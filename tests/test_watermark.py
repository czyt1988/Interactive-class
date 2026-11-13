"""Tests for the per-course watermark contract, form parsing, DB storage and build output.

A watermark must never enter ``courses/<slug>/course.json`` or git history, so
these tests also pin where the config lives: the site database, not the source.
"""

from __future__ import annotations

import json
import math
import re
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from app import models as _models  # noqa: F401  (registers course_watermarks on Base)
from app.catalog.models import WatermarkConfig
from app.catalog.watermark import (
    PREVIEW_TILES,
    form_values,
    form_values_from_request,
    inject_watermark,
    parse_form,
    tile_count,
)
from app.catalog.watermark_store import load, load_all, save
from app.config import Settings
from app.db import Base, create_db_engine
from scripts.build_courses import build_course

FIXTURES = Path(__file__).parent / "fixtures" / "courses"
SLUG = "valid-two-screen"


def _settings(tmp_path: Path, **overrides) -> Settings:
    return Settings(
        env="dev",
        courses_src_dir=tmp_path / "courses",
        courses_dist_dir=tmp_path / "dist" / "courses",
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        **overrides,
    )


def _create_watermark_table(settings: Settings) -> None:
    engine = create_db_engine(settings.database_url)
    Base.metadata.create_all(engine)
    engine.dispose()


def _watermark_payload() -> dict:
    return {
        "enabled": True,
        "corners": [
            {
                "position": "top-left",
                "text": "作者：张三",
                "fontSize": 30,
                "color": "#16140f",
                "opacity": 0.6,
            },
            {
                "position": "bottom-right",
                "text": "示例公司",
                "fontSize": 24,
                "color": "#b8452b",
                "opacity": 0.5,
            },
        ],
        "repeating": {
            "text": "内部资料，请勿外传",
            "fontSize": 28,
            "color": "#16140f",
            "opacity": 0.12,
            "gapX": 320,
            "gapY": 200,
            "rotate": -24,
        },
    }


def _fields(**overrides: str) -> dict[str, list[str]]:
    fields = {
        "enabled": ["1"],
        "corner_top_left_text": ["作者：张三"],
        "corner_top_left_fontSize": ["30"],
        "corner_top_left_color": ["#16140f"],
        "corner_top_left_opacity": ["0.6"],
        "corner_bottom_right_text": ["示例公司"],
        "corner_bottom_right_fontSize": ["24"],
        "corner_bottom_right_color": ["#b8452b"],
        "corner_bottom_right_opacity": ["0.5"],
        "repeat_text": ["内部资料，请勿外传"],
        "repeat_fontSize": ["28"],
        "repeat_color": ["#16140f"],
        "repeat_opacity": ["0.12"],
        "repeat_gapX": ["320"],
        "repeat_gapY": ["200"],
        "repeat_rotate": ["-24"],
    }
    fields.update({key: [value] for key, value in overrides.items()})
    return fields


# -- schema ----------------------------------------------------------------


def test_watermark_config_round_trips() -> None:
    watermark = WatermarkConfig.model_validate(_watermark_payload())
    assert [mark.position for mark in watermark.corners] == ["top-left", "bottom-right"]
    assert watermark.repeating is not None
    assert watermark.repeating.gapX == 320
    serialized = watermark.model_dump(exclude_none=True)
    assert serialized["corners"][0]["text"] == "作者：张三"


def test_duplicate_corner_is_rejected() -> None:
    payload = _watermark_payload()
    payload["corners"].append(
        {"position": "top-left", "text": "第二作者", "fontSize": 20, "color": "#16140f", "opacity": 0.4}
    )
    with pytest.raises(ValidationError, match="角落重复"):
        WatermarkConfig.model_validate(payload)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (("corners", 0, "text", ""), "watermark.corners"),
        (("corners", 0, "fontSize", 9), "fontSize"),
        (("corners", 0, "color", "#fff"), "#RRGGBB"),
        (("corners", 0, "opacity", 1.5), "opacity"),
        (("repeating", "gapX", 100), "gapX"),
        (("repeating", "rotate", 120), "rotate"),
    ],
)
def test_invalid_watermark_values_are_rejected(mutation: tuple, message: str) -> None:
    payload = _watermark_payload()
    target: object = payload
    for part in mutation[:-2]:
        target = target[part]  # type: ignore[index]
    target[mutation[-2]] = mutation[-1]  # type: ignore[index]
    with pytest.raises(ValidationError, match=message):
        WatermarkConfig.model_validate(payload)


def test_unknown_watermark_field_is_rejected() -> None:
    payload = _watermark_payload()
    payload["repeating"]["gap"] = 10
    with pytest.raises(ValidationError, match="Extra inputs"):
        WatermarkConfig.model_validate(payload)


# -- form parsing ----------------------------------------------------------


def test_parse_form_builds_a_valid_config() -> None:
    watermark, errors = parse_form(_fields())
    assert errors == []
    assert watermark is not None and watermark.enabled
    assert [(mark.position, mark.text) for mark in watermark.corners] == [
        ("top-left", "作者：张三"),
        ("bottom-right", "示例公司"),
    ]
    assert watermark.repeating is not None
    assert watermark.repeating.text == "内部资料，请勿外传"


def test_parse_form_fills_defaults_for_blank_numbers() -> None:
    watermark, errors = parse_form(
        {
            "enabled": ["1"],
            "corner_top_left_text": ["署名"],
            "repeat_text": ["内部资料"],
        }
    )
    assert errors == []
    assert watermark is not None
    mark = watermark.corners[0]
    assert (mark.fontSize, mark.color, mark.opacity) == (30, "#16140f", 0.6)
    assert watermark.repeating is not None
    assert (watermark.repeating.gapX, watermark.repeating.gapY, watermark.repeating.rotate) == (
        320,
        200,
        -24,
    )


def test_blank_form_means_no_watermark() -> None:
    assert parse_form({}) == (None, [])
    assert parse_form({"enabled": ["1"]}) == (None, [])


def test_unchecked_master_switch_keeps_the_config_but_disables_it() -> None:
    watermark, errors = parse_form({"corner_top_left_text": ["作者：张三"]})
    assert errors == []
    assert watermark is not None
    assert watermark.enabled is False
    assert watermark.corners[0].text == "作者：张三"


def test_parse_form_reports_friendly_errors() -> None:
    _, errors = parse_form(
        _fields(
            corner_top_left_fontSize="9",
            corner_top_left_color="red",
            corner_top_left_opacity="2",
            repeat_gapX="10",
            repeat_text="长" * 49,
        )
    )
    joined = " ".join(errors)
    assert "左上角字号必须在 10 到 96 之间" in joined
    assert "左上角颜色必须是 #RRGGBB 格式" in joined
    assert "左上角透明度必须在 0 到 1 之间" in joined
    assert "平铺水印文字最多 48 个字" in joined


def test_form_values_round_trip_through_the_form() -> None:
    watermark = WatermarkConfig.model_validate(_watermark_payload())
    values = form_values(watermark)
    assert values["corners"]["top-left"]["text"] == "作者：张三"
    assert values["corners"]["top-right"]["text"] == ""
    assert values["repeating"]["text"] == "内部资料，请勿外传"
    parsed, errors = parse_form(
        {
            f"corner_{key.replace('-', '_')}_{field}": [str(values["corners"][key][field])]
            for key in ("top-left", "bottom-right")
            for field in ("text", "fontSize", "color", "opacity")
        }
        | {
            "enabled": ["1"],
            "repeat_text": [values["repeating"]["text"]],
            "repeat_fontSize": [str(values["repeating"]["fontSize"])],
            "repeat_color": [values["repeating"]["color"]],
            "repeat_opacity": [str(values["repeating"]["opacity"])],
            "repeat_gapX": [str(values["repeating"]["gapX"])],
            "repeat_gapY": [str(values["repeating"]["gapY"])],
            "repeat_rotate": [str(values["repeating"]["rotate"])],
        }
    )
    assert errors == []
    assert parsed is not None
    assert parsed.model_dump(exclude_none=True) == watermark.model_dump(exclude_none=True)


def test_form_values_from_request_keeps_submitted_values() -> None:
    values = form_values_from_request(
        {"enabled": ["1"], "corner_top_left_text": ["草稿"], "corner_top_left_fontSize": ["44"]}
    )
    assert values["enabled"] is True
    assert values["corners"]["top-left"]["text"] == "草稿"
    assert values["corners"]["top-left"]["fontSize"] == 44
    assert values["corners"]["bottom-left"]["text"] == ""


def test_form_values_from_request_sanitises_preview_style_values() -> None:
    values = form_values_from_request(
        {
            "enabled": ["1"],
            "corner_top_left_color": ["#fff; background: url(x)"],
            "corner_top_left_fontSize": ["999; color: red"],
            "corner_top_left_opacity": ["2"],
            "repeat_gapX": ["10"],
            "repeat_rotate": ["not-a-number"],
        }
    )
    corner = values["corners"]["top-left"]
    assert corner["color"] == "#16140f"
    assert corner["fontSize"] == 30
    assert corner["opacity"] == 0.6
    assert values["repeating"]["gapX"] == 320
    assert values["repeating"]["rotate"] == -24


def test_preview_tiles_cover_the_densest_setting() -> None:
    # The preview cannot add tiles from JavaScript, so the server-rendered count
    # must cover the smallest allowed grid spacing.
    assert math.ceil(1920 / 120) * math.ceil(1080 / 80) <= PREVIEW_TILES


def test_tile_count_covers_the_canvas() -> None:
    watermark = WatermarkConfig.model_validate(_watermark_payload())
    assert watermark.repeating is not None
    assert tile_count(watermark.repeating) == 49
    assert tile_count(None) == 0
    dense = watermark.repeating.model_copy(update={"gapX": 120, "gapY": 80})
    assert tile_count(dense) == 255  # ceil(1920/120)=16, ceil(1080/80)=14


# -- site database storage -------------------------------------------------


def test_save_watermark_writes_and_removes_the_row(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _create_watermark_table(settings)
    watermark = WatermarkConfig.model_validate(_watermark_payload())

    assert load(settings, SLUG) is None
    save(settings, SLUG, watermark)

    saved = load(settings, SLUG)
    assert saved is not None
    assert saved.repeating is not None
    assert saved.repeating.text == "内部资料，请勿外传"
    assert load_all(settings)[SLUG].corners[0].text == "作者：张三"

    save(settings, SLUG, None)
    assert load(settings, SLUG) is None
    assert load_all(settings) == {}


def test_watermark_is_not_written_into_the_course_source(tmp_path: Path) -> None:
    """The whole point of the database: the text never enters ``course.json``."""

    settings = _settings(tmp_path)
    _create_watermark_table(settings)
    course_dir = settings.courses_src_dir / SLUG
    shutil.copytree(FIXTURES / SLUG, course_dir)
    before = (course_dir / "course.json").read_text(encoding="utf-8")

    save(settings, SLUG, WatermarkConfig.model_validate(_watermark_payload()))

    after = (course_dir / "course.json").read_text(encoding="utf-8")
    assert after == before
    assert "watermark" not in json.loads(after)
    assert "作者：张三" not in after


def test_missing_table_means_no_watermark(tmp_path: Path) -> None:
    """A build on a fresh checkout must not fail because migrations have not run."""

    settings = _settings(tmp_path)
    assert load(settings, SLUG) is None
    assert load_all(settings) == {}

    # Nothing was created as a side effect of reading.
    created = create_db_engine(settings.database_url)
    try:
        from sqlalchemy import inspect

        assert "course_watermarks" not in inspect(created).get_table_names()
    finally:
        created.dispose()


def test_slug_traversal_is_rejected(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _create_watermark_table(settings)
    with pytest.raises(ValueError):
        save(settings, "../escape", None)


# -- build output ----------------------------------------------------------


def _build_with(payload: dict | None, root: Path) -> tuple[str, str, str]:
    """Build one course with a DB-side watermark and return ``(shell, composition, hash)``."""

    source = root / "courses" / SLUG
    shutil.copytree(FIXTURES / SLUG, source)
    watermark = WatermarkConfig.model_validate(payload) if payload is not None else None
    result = build_course(source, out_root=root / "dist", watermark=watermark)
    assert result.ok, [error.message for error in result.errors]
    bundle = root / "dist" / SLUG
    shell = (bundle / "index.html").read_text(encoding="utf-8")
    composition = (bundle / "composition" / "index.html").read_text(encoding="utf-8")
    return shell, composition, result.content_hash


def test_build_bakes_corner_and_repeating_watermarks_into_the_composition(
    tmp_path: Path,
) -> None:
    """Playback and MP4 export read the composition, so the layer must live there.

    The shell no longer renders a watermark: a shell-only layer would show up in
    the browser but be missing from the exported video.
    """

    shell, composition, _ = _build_with(_watermark_payload(), tmp_path / "marked")
    assert "data-course-watermark" in composition
    assert "course-watermark__corner course-watermark__corner--top-left" in composition
    assert "作者：张三" in composition
    assert "示例公司" in composition
    assert "内部资料，请勿外传" in composition
    assert composition.count('class="course-watermark__tile"') == 49
    assert "data-course-watermark" not in shell
    assert "course-watermark" not in shell


def test_build_omits_watermark_when_not_configured(tmp_path: Path) -> None:
    shell, composition, _ = _build_with(None, tmp_path / "plain")
    assert "data-course-watermark" not in composition
    assert "course-watermark" not in composition
    assert "data-course-watermark" not in shell


def test_disabled_watermark_is_not_rendered_or_serialized(tmp_path: Path) -> None:
    payload = _watermark_payload()
    payload["enabled"] = False
    _, composition, _ = _build_with(payload, tmp_path / "disabled")
    assert "data-course-watermark" not in composition
    built = json.loads(
        (tmp_path / "disabled" / "dist" / SLUG / "course.json").read_text(
            encoding="utf-8"
        )
    )
    # Not rendered and not part of the built manifest: the config stays in the
    # database, not in course content.
    assert "watermark" not in built


def test_build_changes_content_hash_when_watermark_changes(tmp_path: Path) -> None:
    _shell, _composition, plain_hash = _build_with(None, tmp_path / "plain")
    _shell, _composition, marked_hash = _build_with(_watermark_payload(), tmp_path / "marked")
    assert plain_hash != marked_hash


def test_watermark_text_is_html_escaped(tmp_path: Path) -> None:
    payload = {
        "enabled": True,
        "corners": [
            {
                "position": "top-left",
                "text": "<b>作者</b>",
                "fontSize": 30,
                "color": "#16140f",
                "opacity": 0.6,
            }
        ],
    }
    _, composition, _ = _build_with(payload, tmp_path / "escaped")
    assert "&lt;b&gt;作者&lt;/b&gt;" in composition
    assert "<b>作者</b>" not in composition
    match = re.search(
        r'<span[^>]*course-watermark__corner--top-left[^>]*>(.*?)</span>', composition, re.S
    )
    assert match, "corner watermark span not found"
    assert "&lt;b&gt;作者&lt;/b&gt;" in match.group(1)
    assert "<b>" not in match.group(1)


def test_inject_watermark_is_idempotent(tmp_path: Path) -> None:
    """Builds inject into a fresh copy; a second call must not double the layer."""

    entry = tmp_path / "index.html"
    entry.write_text("<!doctype html><html><body><p>hi</p></body></html>", encoding="utf-8")
    watermark = WatermarkConfig.model_validate(_watermark_payload())
    assert inject_watermark(entry, watermark) is True
    assert inject_watermark(entry, watermark) is False
    document = entry.read_text(encoding="utf-8")
    assert document.count("data-course-watermark") == 1
    assert document.count('id="course-watermark-style"') == 1
    assert document.index("<p>hi</p>") < document.index("data-course-watermark")


def test_inject_watermark_appends_without_a_body_tag(tmp_path: Path) -> None:
    entry = tmp_path / "fragment.html"
    entry.write_text("<!-- no body wrapper -->", encoding="utf-8")
    watermark = WatermarkConfig.model_validate(
        {
            "enabled": True,
            "corners": [
                {
                    "position": "bottom-right",
                    "text": "署名",
                    "fontSize": 24,
                    "color": "#16140f",
                    "opacity": 0.5,
                }
            ],
        }
    )
    assert inject_watermark(entry, watermark) is True
    document = entry.read_text(encoding="utf-8")
    assert document.startswith("<!-- no body wrapper -->")
    assert "course-watermark__corner--bottom-right" in document


def test_course_json_rejects_the_watermark_field(tmp_path: Path) -> None:
    """Watermark is no longer course content: a stray key must fail the build."""

    source = tmp_path / "courses" / SLUG
    shutil.copytree(FIXTURES / SLUG, source)
    manifest_path = source / "course.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["watermark"] = _watermark_payload()
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    result = build_course(source, out_root=tmp_path / "dist")
    assert not result.ok
    assert any(error.code == "manifest_invalid" for error in result.errors)


def test_build_manifest_does_not_serialize_the_watermark(tmp_path: Path) -> None:
    _build_with(_watermark_payload(), tmp_path / "marked")
    built = json.loads(
        (tmp_path / "marked" / "dist" / SLUG / "course.json").read_text(
            encoding="utf-8"
        )
    )
    assert "watermark" not in built
