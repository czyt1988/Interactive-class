from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Base
from app.main import create_app


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
    )


@pytest.fixture
def app(settings: Settings):
    application = create_app(settings)
    Base.metadata.create_all(application.state.engine)
    return application


@pytest.fixture
def client(app) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
