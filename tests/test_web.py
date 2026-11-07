from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.catalog.resolver import resolve_course

FIXTURE = Path(__file__).parent / "fixtures" / "courses" / "valid-two-screen"


def write_course(dist: Path, *, featured: bool = False, level: str = "beginner", tags=None) -> None:
    payload = resolve_course(FIXTURE).model_dump()
    payload["featured"] = featured
    payload["level"] = level
    payload["tags"] = tags or ["测试"]
    target = dist / payload["slug"]
    target.mkdir(parents=True, exist_ok=True)
    (target / "course.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    (target / "index.html").write_text("<!doctype html><title>c</title>", encoding="utf-8")
    (target / "composition").mkdir(exist_ok=True)
    (target / "composition" / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (target / "runtime").mkdir(exist_ok=True)
    (target / "runtime" / "course-deck.js").write_text("export {};", encoding="utf-8")


@pytest.fixture
def site(settings):
    from app.db import Base
    from app.main import create_app

    write_course(settings.courses_dist_dir)
    application = create_app(settings)
    Base.metadata.create_all(application.state.engine)
    with TestClient(application) as client:
        yield client


def test_home_shows_course_card(site: TestClient) -> None:
    response = site.get("/")
    assert response.status_code == 200
    assert "两屏测试课" in response.text
    assert "/courses/valid-two-screen/" in response.text


def test_library_lists_and_filters(site: TestClient) -> None:
    assert "两屏测试课" in site.get("/courses").text

    filtered_out = site.get("/courses?level=advanced")
    assert filtered_out.status_code == 200
    assert "两屏测试课" not in filtered_out.text
    assert "没有匹配的课程" in filtered_out.text

    filtered_in = site.get("/courses?level=beginner")
    assert "两屏测试课" in filtered_in.text


def test_library_slash_redirects(site: TestClient) -> None:
    response = site.get("/courses/", follow_redirects=False)
    assert response.status_code in (307, 308)
    assert response.headers["location"].endswith("/courses")


def test_about_page(site: TestClient) -> None:
    response = site.get("/about")
    assert response.status_code == 200
    assert "六条不能删的原则" in response.text


def test_sitemap_and_robots(site: TestClient) -> None:
    sitemap = site.get("/sitemap.xml")
    assert sitemap.status_code == 200
    assert "/courses/valid-two-screen/" in sitemap.text

    robots = site.get("/robots.txt")
    assert robots.status_code == 200
    assert "Sitemap:" in robots.text


def test_security_headers(site: TestClient) -> None:
    response = site.get("/")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" in response.headers


def test_courses_mount_serves_bundle(site: TestClient) -> None:
    response = site.get("/courses/valid-two-screen/")
    assert response.status_code == 200


def test_es_modules_are_served_as_javascript(site: TestClient) -> None:
    """A course bundle is only playable if its module script has a JS MIME type.

    On Windows, ``mimetypes`` reads the registry and may map ``.js`` to
    ``text/plain``; the app pins the types it needs at import time.
    """

    response = site.get("/courses/valid-two-screen/runtime/course-deck.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]