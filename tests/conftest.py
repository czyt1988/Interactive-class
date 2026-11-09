from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.catalog.resolver import resolve_course
from app.config import Settings
from app.db import Base
from app.main import create_app

FIXTURE_COURSE = Path(__file__).parent / "fixtures" / "courses" / "valid-two-screen"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        env="dev",
        courses_dist_dir=tmp_path / "dist" / "courses",
        courses_src_dir=tmp_path / "courses",
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        strict_catalog=False,
        include_drafts=True,
        verify_course_bundles=True,
        video_output_dir=tmp_path / "data" / "videos",
        video_work_dir=tmp_path / "data" / "videos" / ".work",
    )


@pytest.fixture
def write_course() -> Callable[..., Path]:
    """Write the resolved two-screen fixture into a dist directory."""

    def _write(
        dist: Path,
        *,
        featured: bool = False,
        level: str = "beginner",
        tags: list[str] | None = None,
    ) -> Path:
        payload = resolve_course(FIXTURE_COURSE).model_dump()
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
        (target / "composition" / "index.html").write_text(
            "<!doctype html>", encoding="utf-8"
        )
        (target / "runtime").mkdir(exist_ok=True)
        (target / "runtime" / "course-deck.js").write_text("export {};", encoding="utf-8")
        return target

    return _write


@pytest.fixture
def app(settings: Settings):
    application = create_app(settings)
    Base.metadata.create_all(application.state.engine)
    return application


@pytest.fixture
def client(app) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
