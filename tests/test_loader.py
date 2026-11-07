from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.catalog.loader import CatalogLoader, CatalogLoadError
from app.catalog.resolver import resolve_course

FIXTURE = Path(__file__).parent / "fixtures" / "courses" / "valid-two-screen"


def write_resolved_course(
    dist_dir: Path,
    *,
    bundles: bool = True,
    mutate: dict | None = None,
) -> Path:
    course = resolve_course(FIXTURE)
    payload = course.model_dump()
    if mutate:
        payload.update(mutate)
    target = dist_dir / payload["slug"]
    target.mkdir(parents=True, exist_ok=True)
    (target / "course.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if bundles:
        (target / "index.html").write_text("<!doctype html><title>course</title>", encoding="utf-8")
        composition = target / "composition"
        composition.mkdir(exist_ok=True)
        (composition / "index.html").write_text("<!doctype html><title>composition</title>")
        (target / "runtime").mkdir(exist_ok=True)
    return target


def test_loader_reads_resolved_manifest(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    write_resolved_course(dist)
    catalog = CatalogLoader(dist).load()
    assert len(catalog.courses) == 1
    assert catalog.courses[0].slug == "valid-two-screen"
    assert catalog.stats.published == 1
    assert catalog.stats.invalid == 0


def test_loader_reports_invalid_manifest(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    target = write_resolved_course(dist)
    (target / "course.json").write_text('{"schemaVersion": 1}', encoding="utf-8")
    catalog = CatalogLoader(dist).load()
    assert not catalog.courses
    assert catalog.errors[0].code == "manifest_invalid"
    assert catalog.errors[0].slug == "valid-two-screen"


def test_loader_reports_slug_mismatch(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    target = write_resolved_course(dist)
    payload = json.loads((target / "course.json").read_text(encoding="utf-8"))
    payload["slug"] = "another-slug"
    (target / "course.json").write_text(json.dumps(payload), encoding="utf-8")
    catalog = CatalogLoader(dist).load()
    assert not catalog.courses
    assert catalog.errors[0].code == "slug_mismatch"


def test_loader_reports_missing_bundle(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    write_resolved_course(dist, bundles=False)
    catalog = CatalogLoader(dist, verify_bundles=True).load()
    assert not catalog.courses
    assert {error.code for error in catalog.errors} == {"bundle_incomplete"}


def test_loader_can_skip_bundle_verification(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    write_resolved_course(dist, bundles=False)
    catalog = CatalogLoader(dist, verify_bundles=False).load()
    assert len(catalog.courses) == 1


def test_loader_strict_mode_raises(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    write_resolved_course(dist, bundles=False)
    with pytest.raises(CatalogLoadError):
        CatalogLoader(dist).load(strict=True)


def test_loader_cache_sees_new_manifest(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    write_resolved_course(dist)
    loader = CatalogLoader(dist)
    first = loader.load()
    assert first.courses[0].featured is False

    target = dist / "valid-two-screen"
    payload = json.loads((target / "course.json").read_text(encoding="utf-8"))
    payload["featured"] = True
    (target / "course.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    second = loader.load()
    assert second.courses[0].featured is True


def test_course_api_lists_summary_and_detail(client: TestClient, settings) -> None:
    write_resolved_course(settings.courses_dist_dir)

    listing = client.get("/api/courses")
    assert listing.status_code == 200
    body = listing.json()
    assert len(body["courses"]) == 1
    summary = body["courses"][0]
    assert summary["slug"] == "valid-two-screen"
    assert summary["courseUrl"] == "/courses/valid-two-screen/"
    assert summary["screenCount"] == 2
    assert "screens" not in summary

    detail = client.get("/api/courses/valid-two-screen")
    assert detail.status_code == 200
    course = detail.json()
    assert course["screens"][0]["start"] == 0
    assert course["screens"][1]["start"] == 2
    assert course["stats"]["durationSeconds"] == 4


def test_course_api_unknown_slug_uses_error_shape(client: TestClient) -> None:
    response = client.get("/api/courses/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "course_not_found"


def test_site_lists_course_card(client: TestClient, settings) -> None:
    write_resolved_course(settings.courses_dist_dir)
    home = client.get("/")
    assert home.status_code == 200
    assert "两屏测试课" in home.text
    assert 'href="/courses/valid-two-screen/"' in home.text

    library = client.get("/courses")
    assert library.status_code == 200
    assert "两屏测试课" in library.text
