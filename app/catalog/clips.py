"""Course intro/outro clips: library, placeholder rendering and build injection.

An intro or outro is not a new content type. It is one more scene of the course
composition, inserted at build time the same way the watermark layer is: the web
player and the MP4 renderer both consume that composition, so one injected scene
appears in both channels and the course bundle stays a plain static package.

The clip library lives in ``clips/<clip-id>/`` at the repository root. A clip is
``clip.json`` (metadata) plus one ``<template>`` scene. Clips are shared by every
course, so the scene may print per-course values through ``{{placeholders}}``.
They are deliberately self-contained: inline CSS and inline SVG only, no image
or font files. That keeps a clip portable into any course bundle and lets the
build prove it introduces no external resource loads.

Which clips a course plays is stored in the site database
(``app.catalog.clip_store``), never in ``course.json``. A course bundle carries
the rendered clip, so it still plays correctly without the database.
"""

from __future__ import annotations

import html
import json
import math
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from app.catalog import rebuild_lock
from app.catalog.assets import FORBIDDEN_CLOCKS, scan_composition
from app.catalog.models import (
    SCREEN_ID_PATTERN,
    CatalogError,
    ClipKind,
    ClipSelection,
    ResolvedCourse,
    ResolvedScreen,
    StrictModel,
)

KIND_LABELS: dict[str, str] = {"intro": "片头", "outro": "片尾"}
MIN_CLIP_SECONDS = 5.0
MAX_CLIP_SECONDS = 30.0

PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z][a-zA-Z0-9_.]*)\s*\}\}")
ROOT_TAG_RE = re.compile(
    r'<div\b[^>]*\bid\s*=\s*["\']root["\'][^>]*>', re.IGNORECASE | re.DOTALL
)
TEMPLATE_RE = re.compile(r"<template\b[^>]*>(?P<body>.*)</template>", re.DOTALL | re.IGNORECASE)
STYLE_BLOCK_RE = re.compile(r"<style\b[^>]*>(?P<css>.*?)</style>", re.DOTALL | re.IGNORECASE)
SCRIPT_BLOCK_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.DOTALL | re.IGNORECASE)


def _attr(name: str) -> re.Pattern[str]:
    return re.compile(rf'(\b{name}\s*=\s*)(["\'])(.*?)\2', re.IGNORECASE | re.DOTALL)


START_ATTR_RE = _attr("data-start")
DURATION_ATTR_RE = _attr("data-duration")
TRACK_ATTR_RE = _attr("data-track-index")


class ClipBuildError(Exception):
    """A clip cannot be inserted; ``errors`` is ready for the build report."""

    def __init__(self, errors: list[CatalogError]) -> None:
        self.errors = errors
        super().__init__(f"{len(errors)} 个片头/片尾错误")


class ClipDefinition(StrictModel):
    """One selectable intro or outro template."""

    schemaVersion: Literal[1] = 1
    id: str
    kind: ClipKind
    title: str
    summary: str
    description: str | None = None
    kicker: str | None = None
    transcript: str | None = None
    duration: float = Field(ge=MIN_CLIP_SECONDS, le=MAX_CLIP_SECONDS)
    scene: str = "scene.html"

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        if not SCREEN_ID_PATTERN.match(value) or len(value) > 32:
            raise ValueError("id 必须匹配 ^[a-z][a-z0-9-]*$ 且为 1–32 个字符")
        return value

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        if not 1 <= len(value) <= 40:
            raise ValueError("title 必须是 1–40 个字符")
        return value

    @field_validator("summary")
    @classmethod
    def _summary(cls, value: str) -> str:
        if not 1 <= len(value) <= 120:
            raise ValueError("summary 必须是 1–120 个字符")
        return value

    @field_validator("description")
    @classmethod
    def _description(cls, value: str | None) -> str | None:
        if value is not None and len(value) > 200:
            raise ValueError("description 最多 200 个字符")
        return value

    @field_validator("kicker")
    @classmethod
    def _kicker(cls, value: str | None) -> str | None:
        if value is not None and not 1 <= len(value) <= 24:
            raise ValueError("kicker 必须是 1–24 个字符")
        return value

    @field_validator("transcript")
    @classmethod
    def _transcript(cls, value: str | None) -> str | None:
        if value is not None and len(value) > 2000:
            raise ValueError("transcript 最多 2000 个字符")
        return value

    @field_validator("scene")
    @classmethod
    def _scene(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*\.html", value):
            raise ValueError("scene 必须是 clip 文件夹内的 .html 文件名")
        return value

    @model_validator(mode="after")
    def _kind_id(self) -> ClipDefinition:
        if not self.id.startswith(f"{self.kind}-"):
            raise ValueError(f"id 必须以 {self.kind!r}- 开头，方便在目录里看出类型")
        return self

    @property
    def label(self) -> str:
        return KIND_LABELS[self.kind]


@dataclass(frozen=True)
class ClipLibraryIssue:
    code: str
    message: str
    clip_id: str | None
    file: str | None


@dataclass(frozen=True)
class ClipContext:
    """Per-course values a clip scene can print through ``{{placeholders}}``."""

    values: dict[str, str]


@dataclass
class ClipPlan:
    """What the build will write, computed without touching the bundle."""

    inserted: list[ResolvedScreen] = field(default_factory=list)
    screens: list[ResolvedScreen] = field(default_factory=list)
    definitions: dict[str, ClipDefinition] = field(default_factory=dict)
    intro_duration: float = 0.0
    outro_duration: float = 0.0
    duration: float = 0.0
    original_duration: float = 0.0
    scenes: dict[str, str] = field(default_factory=dict)
    scene_paths: dict[str, str] = field(default_factory=dict)
    track_indices: dict[str, int] = field(default_factory=dict)

    @property
    def active(self) -> bool:
        return bool(self.inserted)


def _error(
    code: str,
    message: str,
    *,
    slug: str | None,
    file: str | Path | None = None,
    clip_id: str | None = None,
    field_name: str | None = None,
    expected: str | None = None,
) -> CatalogError:
    return CatalogError(
        code=code,
        message=message,
        slug=slug,
        file=str(file) if file is not None else None,
        screen_id=clip_id,
        field=field_name,
        expected=expected,
    )


def _seconds(value: float) -> str:
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return text or "0"


def _scene_id_check(source: str, clip: ClipDefinition) -> list[str]:
    problems: list[str] = []
    if "<template" not in source or (
        'id="root"' not in source and "id='root'" not in source
    ):
        problems.append("scene 必须是包含 <template> 和 id=root 的片段")
    if not re.search(
        rf'data-composition-id\s*=\s*["\']s-{re.escape(clip.id)}["\']', source
    ):
        problems.append(f"scene 的 data-composition-id 必须等于 s-{clip.id}")
    if not re.search(
        rf"window\.__timelines\s*\[\s*[\"']s-{re.escape(clip.id)}[\"']\s*\]", source
    ):
        problems.append(f'scene 必须注册 window.__timelines["s-{clip.id}"]')
    for needle, label in FORBIDDEN_CLOCKS:
        if needle in source:
            problems.append(f"scene 的动画时钟不允许使用 {label}")
    return problems


class ClipLibrary:
    """Scan ``clips/`` and return the valid definitions.

    Invalid clips are reported instead of crashing: the admin page lists what a
    clip needs, and a build only fails when a course actually selects one.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._lock = threading.Lock()
        self._signature: tuple[tuple[str, int, int], ...] | None = None
        self._definitions: list[ClipDefinition] | None = None
        self._issues: list[ClipLibraryIssue] | None = None

    # -- public API ---------------------------------------------------------

    def definitions(self) -> list[ClipDefinition]:
        self._ensure()
        return list(self._definitions or [])

    def issues(self) -> list[ClipLibraryIssue]:
        self._ensure()
        return list(self._issues or [])

    def for_kind(self, kind: ClipKind) -> list[ClipDefinition]:
        return [clip for clip in self.definitions() if clip.kind == kind]

    def get(self, clip_id: str) -> ClipDefinition | None:
        return next((clip for clip in self.definitions() if clip.id == clip_id), None)

    def scene_path(self, clip: ClipDefinition) -> Path:
        return self.root / clip.id / clip.scene

    # -- internals ----------------------------------------------------------

    def _signature_now(self) -> tuple[tuple[str, int, int], ...]:
        entries: list[tuple[str, int, int]] = []
        if not self.root.is_dir():
            return tuple()
        stat = self.root.stat()
        entries.append((str(self.root), stat.st_mtime_ns, 0))
        for directory in sorted(path for path in self.root.iterdir() if path.is_dir()):
            if directory.name.startswith(("_", ".")):
                continue
            for path in sorted(directory.iterdir()):
                if not path.is_file() or path.suffix.lower() not in {".html", ".json"}:
                    continue
                try:
                    info = path.stat()
                except OSError:
                    continue
                entries.append((str(path), info.st_mtime_ns, info.st_size))
        return tuple(entries)

    def _ensure(self) -> None:
        signature = self._signature_now()
        with self._lock:
            if self._definitions is not None and signature == self._signature:
                return
            definitions, issues = self._scan()
            self._definitions = definitions
            self._issues = issues
            self._signature = signature

    def _scan(self) -> tuple[list[ClipDefinition], list[ClipLibraryIssue]]:
        definitions: list[ClipDefinition] = []
        issues: list[ClipLibraryIssue] = []
        if not self.root.is_dir():
            return definitions, issues

        for directory in sorted(
            path for path in self.root.iterdir() if path.is_dir() and not path.name.startswith(("_", "."))
        ):
            manifest = directory / "clip.json"
            if not manifest.is_file():
                issues.append(
                    ClipLibraryIssue(
                        "clip_manifest_missing",
                        "缺少 clip.json，这个片头/片尾不会被列出",
                        directory.name,
                        str(manifest),
                    )
                )
                continue
            try:
                raw = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                issues.append(
                    ClipLibraryIssue(
                        "clip_manifest_invalid",
                        f"clip.json 无法读取：{exc}",
                        directory.name,
                        str(manifest),
                    )
                )
                continue
            try:
                definition = ClipDefinition.model_validate(raw)
            except ValidationError as exc:
                detail = exc.errors()[0]
                location = ".".join(str(part) for part in detail.get("loc", ()))
                issues.append(
                    ClipLibraryIssue(
                        "clip_manifest_invalid",
                        f"{location}: {detail.get('msg', '字段不合法')}",
                        directory.name,
                        str(manifest),
                    )
                )
                continue
            if definition.id != directory.name:
                issues.append(
                    ClipLibraryIssue(
                        "clip_id_mismatch",
                        f"clip.json 的 id={definition.id!r} 与文件夹名 {directory.name!r} 不一致",
                        directory.name,
                        str(manifest),
                    )
                )
                continue
            scene = self.scene_path(definition)
            if not scene.is_file():
                issues.append(
                    ClipLibraryIssue(
                        "clip_scene_missing",
                        f"找不到 scene 文件 {definition.scene}",
                        definition.id,
                        str(scene),
                    )
                )
                continue
            source = scene.read_text(encoding="utf-8", errors="replace")
            problems = _scene_id_check(source, definition)
            if problems:
                issues.append(
                    ClipLibraryIssue(
                        "clip_scene_invalid",
                        "；".join(problems),
                        definition.id,
                        str(scene),
                    )
                )
                continue
            external = scan_composition(directory)
            if external:
                first = external[0]
                issues.append(
                    ClipLibraryIssue(
                        "clip_scene_invalid",
                        f"片头/片尾必须自包含（不加载外部资源）：{first.message}",
                        definition.id,
                        first.file,
                    )
                )
                continue
            definitions.append(definition)
        return definitions, issues


def render_scene(source: str, context: ClipContext, *, clip_id: str, file: str = "") -> str:
    """Substitute ``{{course.title}}``-style placeholders, HTML-escaped."""

    unknown: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in context.values:
            unknown.add(key)
            return match.group(0)
        return html.escape(context.values[key], quote=True)

    rendered = PLACEHOLDER_RE.sub(replace, source)
    if unknown:
        raise ClipBuildError(
            [
                _error(
                    "clip_placeholder_unknown",
                    f"片头/片尾里用了未知占位符：{'、'.join(sorted(unknown))}",
                    slug=None,
                    clip_id=clip_id,
                    file=file,
                    field_name="placeholder",
                    expected="、".join(sorted(context.values)),
                )
            ]
        )
    return rendered


def title_size(title: str) -> int:
    """Fit a course title onto at most two lines of the clip title zone."""

    length = len(title)
    if length <= 12:
        return 120
    if length <= 18:
        return 100
    if length <= 28:
        return 84
    if length <= 34:
        return 74
    return 68


def _mmss(seconds: float) -> str:
    total = max(0, round(seconds))
    return f"{total // 60}:{total % 60:02d}"


def build_context(
    course: ResolvedCourse,
    *,
    site_title: str,
    project_url: str,
    course_url: str,
) -> ClipContext:
    lessons = [screen for screen in course.screens if screen.kind == "lesson"]
    lesson_seconds = sum(screen.duration for screen in lessons)
    label = re.sub(r"^https?://", "", project_url.strip()).rstrip("/")
    label_size = 54 if len(label) <= 36 else 44 if len(label) <= 48 else 36
    # The intro gets one short lead, not the full catalog summary: a 90-character
    # paragraph cannot be read in the few seconds a title card holds.
    lead = course.subtitle or course.summary
    if len(lead) > 56:
        lead = lead[:55].rstrip("，,、；;：: ") + "…"
    return ClipContext(
        {
            "site.title": site_title,
            "project.url": project_url.strip(),
            "project.label": label,
            "project.labelSize": str(label_size),
            "course.title": course.title,
            "course.subtitle": course.subtitle or "",
            "course.lead": lead,
            "course.summary": course.summary,
            "course.slug": course.slug,
            "course.url": course_url,
            "course.accent": course.accent or "#b8452b",
            "course.titleSize": str(title_size(course.title)),
            "course.screenCount": str(len(lessons)),
            "course.meta": f"{len(lessons)} 屏 · {_mmss(lesson_seconds)}",
        }
    )


def _root_info(document: str, *, entry: Path, slug: str) -> tuple[re.Match[str], str, float]:
    match = ROOT_TAG_RE.search(document)
    if match is None:
        raise ClipBuildError(
            [
                _error(
                    "clip_injection_failed",
                    "根 composition 里找不到 id=root 的 div，无法插入片头/片尾",
                    slug=slug,
                    file=entry,
                    field_name="id",
                    expected='<div id="root">',
                )
            ]
        )
    root_tag = match.group(0)
    duration_match = DURATION_ATTR_RE.search(root_tag)
    if duration_match is None:
        raise ClipBuildError(
            [
                _error(
                    "clip_injection_failed",
                    "根 composition 缺少 data-duration，无法计算插入后的总时长",
                    slug=slug,
                    file=entry,
                    field_name="data-duration",
                )
            ]
        )
    try:
        duration = float(duration_match.group(3))
    except ValueError as exc:
        raise ClipBuildError(
            [
                _error(
                    "clip_injection_failed",
                    f"根 data-duration={duration_match.group(3)!r} 不是数字",
                    slug=slug,
                    file=entry,
                    field_name="data-duration",
                )
            ]
        ) from exc
    if not math.isfinite(duration) or duration <= 0:
        raise ClipBuildError(
            [
                _error(
                    "clip_injection_failed",
                    f"根 data-duration={duration_match.group(3)!r} 必须是正数",
                    slug=slug,
                    file=entry,
                    field_name="data-duration",
                )
            ]
        )
    return match, root_tag, duration


def _track_indices(document: str, count: int) -> list[int]:
    used: list[int] = []
    for match in TRACK_ATTR_RE.finditer(document):
        try:
            used.append(int(match.group(3)))
        except ValueError:
            continue
    start = (max(used) + 1) if used else 0
    return list(range(start, start + count))


def _host_markup(
    clip: ClipDefinition,
    *,
    start: float,
    duration: float,
    track_index: int,
    scene_name: str,
) -> str:
    return (
        '      <div\n'
        f'        id="s-{clip.id}"\n'
        f'        data-screen-id="{clip.id}"\n'
        f'        data-composition-id="s-{clip.id}"\n'
        f'        data-composition-src="compositions/{scene_name}"\n'
        f'        data-start="{_seconds(start)}"\n'
        f'        data-duration="{_seconds(duration)}"\n'
        f'        data-track-index="{track_index}"\n'
        '        data-track-kind="graphics"\n'
        '        data-width="1920"\n'
        '        data-height="1080"\n'
        "      ></div>\n"
    )


def _screen_for(clip: ClipDefinition, *, index: int, start: float) -> ResolvedScreen:
    return ResolvedScreen(
        id=clip.id,
        kind=clip.kind,
        kicker=clip.kicker,
        title=clip.title,
        summary=clip.summary,
        transcript=clip.transcript,
        keywords=[],
        index=index,
        start=start,
        duration=clip.duration,
    )


def plan_clips(
    course: ResolvedCourse,
    course_dir: Path,
    selection: ClipSelection | None,
    library: ClipLibrary,
    context: ClipContext,
) -> ClipPlan:
    """Resolve the selected clips and validate everything the build will write.

    Returns an inert plan when no clip is selected, so the caller can always use
    the same code path.
    """

    original = course.composition.duration
    plan = ClipPlan(original_duration=original, duration=original)
    if selection is None or selection.is_empty:
        plan.screens = list(course.screens)
        return plan

    entry = course_dir / course.composition.entry
    try:
        document = entry.read_text(encoding="utf-8")
    except OSError as exc:
        raise ClipBuildError(
            [
                _error(
                    "clip_injection_failed",
                    f"无法读取根 composition：{exc}",
                    slug=course.slug,
                    file=entry,
                )
            ]
        ) from exc
    _match, _root_tag, root_duration = _root_info(document, entry=entry, slug=course.slug)
    if abs(root_duration - original) > 1e-6:
        raise ClipBuildError(
            [
                _error(
                    "clip_injection_failed",
                    "解析出的根时长与 composition 不一致，先重新构建课程",
                    slug=course.slug,
                    file=entry,
                    field_name="data-duration",
                )
            ]
        )

    selected: list[tuple[ClipDefinition, ClipKind]] = []
    errors: list[CatalogError] = []
    for slot, clip_id in (("intro", selection.intro), ("outro", selection.outro)):
        if clip_id is None:
            continue
        clip = library.get(clip_id)
        if clip is None:
            errors.append(
                _error(
                    "clip_missing",
                    f"站点数据库选了 {KIND_LABELS[slot]} {clip_id!r}，但 clips/ 里找不到它",
                    slug=course.slug,
                    file=library.root / clip_id / "clip.json",
                    clip_id=clip_id,
                    field_name=slot,
                    expected="clips/ 下存在的片头/片尾 id",
                )
            )
            continue
        if clip.kind != slot:
            errors.append(
                _error(
                    "clip_kind_mismatch",
                    f"{slot} 位置选了 {clip.kind} 类型的 {clip_id!r}",
                    slug=course.slug,
                    file=library.scene_path(clip),
                    clip_id=clip_id,
                    field_name=slot,
                    expected=slot,
                )
            )
            continue
        selected.append((clip, slot))

    if errors:
        raise ClipBuildError(errors)

    existing_ids = {screen.id for screen in course.screens}
    seen_ids: set[str] = set()
    for clip, _slot in selected:
        if clip.id in existing_ids:
            errors.append(
                _error(
                    "clip_screen_collision",
                    f"课程里已经有 id 为 {clip.id!r} 的屏幕，片头/片尾无法插入",
                    slug=course.slug,
                    file=entry,
                    clip_id=clip.id,
                    field_name="data-screen-id",
                    expected="课程里不重复的屏幕 id",
                )
            )
        if clip.id in seen_ids:
            errors.append(
                _error(
                    "clip_screen_collision",
                    f"同一个片头/片尾被选了两次：{clip.id!r}",
                    slug=course.slug,
                    file=entry,
                    clip_id=clip.id,
                )
            )
        seen_ids.add(clip.id)

    compositions = course_dir / "composition" / "compositions"
    for clip, _slot in selected:
        scene_name = f"clip-{clip.id}.html"
        if (compositions / scene_name).exists():
            errors.append(
                _error(
                    "clip_scene_collision",
                    f"composition/compositions/{scene_name} 已经存在，片头/片尾无法写入",
                    slug=course.slug,
                    file=compositions / scene_name,
                    clip_id=clip.id,
                )
            )
    close_index = document.rfind("</div>")
    if close_index == -1 or close_index < _match.end():
        errors.append(
            _error(
                "clip_injection_failed",
                "根 composition 找不到根 div 的结束标签，无法插入片尾",
                slug=course.slug,
                file=entry,
                field_name="</div>",
            )
        )
    if "<!-- course-clips:" in document:
        errors.append(
            _error(
                "clip_injection_failed",
                "composition 里已经有片头/片尾标记，不能重复插入",
                slug=course.slug,
                file=entry,
                field_name="course-clips",
            )
        )
    if errors:
        raise ClipBuildError(errors)

    tracks = _track_indices(document, len(selected))
    intro = next((clip for clip, slot in selected if slot == "intro"), None)
    outro = next((clip for clip, slot in selected if slot == "outro"), None)
    intro_duration = intro.duration if intro is not None else 0.0
    outro_duration = outro.duration if outro is not None else 0.0
    outro_start = intro_duration + original

    plan.intro_duration = intro_duration
    plan.outro_duration = outro_duration
    plan.duration = intro_duration + original + outro_duration

    screens: list[ResolvedScreen] = []
    if intro is not None:
        screens.append(_screen_for(intro, index=0, start=0.0))
    offset = len(screens)
    for screen in course.screens:
        screens.append(
            screen.model_copy(
                update={
                    "index": screen.index + offset,
                    "start": screen.start + intro_duration,
                }
            )
        )
    if outro is not None:
        screens.append(
            _screen_for(outro, index=len(screens), start=outro_start)
        )
    plan.screens = screens

    track_by_id = {clip.id: tracks[index] for index, (clip, _slot) in enumerate(selected)}
    for clip, _slot in selected:
        source = library.scene_path(clip).read_text(encoding="utf-8", errors="replace")
        try:
            rendered = render_scene(
                source,
                context,
                clip_id=clip.id,
                file=str(library.scene_path(clip)),
            )
        except ClipBuildError as exc:
            for error in exc.errors:
                error.slug = course.slug
            raise
        problems = _scene_id_check(rendered, clip)
        if problems:
            raise ClipBuildError(
                [
                    _error(
                        "clip_scene_invalid",
                        "；".join(problems),
                        slug=course.slug,
                        file=library.scene_path(clip),
                        clip_id=clip.id,
                    )
                ]
            )
        scene_name = f"clip-{clip.id}.html"
        plan.scenes[clip.id] = rendered
        plan.scene_paths[clip.id] = f"compositions/{scene_name}"
        plan.track_indices[clip.id] = track_by_id[clip.id]
        plan.definitions[clip.id] = clip
        screen = next(item for item in screens if item.id == clip.id)
        plan.inserted.append(screen)
    return plan


def inject_clips(entry: Path, plan: ClipPlan) -> None:
    """Write the clip scenes into a freshly copied composition and rewrite its root."""

    if not plan.active:
        return
    document = entry.read_text(encoding="utf-8")
    match, root_tag, duration = _root_info(document, entry=entry, slug="")
    if abs(duration - plan.original_duration) > 1e-6:
        raise ClipBuildError(
            [
                _error(
                    "clip_injection_failed",
                    "构建副本的根时长与源课程不一致",
                    slug=None,
                    file=entry,
                    field_name="data-duration",
                )
            ]
        )

    body = document[match.end():]
    close_index = body.rfind("</div>")
    if close_index == -1:
        raise ClipBuildError(
            [
                _error(
                    "clip_injection_failed",
                    "根 composition 找不到根 div 的结束标签",
                    slug=None,
                    file=entry,
                    field_name="</div>",
                )
            ]
        )

    def shift(match_: re.Match[str]) -> str:
        raw = match_.group(3)
        try:
            value = float(raw)
        except ValueError as exc:
            raise ClipBuildError(
                [
                    _error(
                        "clip_injection_failed",
                        f"data-start={raw!r} 不是数字，无法平移时间",
                        slug=None,
                        file=entry,
                        field_name="data-start",
                    )
                ]
            ) from exc
        if not math.isfinite(value):
            raise ClipBuildError(
                [
                    _error(
                        "clip_injection_failed",
                        f"data-start={raw!r} 不是有限数字",
                        slug=None,
                        file=entry,
                        field_name="data-start",
                    )
                ]
            )
        return f"{match_.group(1)}{match_.group(2)}{_seconds(value + plan.intro_duration)}{match_.group(2)}"

    shifted_body = START_ATTR_RE.sub(shift, body) if plan.intro_duration else body
    new_root_tag = DURATION_ATTR_RE.sub(
        lambda m: f"{m.group(1)}{m.group(2)}{_seconds(plan.duration)}{m.group(2)}",
        root_tag,
        count=1,
    )

    intro_html = ""
    outro_html = ""
    inserted_by_kind = {screen.kind: screen for screen in plan.inserted}
    if "intro" in inserted_by_kind:
        screen = inserted_by_kind["intro"]
        intro_html = _host_markup(
            plan.definitions[screen.id],
            start=0.0,
            duration=plan.intro_duration,
            track_index=plan.track_indices[screen.id],
            scene_name=plan.scene_paths[screen.id].removeprefix("compositions/"),
        )
    if "outro" in inserted_by_kind:
        screen = inserted_by_kind["outro"]
        outro_html = _host_markup(
            plan.definitions[screen.id],
            start=plan.intro_duration + plan.original_duration,
            duration=plan.outro_duration,
            track_index=plan.track_indices[screen.id],
            scene_name=plan.scene_paths[screen.id].removeprefix("compositions/"),
        )

    compositions_dir = entry.parent / "compositions"
    if not compositions_dir.is_dir():
        raise ClipBuildError(
            [
                _error(
                    "clip_injection_failed",
                    "课程 composition 缺少 compositions/ 目录",
                    slug=None,
                    file=compositions_dir,
                )
            ]
        )
    for clip_id, rendered in plan.scenes.items():
        target = entry.parent / plan.scene_paths[clip_id]
        if target.exists():
            raise ClipBuildError(
                [
                    _error(
                        "clip_scene_collision",
                        f"{plan.scene_paths[clip_id]} 已经存在，拒绝覆盖",
                        slug=None,
                        file=target,
                        clip_id=clip_id,
                    )
                ]
            )
        target.write_text(rendered, encoding="utf-8", newline="\n")

    # Keep the closing </div> where it was and put the outro above it, so the
    # root composition stays readable: intro, lesson hosts, outro, close.
    body_before_close = shifted_body[:close_index]
    indent_start = len(body_before_close)
    while indent_start > 0 and body_before_close[indent_start - 1] in " \t":
        indent_start -= 1
    new_body = (
        "\n"
        f"      <!-- course-clips: {', '.join(sorted(plan.scenes))} -->\n"
        + intro_html
        + body_before_close[:indent_start].lstrip("\n")
        + outro_html
        + body_before_close[indent_start:]
        + shifted_body[close_index:]
    )
    entry.write_text(
        document[: match.start()] + new_root_tag + new_body,
        encoding="utf-8",
        newline="\n",
    )


def apply_plan(course: ResolvedCourse, plan: ClipPlan) -> ResolvedCourse:
    """Return the resolved course as the player will see it, clips included."""

    if not plan.active:
        return course
    payload = course.model_dump()
    payload["composition"]["duration"] = plan.duration
    payload["screens"] = [screen.model_dump() for screen in plan.screens]
    payload["stats"] = {
        "screenCount": len(plan.screens),
        "durationSeconds": plan.duration,
        "estimatedMinutes": max(1, math.ceil(plan.duration / 60)),
    }
    return ResolvedCourse.model_validate(payload)


def plan_fingerprint(plan: ClipPlan, selection: ClipSelection) -> str:
    """Stable text mixed into ``contentHash`` so a clip change marks a video stale."""

    if not plan.active:
        return ""
    payload = {
        "selection": selection.model_dump(),
        "scenes": plan.scenes,
        "screens": [screen.model_dump() for screen in plan.inserted],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


# -- site-side rebuild -----------------------------------------------------
#
# The admin page saves the selection and rebuilds the bundle as one serialised
# step. The build script and the watermark editor import this module at import
# time, so the database and authoring imports stay lazy here.

_WRITE_LOCK = rebuild_lock.WRITE_LOCK


def rebuild_course(settings: Any, slug: str, selection: ClipSelection | None):
    """Rebuild one course with its selected clips and its stored watermark."""

    from app.catalog import watermark_store
    from scripts.build_courses import build_course

    return build_course(
        Path(settings.courses_src_dir) / slug,
        out_root=Path(settings.courses_dist_dir),
        runtime_dir=Path(settings.runtime_dir),
        include_drafts=bool(settings.include_drafts),
        site_url=settings.site_url,
        site_title=settings.site_title,
        course_base_url=settings.course_base_url,
        progress_sync=True,
        watermark=watermark_store.load(settings, slug),
        clip_selection=selection,
        clip_library=ClipLibrary(Path(settings.clips_dir)),
        project_url=settings.project_url,
    )


def apply_selection(settings: Any, slug: str, selection: ClipSelection | None):
    """Persist the selection and rebuild the bundle as one serialised step.

    The database write comes first: if the rebuild fails, the config is already
    stored and the next build picks it up.
    """

    from app.catalog import clip_store

    with _WRITE_LOCK:
        clip_store.save(settings, slug, selection)
        result = rebuild_course(settings, slug, selection)
    return result


# -- admin preview ---------------------------------------------------------


def clip_frame_html(definition: ClipDefinition, scene_source: str, context: ClipContext) -> str:
    rendered = render_scene(scene_source, context, clip_id=definition.id)
    template = TEMPLATE_RE.search(rendered)
    if template is None:
        raise ClipBuildError(
            [
                _error(
                    "clip_scene_invalid",
                    "scene 缺少 <template> 包裹",
                    slug=None,
                    clip_id=definition.id,
                )
            ]
        )
    body = template.group("body")
    styles = "\n".join(match.group("css") for match in STYLE_BLOCK_RE.finditer(body))
    markup = SCRIPT_BLOCK_RE.sub("", STYLE_BLOCK_RE.sub("", body)).strip()
    return f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{html.escape(definition.title)} · 预览</title>
    <style>
      @font-face {{
        font-family: "Noto Sans SC";
        src: url("/static/fonts/NotoSansSC-VF.woff2") format("woff2");
        font-weight: 100 900;
        font-display: swap;
      }}
      html, body {{
        width: 100%;
        height: 100%;
        margin: 0;
        padding: 0;
        overflow: hidden;
        background: #f4efe6;
        color: #16140f;
        font-family: "Noto Sans SC", sans-serif;
      }}
{styles}
      /* Preview only: the still is the end state, so reveal what the timeline
       * would have faded in. The root is pinned to the 1920×1080 design surface
       * because the frame viewport is the iframe size; clip_frame.js scales it. */
      #root {{
        width: 1920px;
        height: 1080px;
      }}
      #root *,
      #root *::before,
      #root *::after {{
        opacity: 1 !important;
      }}
    </style>
  </head>
  <body>
{markup}
    <script src="/static/clip_frame.js" defer></script>
  </body>
</html>
"""
