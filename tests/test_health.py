from __future__ import annotations

from fastapi.testclient import TestClient


def test_healthz_returns_ok(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_home_renders_site_name(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "页间课堂" in response.text
    assert "一门可以翻页的" in response.text
    assert "AI Learning 系列" in response.text
    assert "动画要承担论证" not in response.text
    assert "一叠会停的幻灯片" not in response.text
    assert "不是视频课" not in response.text


def test_empty_catalog_has_helpful_state(client: TestClient) -> None:
    response = client.get("/courses")
    assert response.status_code == 200
    assert "没有匹配的课程" in response.text


def test_about_and_404(client: TestClient) -> None:
    assert client.get("/about").status_code == 200
    missing = client.get("/does-not-exist")
    assert missing.status_code == 404
    assert "这一屏不存在" in missing.text


def test_api_health_shape(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ok", "degraded"}
    assert "published" in body
    assert "db" in body
