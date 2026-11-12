"""Per-course watermark settings: form parsing and source-file persistence.

Watermarks are course content. They live in the course's ``course.json`` under
the optional ``watermark`` field and are baked into the built course page, so a
standalone course bundle keeps its watermark without the site, the database or
an API. The admin config page is only a form over this module: it edits the
source ``course.json`` and rebuilds ``dist/courses/<slug>/``.

The module deliberately has no FastAPI import so it can be unit-tested and
reused by scripts. ``scripts`` is imported lazily inside ``rebuild_course``
because production images ship only the ``app`` package.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.catalog.models import (
    ACCENT_PATTERN,
    SLUG_PATTERN,
    CatalogError,
    CornerWatermark,
    RepeatingWatermark,
    WatermarkConfig,
)
from app.config import Settings

POSITIONS: tuple[str, ...] = ("top-left", "top-right", "bottom-left", "bottom-right")
POSITION_LABELS = {
    "top-left": "左上角",
    "top-right": "右上角",
    "bottom-left": "左下角",
    "bottom-right": "右下角",
}
# Form field names cannot use the hyphenated position directly without making
# the parsed keys awkward; keep one explicit mapping on both sides.
POSITION_FIELD_KEYS = {
    "top-left": "top_left",
    "top-right": "top_right",
    "bottom-left": "bottom_left",
    "bottom-right": "bottom_right",
}

MAX_FORM_BYTES = 64 * 1024
MAX_CORNER_TEXT = 80
MAX_REPEAT_TEXT = 48

CORNER_DEFAULTS: dict[str, Any] = {
    "fontSize": 30,
    "color": "#16140f",
    "opacity": 0.6,
}
REPEAT_DEFAULTS: dict[str, Any] = {
    "fontSize": 28,
    "color": "#16140f",
    "opacity": 0.12,
    "gapX": 320,
    "gapY": 200,
    "rotate": -24,
}

# The admin form preview only needs enough tiles to cover a 16:9 box.
PREVIEW_TILES = 160

_WRITE_LOCK = threading.Lock()


# -- form values -----------------------------------------------------------


def form_values(watermark: WatermarkConfig | None) -> dict[str, Any]:
    """Values the config template renders into its inputs."""

    corners: dict[str, dict[str, Any]] = {
        position: {"text": "", **CORNER_DEFAULTS} for position in POSITIONS
    }
    repeating: dict[str, Any] = {"text": "", **REPEAT_DEFAULTS}
    if watermark is not None:
        for mark in watermark.corners:
            corners[mark.position] = {
                "text": mark.text,
                "fontSize": mark.fontSize,
                "color": mark.color,
                "opacity": mark.opacity,
            }
        if watermark.repeating is not None:
            repeating = {
                "text": watermark.repeating.text,
                "fontSize": watermark.repeating.fontSize,
                "color": watermark.repeating.color,
                "opacity": watermark.repeating.opacity,
                "gapX": watermark.repeating.gapX,
                "gapY": watermark.repeating.gapY,
                "rotate": watermark.repeating.rotate,
            }
    return {
        "enabled": True if watermark is None else watermark.enabled,
        "corners": corners,
        "repeating": repeating,
    }


def form_values_from_request(fields: Mapping[str, Any]) -> dict[str, Any]:
    """Submitted values, kept for re-rendering the form after an error."""

    corners: dict[str, dict[str, Any]] = {}
    for position, key in POSITION_FIELD_KEYS.items():
        corners[position] = {
            "text": _field(fields, f"corner_{key}_text"),
            "fontSize": _field(fields, f"corner_{key}_fontSize") or CORNER_DEFAULTS["fontSize"],
            "color": _field(fields, f"corner_{key}_color") or CORNER_DEFAULTS["color"],
            "opacity": _field(fields, f"corner_{key}_opacity") or CORNER_DEFAULTS["opacity"],
        }
    return {
        "enabled": _checked(fields, "enabled", default=False),
        "corners": corners,
        "repeating": {
            "text": _field(fields, "repeat_text"),
            "fontSize": _field(fields, "repeat_fontSize") or REPEAT_DEFAULTS["fontSize"],
            "color": _field(fields, "repeat_color") or REPEAT_DEFAULTS["color"],
            "opacity": _field(fields, "repeat_opacity") or REPEAT_DEFAULTS["opacity"],
            "gapX": _field(fields, "repeat_gapX") or REPEAT_DEFAULTS["gapX"],
            "gapY": _field(fields, "repeat_gapY") or REPEAT_DEFAULTS["gapY"],
            "rotate": _field(fields, "repeat_rotate") or REPEAT_DEFAULTS["rotate"],
        },
    }


def parse_form(fields: Mapping[str, Any]) -> tuple[WatermarkConfig | None, list[str]]:
    """Turn submitted strings into a validated config.

    A blank text field removes that watermark, so an empty form means "no
    watermark" (the manifest key is removed instead of storing an empty object).
    Returns ``(None, [])`` when there is nothing to save, or ``(None, errors)``
    when the submission is invalid.
    """

    errors: list[str] = []
    corners: list[CornerWatermark] = []

    for position in POSITIONS:
        key = POSITION_FIELD_KEYS[position]
        label = POSITION_LABELS[position]
        text = _field(fields, f"corner_{key}_text")
        if not text:
            continue
        if len(text) > MAX_CORNER_TEXT:
            errors.append(f"{label}水印文字最多 {MAX_CORNER_TEXT} 个字，当前 {len(text)} 个。")
            continue
        font_size = _int_field(
            fields,
            f"corner_{key}_fontSize",
            CORNER_DEFAULTS["fontSize"],
            label=f"{label}字号",
            minimum=10,
            maximum=96,
            errors=errors,
        )
        color = _color_field(
            fields, f"corner_{key}_color", CORNER_DEFAULTS["color"], label=f"{label}颜色", errors=errors
        )
        opacity = _float_field(
            fields,
            f"corner_{key}_opacity",
            CORNER_DEFAULTS["opacity"],
            label=f"{label}透明度",
            minimum=0,
            maximum=1,
            errors=errors,
        )
        try:
            corners.append(
                CornerWatermark(
                    position=position,
                    text=text,
                    fontSize=font_size,
                    color=color,
                    opacity=opacity,
                )
            )
        except ValidationError as exc:
            errors.append(f"{label}水印不合法：{_first_validation_message(exc)}")

    repeating = None
    repeat_text = _field(fields, "repeat_text")
    if repeat_text:
        if len(repeat_text) > MAX_REPEAT_TEXT:
            errors.append(f"平铺水印文字最多 {MAX_REPEAT_TEXT} 个字，当前 {len(repeat_text)} 个。")
        else:
            try:
                repeating = RepeatingWatermark(
                    text=repeat_text,
                    fontSize=_int_field(
                        fields,
                        "repeat_fontSize",
                        REPEAT_DEFAULTS["fontSize"],
                        label="平铺水印字号",
                        minimum=10,
                        maximum=96,
                        errors=errors,
                    ),
                    color=_color_field(
                        fields,
                        "repeat_color",
                        REPEAT_DEFAULTS["color"],
                        label="平铺水印颜色",
                        errors=errors,
                    ),
                    opacity=_float_field(
                        fields,
                        "repeat_opacity",
                        REPEAT_DEFAULTS["opacity"],
                        label="平铺水印透明度",
                        minimum=0,
                        maximum=1,
                        errors=errors,
                    ),
                    gapX=_int_field(
                        fields,
                        "repeat_gapX",
                        REPEAT_DEFAULTS["gapX"],
                        label="平铺水印横向间距",
                        minimum=120,
                        maximum=960,
                        errors=errors,
                    ),
                    gapY=_int_field(
                        fields,
                        "repeat_gapY",
                        REPEAT_DEFAULTS["gapY"],
                        label="平铺水印纵向间距",
                        minimum=80,
                        maximum=600,
                        errors=errors,
                    ),
                    rotate=_int_field(
                        fields,
                        "repeat_rotate",
                        REPEAT_DEFAULTS["rotate"],
                        label="平铺水印倾斜角",
                        minimum=-90,
                        maximum=90,
                        errors=errors,
                    ),
                )
            except ValidationError as exc:
                errors.append(f"平铺水印不合法：{_first_validation_message(exc)}")

    if errors:
        return None, errors
    if not corners and repeating is None:
        return None, []
    return (
        WatermarkConfig(
            enabled=_checked(fields, "enabled", default=False),
            corners=corners,
            repeating=repeating,
        ),
        [],
    )


def tile_count(repeating: RepeatingWatermark | None) -> int:
    """How many repeating tiles cover a 16:9 canvas at the configured density."""

    if repeating is None:
        return 0
    columns = math.ceil(1920 / repeating.gapX)
    rows = math.ceil(1080 / repeating.gapY)
    return min(400, (columns + 1) * (rows + 1))


# -- source manifest -------------------------------------------------------


def manifest_path(settings: Settings, slug: str) -> Path:
    if not SLUG_PATTERN.fullmatch(slug) or Path(slug).name != slug:
        raise ValueError("课程 slug 不合法")
    return Path(settings.courses_src_dir) / slug / "course.json"


def read_manifest(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("course.json 顶层必须是对象")
    return raw


def watermark_from_manifest(raw: Mapping[str, Any]) -> WatermarkConfig | None:
    payload = raw.get("watermark")
    if not payload:
        return None
    return WatermarkConfig.model_validate(payload)


def write_manifest(path: Path, raw: Mapping[str, Any]) -> None:
    """Atomically replace the manifest so a failed write never truncates it."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        dir=str(path.parent), prefix=".course-", suffix=".json"
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(raw, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def save_watermark(settings: Settings, slug: str, watermark: WatermarkConfig | None) -> Path:
    path = manifest_path(settings, slug)
    raw = read_manifest(path)
    if watermark is None:
        raw.pop("watermark", None)
    else:
        raw["watermark"] = watermark.model_dump(exclude_none=True)
    write_manifest(path, raw)
    return path


def rebuild_course(settings: Settings, slug: str):
    """Rebuild one course bundle from its source directory.

    Imported lazily: production deployments install only ``app`` and never run
    the authoring pipeline. The web process calls this only from the admin page.
    """

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
    )


def apply_watermark(
    settings: Settings, slug: str, watermark: WatermarkConfig | None
):
    """Persist the watermark and rebuild the bundle as one serialised step."""

    with _WRITE_LOCK:
        path = save_watermark(settings, slug, watermark)
        result = rebuild_course(settings, slug)
    return path, result


def build_error_messages(result: Any) -> list[str]:
    errors: list[CatalogError] = list(getattr(result, "errors", []) or [])
    messages = []
    for error in errors:
        location = " / ".join(
            part for part in (error.code, error.file, error.field) if part
        )
        messages.append(f"{location}：{error.message}" if location else error.message)
    return messages


# -- small parsing helpers -------------------------------------------------


def _first(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)) and value:
        return str(value[0])
    return ""


def _field(fields: Mapping[str, Any], key: str) -> str:
    return _first(fields.get(key)).strip()


def _checked(fields: Mapping[str, Any], key: str, *, default: bool) -> bool:
    if key not in fields:
        return default
    return _field(fields, key) not in {"", "0", "off", "false", "no"}


def _int_field(
    fields: Mapping[str, Any],
    key: str,
    default: int,
    *,
    label: str,
    minimum: int,
    maximum: int,
    errors: list[str],
) -> int:
    raw = _field(fields, key)
    if not raw:
        return int(default)
    try:
        value = int(raw)
    except ValueError:
        errors.append(f"{label}必须是整数。")
        return int(default)
    if not minimum <= value <= maximum:
        errors.append(f"{label}必须在 {minimum} 到 {maximum} 之间。")
        return int(default)
    return value


def _float_field(
    fields: Mapping[str, Any],
    key: str,
    default: float,
    *,
    label: str,
    minimum: float,
    maximum: float,
    errors: list[str],
) -> float:
    raw = _field(fields, key)
    if not raw:
        return float(default)
    try:
        value = float(raw)
    except ValueError:
        errors.append(f"{label}必须是数字。")
        return float(default)
    if not minimum <= value <= maximum:
        errors.append(f"{label}必须在 {minimum:g} 到 {maximum:g} 之间。")
        return float(default)
    return value


def _color_field(
    fields: Mapping[str, Any],
    key: str,
    default: str,
    *,
    label: str,
    errors: list[str],
) -> str:
    raw = _field(fields, key) or default
    if not ACCENT_PATTERN.fullmatch(raw):
        errors.append(f"{label}必须是 #RRGGBB 格式。")
        return default
    return raw


def _first_validation_message(exc: ValidationError) -> str:
    detail = exc.errors()[0]
    return str(detail.get("msg", "字段不合法"))
