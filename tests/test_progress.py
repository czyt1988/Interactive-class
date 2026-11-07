from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.catalog.resolver import resolve_course

FIXTURE = Path(__file__).parent / "fixtures" / "courses" / "valid-two-screen"
SLUG = "valid-two-screen"


@pytest.fixture
def course_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist" / "courses"
    payload = resolve_course(FIXTURE).model_dump()
    target = dist / SLUG
    target.mkdir(parents=True)
    (target / "course.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (target / "index.html").write_text("<!doctype html><title>course</title>", encoding="utf-8")
    (target / "composition").mkdir()
    (target / "composition" / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (target / "runtime").mkdir()
    return dist


@pytest.fixture
def client_with_course(settings, course_dist: Path):
    settings.courses_dist_dir = course_dist
    from app.db import Base
    from app.main import create_app

    application = create_app(settings)
    Base.metadata.create_all(application.state.engine)
    with TestClient(application) as test_client:
        yield test_client


def test_get_without_cookie_returns_empty_and_creates_nothing(client_with_course: TestClient) -> None:
    response = client_with_course.get(f"/api/progress/{SLUG}")
    assert response.status_code == 200
    body = response.json()
    assert body["lastScreenId"] is None
    assert body["completedScreens"] == []
    assert "al_session" not in response.cookies


def test_put_creates_anonymous_session_and_cookie(client_with_course: TestClient) -> None:
    response = client_with_course.put(f"/api/progress/{SLUG}", json={"screenId": "hook"})
    assert response.status_code == 200
    assert response.json()["lastScreenId"] == "hook"
    cookie = response.cookies.get("al_session")
    assert cookie
    assert "httponly" in response.headers["set-cookie"].lower()
    assert "samesite=lax" in response.headers["set-cookie"].lower()


def test_put_is_idempotent(client_with_course: TestClient) -> None:
    first = client_with_course.put(f"/api/progress/{SLUG}", json={"screenId": "hook", "completed": True})
    second = client_with_course.put(f"/api/progress/{SLUG}", json={"screenId": "hook", "completed": True})
    assert first.status_code == second.status_code == 200
    assert second.json()["completedScreens"] == ["hook"]


def test_get_reads_back_written_progress(client_with_course: TestClient) -> None:
    client_with_course.put(f"/api/progress/{SLUG}", json={"screenId": "split", "completed": True})
    response = client_with_course.get(f"/api/progress/{SLUG}")
    body = response.json()
    assert body["lastScreenId"] == "split"
    assert body["completedScreens"] == ["split"]
    assert body["updatedAt"]


def test_unknown_course_is_rejected(client_with_course: TestClient) -> None:
    response = client_with_course.put("/api/progress/nope", json={"screenId": "hook"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "course_not_found"


def test_unknown_screen_is_rejected(client_with_course: TestClient) -> None:
    response = client_with_course.put(f"/api/progress/{SLUG}", json={"screenId": "nope"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "screen_not_found"


def test_invalid_body_is_rejected(client_with_course: TestClient) -> None:
    response = client_with_course.put(f"/api/progress/{SLUG}", json={"screenId": "Hook!"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_cross_origin_write_is_rejected(client_with_course: TestClient) -> None:
    response = client_with_course.put(
        f"/api/progress/{SLUG}",
        json={"screenId": "hook"},
        headers={"origin": "https://evil.example.com"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "origin_not_allowed"


def test_all_progress_lists_courses(client_with_course: TestClient) -> None:
    client_with_course.put(f"/api/progress/{SLUG}", json={"screenId": "hook", "completed": True})
    response = client_with_course.get("/api/progress")
    body = response.json()
    assert len(body["courses"]) == 1
    assert body["courses"][0]["courseSlug"] == SLUG


def test_course_completes_after_all_screens(client_with_course: TestClient) -> None:
    for screen_id in ("hook", "split"):
        client_with_course.put(
            f"/api/progress/{SLUG}", json={"screenId": screen_id, "completed": True}
        )
    response = client_with_course.get("/api/progress")
    assert response.json()["courses"][0]["completed"] is True


def test_readyz_reports_schema_version(client_with_course: TestClient) -> None:
    response = client_with_course.get("/readyz")
    assert response.status_code in (200, 503)
    assert "db" in response.json()
