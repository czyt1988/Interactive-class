"""Contract tests for the standalone ``course-template/`` package.

The template is handed to external authors and external AIs, so it has to stay a
valid course source: structure complete, no external assets, and buildable after
the placeholder slug is replaced.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from app.catalog.assets import scan_composition
from app.catalog.resolver import resolve_course
from scripts.build_courses import build_course

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "course-template"

REQUIRED_FILES = (
    "AGENTS.md",
    "README.md",
    "COURSE-CONTRACT.md",
    "STYLE.md",
    "course.json",
    "STORYBOARD.md",
    "composition/index.html",
    "composition/package.json",
    "composition/assets/course.css",
    "composition/assets/fonts/NotoSansSC-VF.woff2",
    "composition/assets/vendor/gsap.min.js",
    "composition/compositions/01-hello.html",
    "composition/compositions/02-world.html",
)

AUTHOR_DOC_MARKERS = {
    "AGENTS.md": ("course.json", "composition", "导入", "1920", "30fps", "slug", "自检"),
    "README.md": ("course-template", "导入", "course-inbox", "HyperFrames"),
    "COURSE-CONTRACT.md": ("course.json", "composition", "screens", "data-start", "错误码"),
    "STYLE.md": ("#f4efe6", "#16140f", "192px", "字号"),
}


def _read_manifest() -> dict[str, object]:
    return json.loads((TEMPLATE / "course.json").read_text(encoding="utf-8"))


def test_template_has_required_files() -> None:
    for relative in REQUIRED_FILES:
        assert (TEMPLATE / relative).is_file(), relative
    for relative in ("composition/assets/images", "composition/assets/audio"):
        assert (TEMPLATE / relative).is_dir(), relative


def test_legacy_template_directory_is_gone_and_sync_path_updated() -> None:
    assert not (ROOT / "courses" / "_template").exists()

    source = (ROOT / "scripts" / "sync_runtime.py").read_text(encoding="utf-8")
    assert 'TEMPLATE_ROOT = ROOT / "course-template"' in source
    assert 'TEMPLATE_ASSETS = TEMPLATE_ROOT / "composition" / "assets"' in source
    assert 'courses" / "_template' not in source


def test_scaffold_manifest_is_schema_shaped() -> None:
    manifest = _read_manifest()

    assert manifest["schemaVersion"] == 1
    assert manifest["slug"] == "your-course-slug"
    assert manifest["status"] == "draft"
    assert manifest["credits"]["author"] == "AI Learning"  # type: ignore[index]
    assert 40 <= len(str(manifest["summary"])) <= 160
    assert [screen["id"] for screen in manifest["screens"]] == ["hello", "world"]  # type: ignore[index]
    for screen in manifest["screens"]:  # type: ignore[union-attr]
        assert screen["title"] in screen["transcript"], screen["id"]
        assert "start" not in screen and "duration" not in screen


def test_composition_package_pins_authoring_versions() -> None:
    package = json.loads(
        (TEMPLATE / "composition" / "package.json").read_text(encoding="utf-8")
    )
    assert package["name"] == "course-template"
    for command in package["scripts"].values():
        assert "hyperframes@0.9.19" in command


def test_template_composition_has_no_asset_issues() -> None:
    issues = scan_composition(TEMPLATE / "composition")
    assert not issues, [(issue.code, issue.file, issue.value) for issue in issues]


def test_template_resolves_and_builds_after_slug_replace(tmp_path: Path) -> None:
    course_dir = tmp_path / "demo-course"
    shutil.copytree(TEMPLATE, course_dir)

    manifest_path = course_dir / "course.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["slug"] = "demo-course"
    manifest["status"] = "published"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    course = resolve_course(course_dir)
    assert course.slug == "demo-course"
    assert course.stats.screenCount == 2
    assert [screen.id for screen in course.screens] == ["hello", "world"]
    assert [screen.start for screen in course.screens] == [0, 12]

    out_root = tmp_path / "dist"
    result = build_course(course_dir, out_root=out_root)
    assert result.ok, [error.model_dump() for error in result.errors]

    bundle = out_root / "demo-course"
    for relative in ("index.html", "course.json", "composition/index.html"):
        assert (bundle / relative).is_file(), relative

    built = json.loads((bundle / "course.json").read_text(encoding="utf-8"))
    assert built["stats"]["screenCount"] == 2
    assert built["stats"]["durationSeconds"] == 26


@pytest.mark.parametrize(("name", "markers"), list(AUTHOR_DOC_MARKERS.items()))
def test_author_docs_contain_key_guidance(name: str, markers: tuple[str, ...]) -> None:
    text = (TEMPLATE / name).read_text(encoding="utf-8")
    missing = [marker for marker in markers if marker not in text]
    assert not missing, f"{name} 缺少关键指引：{missing}"
