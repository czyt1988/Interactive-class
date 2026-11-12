"""Tests for the per-course watermark contract, form parsing and build output."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.catalog.models import WatermarkConfig
from app.catalog.watermark import (
    form_values,
    form_values_from_request,
    parse_form,
    read_manifest,
    save_watermark,
    tile_count,
    watermark_from_manifest,
    write_manifest,
)
from app.config import Settings
from scripts.build_courses import build_course

FIXTURES = Path(__file__).parent / "fixtures" / "courses"
SLUG = "valid-two-screen"


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
    assert values["corners"]["top-left"]["fontSize"] == "44"
    assert values["corners"]["bottom-left"]["text"] == ""


def test_tile_count_covers_the_canvas() -> None:
    watermark = WatermarkConfig.model_validate(_watermark_payload())
    assert watermark.repeating is not None
    assert tile_count(watermark.repeating) == 49
    assert tile_count(None) == 0
    dense = watermark.repeating.model_copy(update={"gapX": 120, "gapY": 80})
    assert tile_count(dense) == 255  # ceil(1920/120)=16, ceil(1080/80)=14


# -- source manifest -------------------------------------------------------


def test_save_watermark_writes_and_removes_the_key(tmp_path: Path) -> None:
    settings = Settings(
        env="dev",
        courses_src_dir=tmp_path / "courses",
        courses_dist_dir=tmp_path / "dist" / "courses",
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
    )
    course_dir = settings.courses_src_dir / SLUG
    shutil.copytree(FIXTURES / SLUG, course_dir)
    original = read_manifest(course_dir / "course.json")
    original["title"] = "保留我"
    write_manifest(course_dir / "course.json", original)

    watermark = WatermarkConfig.model_validate(_watermark_payload())
    save_watermark(settings, SLUG, watermark)
    saved = read_manifest(course_dir / "course.json")
    assert saved["title"] == "保留我"
    assert saved["watermark"]["repeating"]["text"] == "内部资料，请勿外传"
    assert watermark_from_manifest(saved) is not None

    save_watermark(settings, SLUG, None)
    assert "watermark" not in read_manifest(course_dir / "course.json")


def test_manifest_path_rejects_traversal(tmp_path: Path) -> None:
    settings = Settings(
        env="dev",
        courses_src_dir=tmp_path / "courses",
        courses_dist_dir=tmp_path / "dist" / "courses",
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
    )
    with pytest.raises(ValueError):
        save_watermark(settings, "../escape", None)


# -- build output ----------------------------------------------------------


def _build_with(payload: dict | None, root: Path) -> tuple[str, str]:
    source = root / "courses" / SLUG
    shutil.copytree(FIXTURES / SLUG, source)
    manifest = read_manifest(source / "course.json")
    if payload is not None:
        manifest["watermark"] = payload
    write_manifest(source / "course.json", manifest)
    result = build_course(source, out_root=root / "dist")
    assert result.ok, [error.message for error in result.errors]
    html = (root / "dist" / SLUG / "index.html").read_text(encoding="utf-8")
    return html, result.content_hash


def test_build_renders_corner_and_repeating_watermarks(tmp_path: Path) -> None:
    html, _ = _build_with(_watermark_payload(), tmp_path / "marked")
    assert 'data-watermark' in html
    assert "watermark__corner watermark__corner--top-left" in html
    assert "作者：张三" in html
    assert "示例公司" in html
    assert "内部资料，请勿外传" in html
    assert html.count("watermark__tile") == 49


def test_build_omits_watermark_when_not_configured(tmp_path: Path) -> None:
    html, _ = _build_with(None, tmp_path / "plain")
    assert "data-watermark" not in html
    assert "watermark__corner" not in html


def test_disabled_watermark_is_kept_in_manifest_but_not_rendered(tmp_path: Path) -> None:
    payload = _watermark_payload()
    payload["enabled"] = False
    html, _ = _build_with(payload, tmp_path / "disabled")
    assert "data-watermark" not in html
    built = json.loads(
        (tmp_path / "disabled" / "dist" / SLUG / "course.json").read_text(
            encoding="utf-8"
        )
    )
    assert built["watermark"]["enabled"] is False
    assert built["watermark"]["corners"][0]["text"] == "作者：张三"


def test_build_changes_content_hash_when_watermark_changes(tmp_path: Path) -> None:
    _, plain_hash = _build_with(None, tmp_path / "plain")
    _, marked_hash = _build_with(_watermark_payload(), tmp_path / "marked")
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
    html, _ = _build_with(payload, tmp_path / "escaped")
    assert "&lt;b&gt;作者&lt;/b&gt;" in html
    assert "<b>作者</b>" not in html


def test_invalid_watermark_fails_the_build(tmp_path: Path) -> None:
    source = tmp_path / "courses" / SLUG
    shutil.copytree(FIXTURES / SLUG, source)
    manifest = read_manifest(source / "course.json")
    manifest["watermark"] = {"corners": [{"position": "middle", "text": "x"}]}
    write_manifest(source / "course.json", manifest)
    result = build_course(source, out_root=tmp_path / "dist")
    assert not result.ok
    assert any(error.code == "manifest_invalid" for error in result.errors)


def test_manifest_json_contains_watermark_for_the_deck(tmp_path: Path) -> None:
    build_course_path = tmp_path / "courses" / SLUG
    shutil.copytree(FIXTURES / SLUG, build_course_path)
    manifest = read_manifest(build_course_path / "course.json")
    manifest["watermark"] = _watermark_payload()
    write_manifest(build_course_path / "course.json", manifest)
    assert build_course(build_course_path, out_root=tmp_path / "dist").ok
    built = json.loads(
        (tmp_path / "dist" / SLUG / "course.json").read_text(encoding="utf-8")
    )
    assert built["watermark"]["repeating"]["text"] == "内部资料，请勿外传"
