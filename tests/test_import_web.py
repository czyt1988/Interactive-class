"""Tests for the dev-only /import page.

Everything runs against a temporary repository layout: inbox, courses, dist and
the SQLite file all live under ``tmp_path``, so a test never imports a course
into the real workspace. The import pipeline itself is not mocked; the fixture
course is small enough to validate, copy and build within a second or two.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.db import Base
from app.main import create_app
from app.models import CourseImport

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "courses"
SLUG = "valid-two-screen"
FIXTURE = FIXTURES / SLUG


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "env": "dev",
        "courses_src_dir": tmp_path / "courses",
        "courses_dist_dir": tmp_path / "dist" / "courses",
        "courses_inbox_dir": tmp_path / "course-inbox",
        "database_url": f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        "strict_catalog": False,
        "include_drafts": True,
        "verify_course_bundles": True,
        "course_import_enabled": True,
        "runtime_dir": ROOT / "runtime",
        "video_output_dir": tmp_path / "data" / "videos",
        "video_work_dir": tmp_path / "data" / "videos" / ".work",
    }
    values.update(overrides)
    return Settings(**values)


@contextmanager
def _site(
    tmp_path: Path, *, create_tables: bool = True, **overrides: Any
) -> Iterator[SimpleNamespace]:
    settings = _settings(tmp_path, **overrides)
    application = create_app(settings)
    if create_tables:
        Base.metadata.create_all(application.state.engine)
    with TestClient(application) as client:
        yield SimpleNamespace(client=client, app=application, settings=settings)


def _copy_course(folder: Path) -> Path:
    shutil.copytree(FIXTURE, folder)
    return folder


def _rewrite_manifest(folder: Path, **updates: object) -> None:
    path = folder / "course.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update(updates)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _post_import(
    client: TestClient,
    *,
    folder: str = "incoming-folder",
    action: str = "single",
    overwrite: bool = False,
    headers: dict[str, str] | None = None,
) -> Any:
    data = {"folder": folder, "action": action}
    if overwrite:
        data["overwrite"] = "1"
    return client.post(
        "/import", data=data, headers=headers, follow_redirects=False
    )


def _redirect_params(response: Any) -> dict[str, list[str]]:
    assert response.status_code == 303, response.text
    parsed = urlsplit(response.headers["location"])
    assert parsed.path == "/import"
    return parse_qs(parsed.query)


def _courses_root(tmp_path: Path) -> Path:
    return tmp_path / "courses"


def _dist_root(tmp_path: Path) -> Path:
    return tmp_path / "dist" / "courses"


# -- GET -------------------------------------------------------------------


def test_page_lists_ready_candidate_with_bulk_action(tmp_path: Path) -> None:
    _copy_course(tmp_path / "course-inbox" / "incoming-folder")

    with _site(tmp_path) as site:
        response = site.client.get("/import")

    assert response.status_code == 200
    text = response.text
    assert "两屏测试课" in text
    assert "incoming-folder/" in text
    assert "ready" in text
    assert "可导入" in text
    assert "2 屏" in text
    assert "导入全部可导入课程" in text
    assert 'name="action" value="all"' in text
    assert "/static/import.css" in text
    assert "no-store" in response.headers["cache-control"]


def test_page_without_inbox_renders_empty_state(tmp_path: Path) -> None:
    # The default inbox directory does not exist yet in this temp layout.
    with _site(tmp_path) as site:
        response = site.client.get("/import")

    assert response.status_code == 200
    assert "收件箱尚未创建" in response.text
    assert "course-template/" in response.text


def test_page_shows_recent_imports_after_an_import(tmp_path: Path) -> None:
    _copy_course(tmp_path / "course-inbox" / "incoming-folder")

    with _site(tmp_path) as site:
        _post_import(site.client)
        page = site.client.get("/import")

    assert page.status_code == 200
    text = page.text
    # The inbox folder is still there, but the course now exists in courses/.
    assert "exists" in text
    assert "已存在" in text
    assert "最近导入" in text
    assert SLUG in text
    assert "数据库未迁移" not in text


# -- single import ---------------------------------------------------------


def test_single_import_copies_builds_and_records_provenance(tmp_path: Path) -> None:
    _copy_course(tmp_path / "course-inbox" / "incoming-folder")

    with _site(tmp_path) as site:
        response = _post_import(
            site.client, headers={"Origin": "http://testserver"}
        )
        params = _redirect_params(response)
        assert params["imported"] == [SLUG]

        assert (_courses_root(tmp_path) / SLUG / "course.json").is_file()
        assert (
            _courses_root(tmp_path) / SLUG / "composition" / "index.html"
        ).is_file()
        assert (_dist_root(tmp_path) / SLUG / "index.html").is_file()

        with site.app.state.session_factory() as db:
            rows = list(db.scalars(select(CourseImport)))
        assert len(rows) == 1
        row = rows[0]
        assert row.slug == SLUG
        assert row.title == "两屏测试课"
        assert row.screens == 2
        assert row.duration_seconds == 4.0
        assert row.source_path.endswith("incoming-folder")
        assert row.imported_at is not None

        # The catalog cache was invalidated, so the API sees the new course.
        api = site.client.get("/api/courses")
        assert api.status_code == 200
        slugs = {course["slug"] for course in api.json()["courses"]}
        assert SLUG in slugs

        page = site.client.get("/import")
        assert "导入成功" not in page.text  # the flash only lives in the redirect
        assert "最近导入" in page.text


def test_second_import_without_overwrite_is_rejected(tmp_path: Path) -> None:
    _copy_course(tmp_path / "course-inbox" / "incoming-folder")

    with _site(tmp_path) as site:
        assert _redirect_params(_post_import(site.client))["imported"] == [SLUG]
        manifest = _courses_root(tmp_path) / SLUG / "course.json"
        before = manifest.read_bytes()

        response = _post_import(site.client)
        params = _redirect_params(response)
        assert "error" in params
        assert "已存在" in params["error"][0]
        assert manifest.read_bytes() == before

        with site.app.state.session_factory() as db:
            assert len(list(db.scalars(select(CourseImport)))) == 1


def test_overwrite_import_replaces_the_existing_course(tmp_path: Path) -> None:
    folder = _copy_course(tmp_path / "course-inbox" / "incoming-folder")

    with _site(tmp_path) as site:
        assert _redirect_params(_post_import(site.client))["imported"] == [SLUG]
        _rewrite_manifest(folder, title="覆盖后的课程")

        params = _redirect_params(_post_import(site.client, overwrite=True))
        assert params["imported"] == [SLUG]

        manifest = json.loads(
            (_courses_root(tmp_path) / SLUG / "course.json").read_text(
                encoding="utf-8"
            )
        )
        assert manifest["title"] == "覆盖后的课程"
        dist_manifest = json.loads(
            (_dist_root(tmp_path) / SLUG / "course.json").read_text(
                encoding="utf-8"
            )
        )
        assert dist_manifest["title"] == "覆盖后的课程"


def test_import_all_ready_candidates(tmp_path: Path) -> None:
    inbox = tmp_path / "course-inbox"
    _copy_course(inbox / "first-folder")
    second = _copy_course(inbox / "second-folder")
    _rewrite_manifest(second, slug="second-course", title="第二门测试课")

    with _site(tmp_path) as site:
        response = _post_import(site.client, action="all")
        params = _redirect_params(response)
        assert params["imported"] == ["批量导入 2 门"]

        for slug in (SLUG, "second-course"):
            assert (_courses_root(tmp_path) / slug / "course.json").is_file()
            assert (_dist_root(tmp_path) / slug / "index.html").is_file()

        with site.app.state.session_factory() as db:
            slugs = sorted(row.slug for row in db.scalars(select(CourseImport)))
        assert slugs == ["second-course", SLUG]

        api_slugs = {
            course["slug"]
            for course in site.client.get("/api/courses").json()["courses"]
        }
        assert {SLUG, "second-course"} <= api_slugs


# -- rejected requests -----------------------------------------------------


@pytest.mark.parametrize(
    "folder",
    ["", "..", "../../windows", "..\\windows", "sub/dir", "C:\\Windows"],
)
def test_path_escape_is_rejected(tmp_path: Path, folder: str) -> None:
    _copy_course(tmp_path / "course-inbox" / "incoming-folder")

    with _site(tmp_path) as site:
        params = _redirect_params(_post_import(site.client, folder=folder))

    assert params["error"][0]
    assert not _courses_root(tmp_path).exists()
    assert not _dist_root(tmp_path).exists()
    # The inbox copy is untouched: a rejected post never reads or moves files.
    assert (tmp_path / "course-inbox" / "incoming-folder" / "course.json").is_file()


def test_missing_inbox_folder_is_rejected(tmp_path: Path) -> None:
    _copy_course(tmp_path / "course-inbox" / "incoming-folder")

    with _site(tmp_path) as site:
        params = _redirect_params(_post_import(site.client, folder="not-there"))

    assert "没有" in params["error"][0]
    assert not _courses_root(tmp_path).exists()


def test_invalid_course_shows_errors_and_never_lands(tmp_path: Path) -> None:
    folder = _copy_course(tmp_path / "course-inbox" / "broken-course")
    (folder / "composition" / "compositions" / "01-hook.html").unlink()

    with _site(tmp_path) as site:
        page = site.client.get("/import")
        assert page.status_code == 200
        assert "invalid" in page.text
        assert "需修复" in page.text
        assert "scene_missing" in page.text
        assert "01-hook.html" in page.text
        assert "先修复" in page.text

        params = _redirect_params(
            _post_import(site.client, folder="broken-course")
        )

    assert params["error"][0]
    assert not (_courses_root(tmp_path) / SLUG).exists()
    assert not (_dist_root(tmp_path) / SLUG).exists()


def test_cross_origin_post_is_rejected(tmp_path: Path) -> None:
    _copy_course(tmp_path / "course-inbox" / "incoming-folder")

    with _site(tmp_path) as site:
        response = _post_import(
            site.client, headers={"Origin": "https://evil.example"}
        )

    assert response.status_code == 403
    assert not _courses_root(tmp_path).exists()


# -- dev-only gating and database fallback ---------------------------------


def test_disabled_import_returns_404(tmp_path: Path) -> None:
    _copy_course(tmp_path / "course-inbox" / "incoming-folder")

    with _site(tmp_path, course_import_enabled=False) as site:
        assert site.client.get("/import").status_code == 404
        response = _post_import(site.client)
        assert response.status_code == 404

    assert not _courses_root(tmp_path).exists()


def test_unmigrated_database_still_renders_and_import_still_works(
    tmp_path: Path,
) -> None:
    _copy_course(tmp_path / "course-inbox" / "incoming-folder")

    with _site(tmp_path, create_tables=False) as site:
        page = site.client.get("/import")
        assert page.status_code == 200
        assert "数据库未迁移" in page.text
        assert "不记来源" in page.text

        # Importing must not depend on the provenance table existing.
        params = _redirect_params(_post_import(site.client))
        assert params["imported"] == [SLUG]
        assert (_courses_root(tmp_path) / SLUG / "course.json").is_file()
        assert (_dist_root(tmp_path) / SLUG / "index.html").is_file()

        page = site.client.get("/import")
        assert page.status_code == 200
        assert "数据库未迁移" in page.text
