from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from app.catalog.models import CatalogError
from app.catalog.resolver import CourseResolutionError, resolve_course

FIXTURE = Path(__file__).parent / "fixtures" / "courses" / "valid-two-screen"


def make_course(tmp_path: Path) -> Path:
    target = tmp_path / "valid-two-screen"
    shutil.copytree(FIXTURE, target)
    return target


def load_manifest(course_dir: Path) -> dict:
    return json.loads((course_dir / "course.json").read_text(encoding="utf-8"))


def save_manifest(course_dir: Path, data: dict) -> None:
    (course_dir / "course.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def edit(path: Path, old: str, new: str, *, count: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{old!r} not found in {path}"
    path.write_text(text.replace(old, new, count), encoding="utf-8")


def set_host_attr(path: Path, screen_id: str, attribute: str, value: str) -> None:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(rf'(id="s-{screen_id}".*?{attribute}=")[^"]*(")', re.DOTALL)
    updated, count = pattern.subn(rf"\g<1>{value}\g<2>", text, count=1)
    assert count == 1, f"host {screen_id!r} attribute {attribute!r} not found"
    path.write_text(updated, encoding="utf-8")


def assert_error(exc: CourseResolutionError, code: str, *, screen_id: str | None = None) -> CatalogError:
    matches = [error for error in exc.errors if error.code == code]
    assert matches, f"expected {code}, got {[error.code for error in exc.errors]}"
    error = matches[0]
    if screen_id is not None:
        assert error.screen_id == screen_id
    return error


def test_valid_course_resolves() -> None:
    course = resolve_course(FIXTURE)
    assert course.slug == "valid-two-screen"
    assert course.stats.screenCount == 2
    assert course.stats.durationSeconds == 4
    assert course.stats.estimatedMinutes == 1
    assert course.composition.duration == 4
    assert [screen.id for screen in course.screens] == ["hook", "split"]
    assert [screen.start for screen in course.screens] == [0, 2]
    assert [screen.duration for screen in course.screens] == [2, 2]
    assert [screen.index for screen in course.screens] == [0, 1]


def test_unknown_field_rejected(tmp_path: Path) -> None:
    course_dir = make_course(tmp_path)
    data = load_manifest(course_dir)
    data["autoAdvence"] = True
    save_manifest(course_dir, data)
    with pytest.raises(CourseResolutionError) as caught:
        resolve_course(course_dir)
    error = assert_error(caught.value, "manifest_invalid")
    assert error.field == "autoAdvence"


def test_slug_mismatch(tmp_path: Path) -> None:
    course_dir = make_course(tmp_path)
    data = load_manifest(course_dir)
    data["slug"] = "other-course"
    save_manifest(course_dir, data)
    with pytest.raises(CourseResolutionError) as caught:
        resolve_course(course_dir)
    assert_error(caught.value, "slug_mismatch")


def test_composition_missing(tmp_path: Path) -> None:
    course_dir = make_course(tmp_path)
    (course_dir / "composition" / "index.html").unlink()
    with pytest.raises(CourseResolutionError) as caught:
        resolve_course(course_dir)
    assert_error(caught.value, "composition_missing")


def test_duplicate_screen_meta(tmp_path: Path) -> None:
    course_dir = make_course(tmp_path)
    data = load_manifest(course_dir)
    data["screens"][1]["id"] = "hook"
    save_manifest(course_dir, data)
    with pytest.raises(CourseResolutionError) as caught:
        resolve_course(course_dir)
    assert_error(caught.value, "manifest_invalid")


def test_duplicate_screen_host(tmp_path: Path) -> None:
    course_dir = make_course(tmp_path)
    index = course_dir / "composition" / "index.html"
    set_host_attr(index, "split", "data-screen-id", "hook")
    with pytest.raises(CourseResolutionError) as caught:
        resolve_course(course_dir)
    assert_error(caught.value, "screen_id_duplicate", screen_id="hook")


def test_invalid_screen_id(tmp_path: Path) -> None:
    course_dir = make_course(tmp_path)
    data = load_manifest(course_dir)
    data["screens"][0]["id"] = "Bad ID"
    save_manifest(course_dir, data)
    with pytest.raises(CourseResolutionError) as caught:
        resolve_course(course_dir)
    assert_error(caught.value, "manifest_invalid")


def test_invalid_host_start(tmp_path: Path) -> None:
    course_dir = make_course(tmp_path)
    set_host_attr(course_dir / "composition" / "index.html", "hook", "data-start", "soon")
    with pytest.raises(CourseResolutionError) as caught:
        resolve_course(course_dir)
    assert_error(caught.value, "host_start_invalid", screen_id="hook")


def test_invalid_host_duration(tmp_path: Path) -> None:
    course_dir = make_course(tmp_path)
    set_host_attr(course_dir / "composition" / "index.html", "hook", "data-duration", "0")
    with pytest.raises(CourseResolutionError) as caught:
        resolve_course(course_dir)
    assert_error(caught.value, "host_duration_invalid", screen_id="hook")


def test_host_order_invalid(tmp_path: Path) -> None:
    course_dir = make_course(tmp_path)
    index = course_dir / "composition" / "index.html"
    set_host_attr(index, "hook", "data-start", "2")
    set_host_attr(index, "split", "data-start", "0")
    with pytest.raises(CourseResolutionError) as caught:
        resolve_course(course_dir)
    assert_error(caught.value, "host_order_invalid")


def test_host_overlap(tmp_path: Path) -> None:
    course_dir = make_course(tmp_path)
    set_host_attr(course_dir / "composition" / "index.html", "split", "data-start", "1")
    with pytest.raises(CourseResolutionError) as caught:
        resolve_course(course_dir)
    assert_error(caught.value, "host_overlap", screen_id="split")


def test_root_duration_short(tmp_path: Path) -> None:
    course_dir = make_course(tmp_path)
    edit(course_dir / "composition" / "index.html", 'data-duration="4"', 'data-duration="3"')
    with pytest.raises(CourseResolutionError) as caught:
        resolve_course(course_dir)
    assert_error(caught.value, "root_duration_short")


def test_root_duration_missing(tmp_path: Path) -> None:
    course_dir = make_course(tmp_path)
    edit(course_dir / "composition" / "index.html", ' data-duration="4"', "")
    with pytest.raises(CourseResolutionError) as caught:
        resolve_course(course_dir)
    assert_error(caught.value, "root_duration_missing")


def test_scene_missing(tmp_path: Path) -> None:
    course_dir = make_course(tmp_path)
    (course_dir / "composition" / "compositions" / "02-split.html").unlink()
    with pytest.raises(CourseResolutionError) as caught:
        resolve_course(course_dir)
    assert_error(caught.value, "scene_missing", screen_id="split")


def test_scene_id_mismatch(tmp_path: Path) -> None:
    course_dir = make_course(tmp_path)
    edit(
        course_dir / "composition" / "compositions" / "01-hook.html",
        'data-composition-id="s-hook"',
        'data-composition-id="s-other"',
    )
    with pytest.raises(CourseResolutionError) as caught:
        resolve_course(course_dir)
    assert_error(caught.value, "scene_id_mismatch", screen_id="hook")


def test_timeline_missing(tmp_path: Path) -> None:
    course_dir = make_course(tmp_path)
    edit(
        course_dir / "composition" / "compositions" / "01-hook.html",
        'window.__timelines["s-hook"]',
        'window.__timelines["s-wrong"]',
    )
    with pytest.raises(CourseResolutionError) as caught:
        resolve_course(course_dir)
    assert_error(caught.value, "timeline_missing", screen_id="hook")


def test_screen_meta_orphan(tmp_path: Path) -> None:
    course_dir = make_course(tmp_path)
    index = course_dir / "composition" / "index.html"
    edit(index, 'id="s-split"', 'id="s-extra"')
    edit(index, 'data-composition-id="s-split"', 'data-composition-id="s-extra"')
    set_host_attr(index, "extra", "data-screen-id", "extra")
    (course_dir / "composition" / "compositions" / "02-split.html").rename(
        course_dir / "composition" / "compositions" / "02-extra.html"
    )
    edit(
        course_dir / "composition" / "index.html",
        "compositions/02-split.html",
        "compositions/02-extra.html",
    )
    with pytest.raises(CourseResolutionError) as caught:
        resolve_course(course_dir)
    codes = {error.code for error in caught.value.errors}
    assert "screen_meta_orphan" in codes
    assert "screen_host_orphan" in codes


def test_duplicate_track_index(tmp_path: Path) -> None:
    course_dir = make_course(tmp_path)
    set_host_attr(course_dir / "composition" / "index.html", "split", "data-track-index", "0")
    with pytest.raises(CourseResolutionError) as caught:
        resolve_course(course_dir)
    assert_error(caught.value, "host_track_duplicate", screen_id="split")
