"""Per-course watermark settings: form parsing, persistence and render overlay.

Watermarks are deployment configuration, not course content. The admin page
stores them in the site database (``app.catalog.watermark_store``) so the text
never enters ``courses/<slug>/course.json`` or git history, and the build bakes
the layer into the built course bundle. A standalone course therefore keeps its
watermark without the site, the database or an API at play time.

The build injects the overlay into the built composition's entry page rather
than the shell, because both the web player and the MP4 renderer consume that
same composition: one artifact, so the watermark cannot show up in one channel
and be missing from the other.

The module deliberately has no FastAPI import so it can be unit-tested and
reused by scripts. ``scripts`` is imported lazily inside ``rebuild_course``
because production images ship only the ``app`` package.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from html import escape
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.catalog import rebuild_lock, watermark_store
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

# The admin preview renders a fixed number of tiles once, server-side. It must
# cover the densest allowed setting (gapX=120, gapY=80 needs ceil(1920/120) *
# ceil(1080/80) = 224 cells); 255 is the build's over-provisioned tile count.
PREVIEW_TILES = 255

_WRITE_LOCK = rebuild_lock.WRITE_LOCK


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
    """Submitted values, kept for re-rendering the form after an error.

    Numeric/colour fields are sanitised for the preview's inline style
    attributes: a crafted or mistyped value must never be able to add extra CSS
    declarations, and a value outside the contract bounds would render a
    misleading preview anyway.
    """

    corners: dict[str, dict[str, Any]] = {}
    for position, key in POSITION_FIELD_KEYS.items():
        corners[position] = {
            "text": _field(fields, f"corner_{key}_text"),
            "fontSize": _safe_int(
                _field(fields, f"corner_{key}_fontSize"),
                int(CORNER_DEFAULTS["fontSize"]),
                minimum=10,
                maximum=96,
            ),
            "color": _safe_color(
                _field(fields, f"corner_{key}_color"), str(CORNER_DEFAULTS["color"])
            ),
            "opacity": _safe_float(
                _field(fields, f"corner_{key}_opacity"),
                float(CORNER_DEFAULTS["opacity"]),
                minimum=0,
                maximum=1,
            ),
        }
    return {
        "enabled": _checked(fields, "enabled", default=False),
        "corners": corners,
        "repeating": {
            "text": _field(fields, "repeat_text"),
            "fontSize": _safe_int(
                _field(fields, "repeat_fontSize"),
                int(REPEAT_DEFAULTS["fontSize"]),
                minimum=10,
                maximum=96,
            ),
            "color": _safe_color(
                _field(fields, "repeat_color"), str(REPEAT_DEFAULTS["color"])
            ),
            "opacity": _safe_float(
                _field(fields, "repeat_opacity"),
                float(REPEAT_DEFAULTS["opacity"]),
                minimum=0,
                maximum=1,
            ),
            "gapX": _safe_int(
                _field(fields, "repeat_gapX"),
                int(REPEAT_DEFAULTS["gapX"]),
                minimum=120,
                maximum=960,
            ),
            "gapY": _safe_int(
                _field(fields, "repeat_gapY"),
                int(REPEAT_DEFAULTS["gapY"]),
                minimum=80,
                maximum=600,
            ),
            "rotate": _safe_int(
                _field(fields, "repeat_rotate"),
                int(REPEAT_DEFAULTS["rotate"]),
                minimum=-90,
                maximum=90,
            ),
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


# -- built composition overlay --------------------------------------------
#
# The overlay is appended to the *built* composition entry, not to the shell:
# the web player loads that composition in its iframe and the MP4 renderer
# renders it directly, so baking it there is what makes playback and export
# agree. The composition is a fixed 1920x1080 design surface (contract 3.3), so
# every length is a design pixel; the player scales the whole iframe and the
# renderer captures it 1:1.

WATERMARK_CLASS = "course-watermark"
WATERMARK_STYLE_ID = "course-watermark-style"
WATERMARK_MARKER = 'data-course-watermark'
# 2.4% / 2.6% of the 1920px canvas, the same inset the admin preview draws.
_CORNER_INSET_Y = "46px"
_CORNER_INSET_X = "50px"

WATERMARK_CSS = """
/* Course watermark, generated by scripts/build_courses.py. Do not hand-edit
 * built bundles: change course.json's watermark field and rebuild. The layer
 * is inert (no pointer events, no animation, no network) and covers the whole
 * 1920x1080 composition, so it survives fullscreen and lands in the MP4. */
.course-watermark {
  position: fixed;
  inset: 0;
  z-index: 2147483647;
  overflow: hidden;
  pointer-events: none;
  user-select: none;
  -webkit-user-select: none;
}
.course-watermark__corner {
  position: absolute;
  max-width: 46%;
  font-family: var(--font-sans, "Noto Sans SC", sans-serif);
  font-size: calc(var(--wm-font-size, 30) * 1px);
  line-height: 1.35;
  color: var(--wm-color, #16140f);
  opacity: var(--wm-opacity, 0.6);
  overflow-wrap: anywhere;
}
.course-watermark__corner--top-left {
  top: __INSET_Y__;
  left: __INSET_X__;
  text-align: left;
}
.course-watermark__corner--top-right {
  top: __INSET_Y__;
  right: __INSET_X__;
  text-align: right;
}
.course-watermark__corner--bottom-left {
  bottom: __INSET_Y__;
  left: __INSET_X__;
  text-align: left;
}
.course-watermark__corner--bottom-right {
  right: __INSET_X__;
  bottom: __INSET_Y__;
  text-align: right;
}
.course-watermark__repeat {
  position: absolute;
  inset: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, calc(var(--wm-gap-x, 320) * 1px));
  grid-auto-rows: calc(var(--wm-gap-y, 200) * 1px);
  place-items: center;
  justify-content: start;
  align-content: start;
  overflow: hidden;
}
.course-watermark__tile {
  display: block;
  font-family: var(--font-sans, "Noto Sans SC", sans-serif);
  font-size: calc(var(--wm-font-size, 28) * 1px);
  line-height: 1.2;
  color: var(--wm-color, #16140f);
  opacity: var(--wm-opacity, 0.12);
  white-space: nowrap;
  transform: rotate(var(--wm-rotate, -24deg));
  transform-origin: center;
}
/* The visual layer is aria-hidden; attribution is exposed once as hidden copy. */
.course-watermark__attribution {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
  border: 0;
}
""".replace("__INSET_Y__", _CORNER_INSET_Y).replace("__INSET_X__", _CORNER_INSET_X)


def watermark_layer_html(watermark: WatermarkConfig | None) -> str:
    """Markup for the watermark layer, or ``""`` when nothing should render.

    The caller embeds this into the built composition entry. Keeping markup and
    CSS here means the player and the MP4 renderer always draw the same layer.
    """

    if watermark is None or not watermark.enabled:
        return ""
    if watermark.repeating is None and not watermark.corners:
        return ""

    parts: list[str] = [
        f'<div class="{WATERMARK_CLASS}" aria-hidden="true" {WATERMARK_MARKER}>'
    ]
    if watermark.repeating is not None:
        repeating = watermark.repeating
        style = (
            f"--wm-font-size: {repeating.fontSize}; "
            f"--wm-color: {repeating.color}; "
            f"--wm-opacity: {repeating.opacity}; "
            f"--wm-gap-x: {repeating.gapX}; "
            f"--wm-gap-y: {repeating.gapY}; "
            f"--wm-rotate: {repeating.rotate}deg;"
        )
        parts.append(
            f'<div class="{WATERMARK_CLASS}__repeat" style="{style}">'
        )
        tile = escape(repeating.text)
        parts.extend(
            f'<span class="{WATERMARK_CLASS}__tile">{tile}</span>'
            for _ in range(tile_count(repeating))
        )
        parts.append("</div>")
    for mark in watermark.corners:
        style = (
            f"--wm-font-size: {mark.fontSize}; "
            f"--wm-color: {mark.color}; "
            f"--wm-opacity: {mark.opacity};"
        )
        parts.append(
            f'<span class="{WATERMARK_CLASS}__corner '
            f'{WATERMARK_CLASS}__corner--{mark.position}" style="{style}">'
            f"{escape(mark.text)}</span>"
        )
    parts.append("</div>")
    if watermark.corners:
        attribution = "；".join(escape(mark.text) for mark in watermark.corners)
        parts.append(
            f'<p class="{WATERMARK_CLASS}__attribution">课程水印：{attribution}</p>'
        )
    return "".join(parts)


def inject_watermark(entry: Path, watermark: WatermarkConfig | None) -> bool:
    """Bake the watermark layer into a freshly copied composition entry.

    Returns ``True`` when a layer was written. Builds always inject into a new
    staging copy, so an already marked file is left alone instead of gaining a
    second layer.
    """

    markup = watermark_layer_html(watermark)
    if not markup:
        return False
    document = entry.read_text(encoding="utf-8")
    if WATERMARK_MARKER in document:
        return False
    fragment = (
        "\n<!-- course watermark -->\n"
        f'<style id="{WATERMARK_STYLE_ID}">{WATERMARK_CSS}</style>\n'
        f"{markup}\n"
    )
    lowered = document.lower()
    index = lowered.rfind("</body>")
    if index == -1:
        index = lowered.rfind("</html>")
    if index == -1:
        document = document + fragment
    else:
        document = document[:index] + fragment + document[index:]
    entry.write_text(document, encoding="utf-8", newline="\n")
    return True


# -- source manifest -------------------------------------------------------


def manifest_path(settings: Settings, slug: str) -> Path:
    """Source ``course.json`` path, used only to tell whether a rebuild is possible.

    The watermark itself is not stored there any more: this file only decides
    whether the admin page can rebuild the bundle on this machine.
    """

    if not SLUG_PATTERN.fullmatch(slug) or Path(slug).name != slug:
        raise ValueError("课程 slug 不合法")
    return Path(settings.courses_src_dir) / slug / "course.json"


def rebuild_course(
    settings: Settings, slug: str, watermark: WatermarkConfig | None = None
):
    """Rebuild one course bundle from its source directory.

    Imported lazily: production deployments install only ``app`` and never run
    the authoring pipeline. The web process calls this only from the admin page.
    The watermark comes from the caller and is baked into the built bundle; the
    intro/outro selection is read from the database so saving a watermark never
    silently drops a course's clips.
    """

    from app.catalog import clip_store
    from app.catalog.clips import ClipLibrary
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
        watermark=watermark,
        clip_selection=clip_store.load(settings, slug),
        clip_library=ClipLibrary(Path(settings.clips_dir)),
        project_url=settings.project_url,
    )


def apply_watermark(
    settings: Settings, slug: str, watermark: WatermarkConfig | None
):
    """Persist the watermark and rebuild the bundle as one serialised step.

    The database write comes first: if the rebuild fails, the config is already
    stored and the next build picks it up.
    """

    with _WRITE_LOCK:
        watermark_store.save(settings, slug, watermark)
        result = rebuild_course(settings, slug, watermark=watermark)
    return result


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


def _safe_int(raw: str, default: int, *, minimum: int, maximum: int) -> int:
    """Value for the preview inputs, clamped to the contract when malformed."""

    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if minimum <= value <= maximum else default


def _safe_float(raw: str, default: float, *, minimum: float, maximum: float) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if minimum <= value <= maximum else default


def _safe_color(raw: str, default: str) -> str:
    return raw if ACCENT_PATTERN.fullmatch(raw) else default


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
