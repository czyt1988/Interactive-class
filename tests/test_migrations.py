from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def alembic_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    db_path = tmp_path / "app.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    from app.config import get_settings

    get_settings.cache_clear()
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    yield config
    get_settings.cache_clear()


def test_empty_database_upgrades_to_head(alembic_config: Config, tmp_path: Path) -> None:
    command.upgrade(alembic_config, "head")

    url = alembic_config.get_main_option("sqlalchemy.url")
    engine = create_engine(url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {"users", "sessions", "course_progress", "screen_progress", "course_imports"} <= tables

    index_names = {index["name"] for index in inspector.get_indexes("sessions")}
    assert "ix_sessions_user_id" in index_names
    assert "ix_sessions_expires_at" in index_names

    import_indexes = {
        index["name"]: index["unique"] for index in inspector.get_indexes("course_imports")
    }
    assert import_indexes.get("ix_course_imports_slug")

    with engine.connect() as connection:
        version = connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
    assert version == "0002_course_imports"
    engine.dispose()


def test_migration_is_reversible(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")

    url = alembic_config.get_main_option("sqlalchemy.url")
    engine = create_engine(url)
    tables = set(inspect(engine).get_table_names())
    assert "users" not in tables
    engine.dispose()


def test_models_match_a_migrated_database(alembic_config: Config) -> None:
    """The ORM metadata and the migration must describe the same tables."""

    command.upgrade(alembic_config, "head")
    url = alembic_config.get_main_option("sqlalchemy.url")
    engine = create_engine(url)

    from app import models  # noqa: F401
    from app.db import Base

    migrated = {
        table: {column["name"] for column in inspect(engine).get_columns(table)}
        for table in inspect(engine).get_table_names()
        if table != "alembic_version"
    }
    declared = {
        table.name: {column.name for column in table.columns} for table in Base.metadata.sorted_tables
    }
    assert migrated == declared
    engine.dispose()


def test_backup_copy_is_readable(alembic_config: Config, tmp_path: Path) -> None:
    """A backup is a consistent snapshot; VACUUM INTO is the safe way to take one."""

    command.upgrade(alembic_config, "head")
    url = alembic_config.get_main_option("sqlalchemy.url")
    db_path = Path(url.removeprefix("sqlite:///"))

    backup = tmp_path / "backup.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("VACUUM INTO ?", (str(backup),))

    with sqlite3.connect(backup) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert {"users", "sessions", "course_progress", "screen_progress", "course_imports"} <= tables


def test_upgrade_creates_a_missing_database_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fresh checkout has no data/ directory; the first migration must still work."""

    db_path = tmp_path / "data" / "nested" / "app.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        config = Config(str(ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(ROOT / "migrations"))
        command.upgrade(config, "head")
    finally:
        get_settings.cache_clear()

    assert db_path.is_file()
    with sqlite3.connect(db_path) as connection:
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert version == ("0002_course_imports",)
