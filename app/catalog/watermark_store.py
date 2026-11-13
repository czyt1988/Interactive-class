"""Per-course watermark persistence in the site database, never in git.

A watermark identifies who a deployment is shown to, not what the course says,
so it must not travel with ``courses/<slug>/course.json`` or the repository
history. The admin page writes a row here, the build reads it and bakes the
layer into the built composition, and the standalone bundle keeps the watermark
without the database at play time.

Reads are deliberately forgiving: a fresh checkout may build courses before
``alembic upgrade head`` created the table, and a missing table must mean "no
watermark", not a failed build. Writes are strict so the admin page can report
a real database problem instead of silently dropping the config.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.catalog.models import SLUG_PATTERN, WatermarkConfig
from app.config import Settings
from app.db import create_db_engine, create_session_factory
from app.models import CourseWatermark

logger = logging.getLogger(__name__)

# The build CLI and the web process both resolve the same SQLite file; caching
# one engine per URL keeps the admin page from opening a pool on every request.
_FACTORIES: dict[str, sessionmaker[Session]] = {}
_LOCK = threading.Lock()


def _factory(settings: Settings) -> sessionmaker[Session]:
    url = settings.database_url
    with _LOCK:
        factory = _FACTORIES.get(url)
        if factory is None:
            factory = create_session_factory(create_db_engine(url))
            _FACTORIES[url] = factory
        return factory


def _validated_slug(slug: str) -> str:
    if not SLUG_PATTERN.fullmatch(slug) or Path(slug).name != slug:
        raise ValueError("课程 slug 不合法")
    return slug


def _decode(raw: str) -> WatermarkConfig | None:
    try:
        return WatermarkConfig.model_validate(json.loads(raw))
    except (ValueError, ValidationError) as exc:
        logger.warning("课程水印配置无法解析，按未配置处理：%s", exc)
        return None


def load_all(settings: Settings) -> dict[str, WatermarkConfig]:
    """Every stored watermark, keyed by course slug.

    Used by the admin list and by ``build_all`` so a rebuild keeps watermarks.
    """

    try:
        with _factory(settings)() as session:
            rows = session.execute(select(CourseWatermark)).scalars().all()
    except SQLAlchemyError as exc:
        logger.debug("读取课程水印失败，按未配置处理：%s", exc)
        return {}
    configs: dict[str, WatermarkConfig] = {}
    for row in rows:
        watermark = _decode(row.config)
        if watermark is not None:
            configs[row.course_slug] = watermark
    return configs


def load(settings: Settings, slug: str) -> WatermarkConfig | None:
    """One course's stored watermark, or ``None`` when nothing is configured."""

    slug = _validated_slug(slug)
    try:
        with _factory(settings)() as session:
            row = session.get(CourseWatermark, slug)
    except SQLAlchemyError as exc:
        logger.debug("读取课程水印失败，按未配置处理：%s", exc)
        return None
    return _decode(row.config) if row is not None else None


def save(settings: Settings, slug: str, watermark: WatermarkConfig | None) -> None:
    """Store or clear one course's watermark.

    ``None`` removes the row, matching the admin page's "clear" action. Errors
    propagate because the caller can show them in the page instead of pretending
    the save worked.
    """

    slug = _validated_slug(slug)
    session = _factory(settings)()
    try:
        if watermark is None:
            session.execute(
                delete(CourseWatermark).where(CourseWatermark.course_slug == slug)
            )
        else:
            payload = json.dumps(
                watermark.model_dump(exclude_none=True), ensure_ascii=False
            )
            row = session.get(CourseWatermark, slug)
            if row is None:
                session.add(CourseWatermark(course_slug=slug, config=payload))
            else:
                row.config = payload
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
