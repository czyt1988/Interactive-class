from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from sqlalchemy import select

from app.catalog.importing import (
    ImportResult,
    discover_course_sources,
    import_course,
    inspect_course,
    list_imports,
    record_import,
)
from app.db import Base, create_db_engine, create_session_factory
from app.models import CourseImport

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "courses"
SLUG = "valid-two-screen"
RUNTIME_DIR = ROOT / "runtime"


@dataclass
class Workspace:
    root: Path
    inbox: Path
    source: Path
    courses_root: Path
    dist_root: Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rewrite_manifest(source_dir: Path, **updates: object) -> None:
    path = source_dir / "course.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update(updates)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _import(workspace: Workspace, **overrides: object) -> ImportResult:
    options: dict[str, object] = {
        "courses_root": workspace.courses_root,
        "dist_root": workspace.dist_root,
        "runtime_dir": RUNTIME_DIR,
    }
    options.update(overrides)
    return import_course(workspace.source, **options)  # type: ignore[arg-type]


def _staging_leftovers(courses_root: Path) -> list[Path]:
    return [path for path in courses_root.iterdir() if path.name.startswith(".import-")]


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    inbox = tmp_path / "inbox"
    # The folder name intentionally differs from the manifest slug: import must
    # land under courses/<slug> and not care what the folder is called.
    source = inbox / "incoming-folder"
    shutil.copytree(FIXTURES / SLUG, source)
    courses_root = tmp_path / "courses"
    courses_root.mkdir()
    return Workspace(
        root=tmp_path,
        inbox=inbox,
        source=source,
        courses_root=courses_root,
        dist_root=tmp_path / "dist" / "courses",
    )


def test_discover_skips_hidden_and_underscore_dirs(workspace: Workspace) -> None:
    (workspace.inbox / "_template").mkdir()
    (workspace.inbox / "_template" / "course.json").write_text("{}", encoding="utf-8")
    (workspace.inbox / ".hidden").mkdir()
    (workspace.inbox / ".hidden" / "course.json").write_text("{}", encoding="utf-8")
    (workspace.inbox / "not-a-course").mkdir()
    (workspace.inbox / "notes.txt").write_text("hi", encoding="utf-8")

    found = discover_course_sources(workspace.inbox)
    assert [path.name for path in found] == ["incoming-folder"]
    # A course folder passed directly is discovered as itself.
    assert discover_course_sources(workspace.source) == [workspace.source.resolve()]
    assert discover_course_sources(workspace.inbox / "missing") == []


def test_inspect_ready_course(workspace: Workspace) -> None:
    candidate = inspect_course(workspace.source, courses_root=workspace.courses_root)

    assert candidate.status == "ready"
    assert candidate.slug == SLUG
    assert candidate.title == "两屏测试课"
    assert candidate.screens == 2
    assert candidate.duration == 4.0
    assert candidate.errors == []
    assert candidate.path == workspace.source.resolve()


def test_inspect_reports_scene_errors_with_screen_id(workspace: Workspace) -> None:
    (workspace.source / "composition" / "compositions" / "01-hook.html").unlink()

    candidate = inspect_course(workspace.source, courses_root=workspace.courses_root)

    assert candidate.status == "invalid"
    codes = {error.code for error in candidate.errors}
    assert "scene_missing" in codes
    error = next(error for error in candidate.errors if error.code == "scene_missing")
    assert error.slug == SLUG
    assert error.screen_id == "hook"
    assert error.field == "data-composition-src"
    assert error.file is not None and error.file.endswith("01-hook.html")


def test_inspect_survives_broken_manifest(workspace: Workspace) -> None:
    (workspace.source / "course.json").write_text("{not json", encoding="utf-8")

    candidate = inspect_course(workspace.source, courses_root=workspace.courses_root)

    assert candidate.status == "invalid"
    assert candidate.slug == "incoming-folder"  # falls back to the folder name
    assert {error.code for error in candidate.errors} == {"manifest_invalid"}


def test_dry_run_validates_without_writing(workspace: Workspace) -> None:
    before = _sha256(workspace.source / "course.json")

    result = _import(workspace, dry_run=True)

    assert result.ok and not result.copied and not result.built
    assert not result.was_existing
    assert result.screens == 2
    assert result.duration == 4.0
    assert result.source_hash == before
    assert result.content_hash == ""
    assert not (workspace.courses_root / SLUG).exists()
    assert not (workspace.root / "dist").exists()
    assert _staging_leftovers(workspace.courses_root) == []


def test_import_copies_builds_and_reports_hashes(workspace: Workspace) -> None:
    result = _import(workspace)

    assert result.ok and result.copied and result.built
    assert not result.was_existing
    assert result.slug == SLUG
    assert result.title == "两屏测试课"
    assert result.screens == 2
    assert result.duration == 4.0
    assert result.output_dir == workspace.dist_root / SLUG
    assert result.source_hash == _sha256(workspace.source / "course.json")
    assert len(result.content_hash) == 64

    target = workspace.courses_root / SLUG
    assert (target / "course.json").is_file()
    assert (target / "composition" / "index.html").is_file()
    assert (workspace.dist_root / SLUG / "index.html").is_file()
    assert (workspace.dist_root / SLUG / "runtime" / "course-deck.js").is_file()

    manifest = json.loads((workspace.dist_root / SLUG / "course.json").read_text(encoding="utf-8"))
    assert manifest["slug"] == SLUG
    assert manifest["stats"]["screenCount"] == 2
    assert [screen["start"] for screen in manifest["screens"]] == [0, 2]
    assert manifest["build"]["contentHash"] == result.content_hash

    assert _staging_leftovers(workspace.courses_root) == []
    assert not any(path.name.startswith(".build-") for path in workspace.dist_root.iterdir())


def test_import_skips_authoring_and_video_files(workspace: Workspace) -> None:
    source = workspace.source
    (source / ".git").mkdir()
    (source / ".git" / "config").write_text("x", encoding="utf-8")
    (source / "renders").mkdir()
    (source / "renders" / "clip.mp4").write_text("x", encoding="utf-8")
    (source / "notes.log").write_text("x", encoding="utf-8")
    (source / ".DS_Store").write_text("x", encoding="utf-8")
    composition = source / "composition"
    (composition / "node_modules").mkdir()
    (composition / "node_modules" / "x.js").write_text("//", encoding="utf-8")
    (composition / "preview.webm").write_text("x", encoding="utf-8")
    audio_dir = composition / "assets" / "audio"
    audio_dir.mkdir()
    (audio_dir / "voice.ogg").write_bytes(b"OggS")

    result = _import(workspace)

    assert result.ok, result.errors
    target = workspace.courses_root / SLUG
    assert not (target / ".git").exists()
    assert not (target / "renders").exists()
    assert not (target / "notes.log").exists()
    assert not (target / ".DS_Store").exists()
    assert not (target / "composition" / "node_modules").exists()
    assert not (target / "composition" / "preview.webm").exists()
    # Narration audio is part of the course and must be copied.
    assert (target / "composition" / "assets" / "audio" / "voice.ogg").is_file()


@pytest.mark.parametrize("reserved", ["your-course-slug", "_template", "template", "course-template"])
def test_reserved_slug_is_rejected(workspace: Workspace, reserved: str) -> None:
    _rewrite_manifest(workspace.source, slug=reserved)

    candidate = inspect_course(workspace.source, courses_root=workspace.courses_root)
    result = _import(workspace)

    assert candidate.status == "invalid"
    assert result.ok is False
    codes = {error.code for error in result.errors}
    assert "slug_reserved" in codes
    reserved_error = next(error for error in result.errors if error.code == "slug_reserved")
    assert reserved_error.field == "slug"
    assert "slug" in reserved_error.message
    assert "小写连字符" in reserved_error.message
    assert not (workspace.courses_root / SLUG).exists()
    assert _staging_leftovers(workspace.courses_root) == []


def test_existing_target_is_rejected_without_overwrite(workspace: Workspace) -> None:
    first = _import(workspace)
    assert first.ok
    manifest_before = (workspace.courses_root / SLUG / "course.json").read_bytes()

    second = _import(workspace)

    assert second.ok is False
    assert second.was_existing is True
    assert {error.code for error in second.errors} == {"course_exists"}
    assert "--overwrite" in second.errors[0].message
    assert (workspace.courses_root / SLUG / "course.json").read_bytes() == manifest_before


def test_overwrite_replaces_the_existing_course(workspace: Workspace) -> None:
    assert _import(workspace).ok
    stale = workspace.courses_root / SLUG / "stale.txt"
    stale.write_text("old", encoding="utf-8")
    _rewrite_manifest(workspace.source, title="覆盖后的课程")

    result = _import(workspace, overwrite=True)

    assert result.ok and result.copied and result.built
    assert result.was_existing is True
    assert not stale.exists()
    manifest = json.loads(
        (workspace.courses_root / SLUG / "course.json").read_text(encoding="utf-8")
    )
    assert manifest["title"] == "覆盖后的课程"
    dist_manifest = json.loads(
        (workspace.dist_root / SLUG / "course.json").read_text(encoding="utf-8")
    )
    assert dist_manifest["title"] == "覆盖后的课程"
    assert _staging_leftovers(workspace.courses_root) == []


def test_in_place_rebuild(workspace: Workspace) -> None:
    assert _import(workspace).ok
    target = workspace.courses_root / SLUG

    result = import_course(
        target,
        courses_root=workspace.courses_root,
        dist_root=workspace.dist_root,
        runtime_dir=RUNTIME_DIR,
    )

    assert result.ok and result.built
    assert result.copied is False
    assert result.was_existing is True
    assert result.errors == []
    assert (workspace.dist_root / SLUG / "index.html").is_file()


def test_invalid_course_leaves_no_trace(workspace: Workspace) -> None:
    (workspace.source / "composition" / "compositions" / "01-hook.html").unlink()

    result = _import(workspace)

    assert result.ok is False
    codes = {error.code for error in result.errors}
    assert "scene_missing" in codes
    error = next(error for error in result.errors if error.code == "scene_missing")
    # Validation happens on the source folder before anything is copied, so the
    # error points at the author's file, never at a staging copy.
    assert error.file is not None
    assert str(workspace.source.resolve()) in error.file
    assert ".import-" not in error.file
    assert not (workspace.courses_root / SLUG).exists()
    assert not (workspace.dist_root / SLUG).exists()
    assert _staging_leftovers(workspace.courses_root) == []


def test_no_build_copies_the_folder_only(workspace: Workspace) -> None:
    result = _import(workspace, build=False)

    assert result.ok and result.copied
    assert result.built is False
    assert (workspace.courses_root / SLUG / "course.json").is_file()
    assert not (workspace.dist_root / SLUG).exists()
    assert any("未构建" in warning for warning in result.warnings)


def test_no_build_overwrite_removes_the_stale_bundle(workspace: Workspace) -> None:
    assert _import(workspace).ok
    assert (workspace.dist_root / SLUG / "index.html").is_file()
    _rewrite_manifest(workspace.source, title="更新后的课程")

    result = _import(workspace, build=False, overwrite=True)

    assert result.ok and result.copied
    assert result.built is False
    assert result.was_existing is True
    target_manifest = json.loads(
        (workspace.courses_root / SLUG / "course.json").read_text(encoding="utf-8")
    )
    assert target_manifest["title"] == "更新后的课程"
    # Without a build the previous bundle no longer matches the files, so it is
    # removed instead of letting the catalog serve stale content.
    assert not (workspace.dist_root / SLUG).exists()
    assert any("旧的课程包已移除" in warning for warning in result.warnings)


def test_demo_course_slug_is_allowed(workspace: Workspace) -> None:
    # ``demo-course`` is a documentation example, not a template placeholder.
    _rewrite_manifest(workspace.source, slug="demo-course")

    result = _import(workspace)

    assert result.ok and result.built, result.errors
    assert (workspace.courses_root / "demo-course" / "course.json").is_file()
    assert (workspace.dist_root / "demo-course" / "index.html").is_file()


def test_draft_skipped_build_is_a_warning(workspace: Workspace) -> None:
    _rewrite_manifest(workspace.source, status="draft")

    result = _import(workspace, include_drafts=False)

    assert result.ok and result.copied
    assert result.built is False
    assert any("published" in warning for warning in result.warnings)
    assert (workspace.courses_root / SLUG / "course.json").is_file()
    assert not (workspace.dist_root / SLUG).exists()

    rebuilt = _import(workspace, include_drafts=True, overwrite=True)
    assert rebuilt.ok and rebuilt.built
    assert (workspace.dist_root / SLUG / "index.html").is_file()


def test_record_import_upserts_by_slug(workspace: Workspace) -> None:
    result = _import(workspace)
    assert result.ok

    engine = create_db_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    try:
        with factory() as session:
            record_import(session, result)
            session.commit()

        with factory() as session:
            rows = list(session.scalars(select(CourseImport)))
        assert len(rows) == 1
        row = rows[0]
        assert row.slug == SLUG
        assert row.title == result.title
        assert row.source_path == str(result.source)
        assert row.source_hash == result.source_hash
        assert row.content_hash == result.content_hash
        assert row.screens == 2
        assert row.duration_seconds == 4.0
        assert row.imported_at is not None
        assert row.updated_at is not None

        updated = replace(
            result,
            title="覆盖测试课程",
            screens=3,
            duration=9.0,
            content_hash="a" * 64,
            source_hash="b" * 64,
        )
        with factory() as session:
            record_import(session, updated)
            session.commit()

        with factory() as session:
            rows = list_imports(session)
        assert len(rows) == 1
        assert rows[0].title == "覆盖测试课程"
        assert rows[0].screens == 3
        assert rows[0].duration_seconds == 9.0
        assert rows[0].source_hash == "b" * 64

        with factory() as session:
            record_import(session, replace(updated, slug="second-course", title="第二门课"))
            session.commit()
            latest = list_imports(session, limit=1)
            every = list_imports(session)
        assert [row.slug for row in latest] == ["second-course"]
        assert len(every) == 2
    finally:
        engine.dispose()
