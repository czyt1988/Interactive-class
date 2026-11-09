from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from app.catalog.resolver import resolve_course
from scripts.build_courses import build_course
from scripts.new_course import main as new_course_main

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "course-template"
SLUG = "scaffold-smoke-course"


@pytest.fixture(autouse=True)
def require_course_template() -> None:
    """The real template package is a deliverable; skip-free failure is on purpose."""

    assert TEMPLATE.is_dir(), "course-template/ 未就绪：先完成模板抽取，再跑脚手架测试"
    for name in ("course.json", "STORYBOARD.md", "composition"):
        assert (TEMPLATE / name).exists(), f"course-template/ 缺少 {name}"


def _create(
    tmp_path: Path, *, slug: str = SLUG, extra: list[str] | None = None
) -> tuple[int, Path, Path]:
    courses_root = tmp_path / "courses"
    argv = [
        slug,
        "--title",
        "脚手架测试课",
        "--source-dir",
        str(courses_root),
        "--template",
        str(TEMPLATE),
    ]
    argv.extend(extra or [])
    code = new_course_main(argv)
    return code, courses_root, courses_root / slug


def test_scaffold_resolves_and_keeps_the_manifest_valid(tmp_path: Path) -> None:
    code, courses_root, target = _create(tmp_path)

    assert code == 0
    assert sorted(path.name for path in target.iterdir()) == [
        "STORYBOARD.md",
        "composition",
        "course.json",
    ]
    manifest = json.loads((target / "course.json").read_text(encoding="utf-8"))
    assert manifest["slug"] == SLUG
    assert manifest["title"] == "脚手架测试课"
    assert "subtitle" not in manifest
    assert manifest["status"] == "draft"
    assert manifest["credits"]["updatedAt"] == date.today().isoformat()
    # The authoring docs belong to the template package, not to the course folder.
    for name in ("AGENTS.md", "README.md", "COURSE-CONTRACT.md", "STYLE.md"):
        assert not (target / name).exists(), name
        assert not (target / "composition" / name).exists(), name

    course = resolve_course(target)
    assert course.slug == SLUG
    assert [screen.id for screen in course.screens] == ["hello", "world"]
    assert course.stats.screenCount == 2


def test_scaffold_rewrites_package_name_and_published_status(tmp_path: Path) -> None:
    code, _courses_root, target = _create(tmp_path, extra=["--published"])

    assert code == 0
    manifest = json.loads((target / "course.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "published"
    package = json.loads((target / "composition" / "package.json").read_text(encoding="utf-8"))
    assert package["name"] == f"course-{SLUG}"

    built = build_course(target, out_root=tmp_path / "dist")
    assert built.ok, built.errors
    assert built.screens == 2
    assert (tmp_path / "dist" / SLUG / "index.html").is_file()


def test_scaffold_subtitle_is_written(tmp_path: Path) -> None:
    code, _courses_root, target = _create(tmp_path, extra=["--subtitle", "副标题一句"])

    assert code == 0
    manifest = json.loads((target / "course.json").read_text(encoding="utf-8"))
    assert manifest["subtitle"] == "副标题一句"


def test_scaffold_refuses_to_overwrite(tmp_path: Path) -> None:
    courses_root = tmp_path / "courses"
    existing = courses_root / SLUG
    existing.mkdir(parents=True)
    sentinel = existing / "sentinel.txt"
    sentinel.write_text("keep me", encoding="utf-8")

    code = new_course_main(
        [
            SLUG,
            "--title",
            "脚手架测试课",
            "--source-dir",
            str(courses_root),
            "--template",
            str(TEMPLATE),
        ]
    )

    assert code == 1
    assert sentinel.read_text(encoding="utf-8") == "keep me"
    assert not (existing / "course.json").exists()


@pytest.mark.parametrize(
    "bad_slug", ["Bad-Slug", "UPPER", "trailing-", "-leading", "double--dash", "空格 课程", ""]
)
def test_scaffold_rejects_invalid_slugs(tmp_path: Path, bad_slug: str) -> None:
    # ``--`` keeps argparse from reading dash-prefixed slugs as options.
    code = new_course_main(
        [
            "--title",
            "脚手架测试课",
            "--source-dir",
            str(tmp_path / "courses"),
            "--template",
            str(TEMPLATE),
            "--",
            bad_slug,
        ]
    )

    assert code == 1
    assert not (tmp_path / "courses" / bad_slug).exists()


def test_scaffold_rejects_invalid_title(tmp_path: Path) -> None:
    code, courses_root, target = _create(tmp_path, extra=["--title", "x"])

    assert code == 1
    assert not target.exists()


def test_scaffold_reports_a_missing_template(tmp_path: Path) -> None:
    code = new_course_main(
        [
            SLUG,
            "--title",
            "脚手架测试课",
            "--source-dir",
            str(tmp_path / "courses"),
            "--template",
            str(tmp_path / "missing-template"),
        ]
    )

    assert code == 1
    assert not (tmp_path / "courses").exists()
