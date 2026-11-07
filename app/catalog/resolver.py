"""Merge ``course.json`` with the root composition and validate the result.

The resolver is the only place where screen timings are derived. It produces a
``ResolvedCourse`` or raises ``CourseResolutionError`` carrying every concrete
problem it could find.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

from pydantic import ValidationError

from app.catalog.composition import CompositionParseError, ScreenHost, parse_composition
from app.catalog.models import (
    SCREEN_ID_PATTERN,
    CatalogError,
    CourseSource,
    CourseStats,
    ResolvedComposition,
    ResolvedCourse,
    ResolvedScreen,
)


class CourseResolutionError(Exception):
    def __init__(self, errors: list[CatalogError]) -> None:
        self.errors = errors
        codes = ", ".join(sorted({error.code for error in errors}))
        super().__init__(f"课程解析失败（{codes}）")


def _error(
    code: str,
    message: str,
    *,
    slug: str | None,
    file: str | None = None,
    screen_id: str | None = None,
    field: str | None = None,
    expected: str | None = None,
) -> CatalogError:
    return CatalogError(
        code=code,
        message=message,
        slug=slug,
        file=file,
        screen_id=screen_id,
        field=field,
        expected=expected,
    )


def _field_name(location: tuple[object, ...]) -> str:
    parts: list[str] = []
    for item in location:
        if isinstance(item, int):
            if parts:
                parts[-1] = f"{parts[-1]}[{item}]"
            else:
                parts.append(f"[{item}]")
        else:
            parts.append(str(item))
    return ".".join(parts)


def _manifest_errors(
    exc: ValidationError, *, slug: str | None, path: Path, raw: object
) -> list[CatalogError]:
    errors: list[CatalogError] = []
    for detail in exc.errors():
        location = tuple(detail.get("loc", ()))
        field = _field_name(location)
        screen_id: str | None = None
        if (
            len(location) >= 2
            and location[0] == "screens"
            and isinstance(location[1], int)
            and isinstance(raw, dict)
        ):
            screens = raw.get("screens")
            if isinstance(screens, list) and location[1] < len(screens):
                item = screens[location[1]]
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    screen_id = item["id"]
        errors.append(
            _error(
                "manifest_invalid",
                str(detail.get("msg", "清单字段不合法")),
                slug=slug,
                file=str(path),
                field=field,
                screen_id=screen_id,
                expected=str(detail.get("type", "合法值")),
            )
        )
    return errors


def _scene_id_ok(scene_path: Path, expected_id: str) -> bool:
    return bool(
        re.search(
            rf'data-composition-id\s*=\s*["\']{re.escape(expected_id)}["\']',
            scene_path.read_text(encoding="utf-8"),
        )
    )


def _timeline_registered(scene_path: Path, expected_id: str) -> bool:
    source = scene_path.read_text(encoding="utf-8")
    return bool(
        re.search(
            rf"window\.__timelines\s*\[\s*[\"']{re.escape(expected_id)}[\"']\s*\]",
            source,
        )
    )


def _scene_template_ok(scene_path: Path) -> bool:
    source = scene_path.read_text(encoding="utf-8")
    return "<template" in source and 'id="root"' in source


def resolve_course(course_dir: Path, *, slug: str | None = None) -> ResolvedCourse:
    """Resolve ``course_dir`` into a ``ResolvedCourse``.

    ``slug`` defaults to the directory name. ``course_dir`` is the source
    ``courses/<slug>/`` directory, never the built one.
    """

    course_dir = course_dir.resolve()
    course_slug = slug or course_dir.name
    manifest_path = course_dir / "course.json"
    errors: list[CatalogError] = []

    if not manifest_path.is_file():
        raise CourseResolutionError(
            [
                _error(
                    "manifest_invalid",
                    "找不到 course.json",
                    slug=course_slug,
                    file=str(manifest_path),
                    expected="course.json",
                )
            ]
        )

    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CourseResolutionError(
            [
                _error(
                    "manifest_invalid",
                    f"course.json 无法读取或不是合法 JSON：{exc}",
                    slug=course_slug,
                    file=str(manifest_path),
                    expected="合法 JSON 对象",
                )
            ]
        ) from exc

    if not isinstance(raw, dict):
        raise CourseResolutionError(
            [
                _error(
                    "manifest_invalid",
                    "course.json 顶层必须是对象",
                    slug=course_slug,
                    file=str(manifest_path),
                    expected="JSON object",
                )
            ]
        )

    try:
        source = CourseSource.model_validate(raw)
    except ValidationError as exc:
        raise CourseResolutionError(
            _manifest_errors(exc, slug=course_slug, path=manifest_path, raw=raw)
        ) from exc

    if source.slug != course_slug:
        errors.append(
            _error(
                "slug_mismatch",
                f"清单 slug={source.slug!r} 与目录名 {course_slug!r} 不一致",
                slug=course_slug,
                file=str(manifest_path),
                field="slug",
                expected=course_slug,
            )
        )

    if source.cover and not (course_dir / source.cover).is_file():
        errors.append(
            _error(
                "cover_missing",
                f"cover={source.cover!r} 指向的文件不存在",
                slug=course_slug,
                file=str(course_dir / source.cover),
                field="cover",
                expected="存在的相对路径",
            )
        )

    entry_path = course_dir / source.composition.entry
    if not entry_path.is_file():
        errors.append(
            _error(
                "composition_missing",
                f"找不到 composition.entry：{source.composition.entry}",
                slug=course_slug,
                file=str(entry_path),
                field="composition.entry",
                expected="存在的 HTML 文件",
            )
        )
        raise CourseResolutionError(errors)

    try:
        parsed = parse_composition(entry_path)
    except CompositionParseError as exc:
        errors.append(
            _error(
                exc.code,
                exc.message,
                slug=course_slug,
                file=str(entry_path),
                screen_id=exc.screen_id,
                field=exc.field,
                expected=exc.expected,
            )
        )
        raise CourseResolutionError(errors) from exc

    errors.extend(_validate_hosts(parsed.hosts, source, entry_path, course_slug))

    if errors:
        raise CourseResolutionError(errors)

    meta_by_id = {screen.id: screen for screen in source.screens}
    hosts = sorted(parsed.hosts, key=lambda host: host.start)
    screens: list[ResolvedScreen] = []
    for index, host in enumerate(hosts):
        meta = meta_by_id[host.screen_id]
        screens.append(
            ResolvedScreen(
                **meta.model_dump(),
                index=index,
                start=host.start,
                duration=host.duration,
            )
        )

    if parsed.width is not None and parsed.width != source.composition.width:
        errors.append(
            _error(
                "composition_size_invalid",
                f"根 data-width={parsed.width} 与清单 width={source.composition.width} 不一致",
                slug=course_slug,
                file=str(entry_path),
                field="data-width",
                expected=str(source.composition.width),
            )
        )
    if parsed.height is not None and parsed.height != source.composition.height:
        errors.append(
            _error(
                "composition_size_invalid",
                f"根 data-height={parsed.height} 与清单 height={source.composition.height} 不一致",
                slug=course_slug,
                file=str(entry_path),
                field="data-height",
                expected=str(source.composition.height),
            )
        )

    last_end = max(host.start + host.duration for host in hosts)
    for host in hosts:
        scene_path = _resolve_scene_path(course_dir, source.composition.entry, host)
        if scene_path is None or not scene_path.is_file():
            errors.append(
                _error(
                    "scene_missing",
                    f"屏幕 {host.screen_id} 的 scene 文件不存在：{host.src}",
                    slug=course_slug,
                    file=str(scene_path) if scene_path else host.src,
                    screen_id=host.screen_id,
                    field="data-composition-src",
                    expected="compositions/ 下存在的 HTML 文件",
                )
            )
            continue
        if not _scene_template_ok(scene_path):
            errors.append(
                _error(
                    "scene_invalid",
                    f"scene {host.screen_id} 必须是包含 <template> 和 id=root 的片段",
                    slug=course_slug,
                    file=str(scene_path),
                    screen_id=host.screen_id,
                    field="template",
                    expected="<template> 内含 <div id=\"root\">",
                )
            )
        if not _scene_id_ok(scene_path, f"s-{host.screen_id}"):
            errors.append(
                _error(
                    "scene_id_mismatch",
                    f"scene 的 data-composition-id 必须等于 s-{host.screen_id}",
                    slug=course_slug,
                    file=str(scene_path),
                    screen_id=host.screen_id,
                    field="data-composition-id",
                    expected=f"s-{host.screen_id}",
                )
            )
        if not _timeline_registered(scene_path, f"s-{host.screen_id}"):
            errors.append(
                _error(
                    "timeline_missing",
                    f"scene 没有注册 window.__timelines[\"s-{host.screen_id}\"]",
                    slug=course_slug,
                    file=str(scene_path),
                    screen_id=host.screen_id,
                    field="window.__timelines",
                    expected=f'window.__timelines["s-{host.screen_id}"]',
                )
            )

    if parsed.duration + 1e-6 < last_end:
        errors.append(
            _error(
                "root_duration_short",
                f"根 data-duration={parsed.duration} 小于最后一屏结束时间 {last_end}",
                slug=course_slug,
                file=str(entry_path),
                field="data-duration",
                expected=f">= {last_end}",
            )
        )

    if errors:
        raise CourseResolutionError(errors)

    stats = CourseStats(
        screenCount=len(screens),
        durationSeconds=parsed.duration,
        estimatedMinutes=max(1, math.ceil(parsed.duration / 60)),
    )
    payload = source.model_dump()
    payload["composition"] = ResolvedComposition(
        **source.composition.model_dump(), duration=parsed.duration
    ).model_dump()
    payload["screens"] = [screen.model_dump() for screen in screens]
    payload["stats"] = stats.model_dump()
    return ResolvedCourse.model_validate(payload)


def _resolve_scene_path(course_dir: Path, entry: str, host: ScreenHost) -> Path | None:
    if not host.src:
        return None
    if host.src.startswith("/") or ".." in host.src.split("/"):
        return None
    return course_dir / "composition" / host.src


def _validate_hosts(
    hosts: list[ScreenHost],
    source: CourseSource,
    entry_path: Path,
    slug: str,
) -> list[CatalogError]:
    errors: list[CatalogError] = []
    seen: set[str] = set()
    seen_tracks: set[int] = set()

    if not hosts:
        errors.append(
            _error(
                "composition_invalid",
                "根 composition 里没有任何 data-screen-id host",
                slug=slug,
                file=str(entry_path),
                field="data-screen-id",
                expected="至少一个 host",
            )
        )
        return errors

    previous_start: float | None = None
    for host in hosts:
        if not SCREEN_ID_PATTERN.match(host.screen_id) or len(host.screen_id) > 32:
            errors.append(
                _error(
                    "screen_id_invalid",
                    f"屏幕 id {host.screen_id!r} 不符合命名规则",
                    slug=slug,
                    file=str(entry_path),
                    screen_id=host.screen_id,
                    field="data-screen-id",
                    expected="^[a-z][a-z0-9-]*$，1–32 字符",
                )
            )
        if host.screen_id in seen:
            errors.append(
                _error(
                    "screen_id_duplicate",
                    f"屏幕 id {host.screen_id!r} 重复",
                    slug=slug,
                    file=str(entry_path),
                    screen_id=host.screen_id,
                    field="data-screen-id",
                    expected="全课唯一",
                )
            )
        seen.add(host.screen_id)

        expected_element_id = f"s-{host.screen_id}"
        if host.element_id != expected_element_id:
            errors.append(
                _error(
                    "host_id_mismatch",
                    f"host id={host.element_id!r}，应为 {expected_element_id!r}",
                    slug=slug,
                    file=str(entry_path),
                    screen_id=host.screen_id,
                    field="id",
                    expected=expected_element_id,
                )
            )
        if host.composition_id != expected_element_id:
            errors.append(
                _error(
                    "host_id_mismatch",
                    f"host data-composition-id={host.composition_id!r}，应为 {expected_element_id!r}",
                    slug=slug,
                    file=str(entry_path),
                    screen_id=host.screen_id,
                    field="data-composition-id",
                    expected=expected_element_id,
                )
            )
        if not host.src:
            errors.append(
                _error(
                    "scene_missing",
                    f"屏幕 {host.screen_id} 缺少 data-composition-src",
                    slug=slug,
                    file=str(entry_path),
                    screen_id=host.screen_id,
                    field="data-composition-src",
                    expected="compositions/NN-<id>.html",
                )
            )
        if host.track_index is None:
            errors.append(
                _error(
                    "host_track_missing",
                    f"屏幕 {host.screen_id} 缺少 data-track-index",
                    slug=slug,
                    file=str(entry_path),
                    screen_id=host.screen_id,
                    field="data-track-index",
                    expected="唯一整数",
                )
            )
        elif host.track_index in seen_tracks:
            errors.append(
                _error(
                    "host_track_duplicate",
                    f"data-track-index={host.track_index} 重复",
                    slug=slug,
                    file=str(entry_path),
                    screen_id=host.screen_id,
                    field="data-track-index",
                    expected="全课唯一整数",
                )
            )
        else:
            seen_tracks.add(host.track_index)

        if previous_start is not None and host.start <= previous_start:
            errors.append(
                _error(
                    "host_order_invalid",
                    f"host 未按 data-start 严格升序：{previous_start} → {host.start}",
                    slug=slug,
                    file=str(entry_path),
                    screen_id=host.screen_id,
                    field="data-start",
                    expected="严格大于上一屏的 data-start",
                )
            )
        previous_start = host.start

    ordered = sorted(hosts, key=lambda host: host.start)
    for left, right in zip(ordered, ordered[1:], strict=False):
        left_end = left.start + left.duration
        if right.start + 1e-6 < left_end:
            errors.append(
                _error(
                    "host_overlap",
                    f"屏幕 {left.screen_id} 与 {right.screen_id} 时间重叠",
                    slug=slug,
                    file=str(entry_path),
                    screen_id=right.screen_id,
                    field="data-start",
                    expected=f">= {left_end}",
                )
            )

    meta_ids = {screen.id for screen in source.screens}
    host_ids = {host.screen_id for host in hosts}
    for screen_id in sorted(meta_ids - host_ids):
        errors.append(
            _error(
                "screen_meta_orphan",
                f"清单里有屏幕 {screen_id!r}，composition 里没有 host",
                slug=slug,
                file=str(entry_path),
                screen_id=screen_id,
                field="screens",
                expected=f"data-screen-id={screen_id!r} 的 host",
            )
        )
    for screen_id in sorted(host_ids - meta_ids):
        errors.append(
            _error(
                "screen_host_orphan",
                f"composition 里有 host {screen_id!r}，清单里没有元数据",
                slug=slug,
                file=str(entry_path),
                screen_id=screen_id,
                field="screens",
                expected="对应的 screens[] 项",
            )
        )
    return errors
