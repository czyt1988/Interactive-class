"""Per-course intro/outro selection in the site database, never in git.

Which clip a course opens with (and closes with) is deployment configuration,
like its watermark: the clip library belongs to the site, and ``course.json``
stays a portable course manifest. The admin page writes a row here, the build
reads it and bakes the rendered scene into the composition, so the standalone
bundle still plays the intro without the database.

Reads are forgiving: a checkout that has not run ``alembic upgrade head`` yet
builds courses normally with no clip. Writes are strict so the admin page can
report a real database problem instead of silently dropping the selection.
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

from app.catalog.models import SLUG_PATTERN, ClipSelection
from app.config import Settings
from app.db import create_db_engine, create_session_factory
from app.models import CourseClipConfig

logger = logging.getLogger(__name__)

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


def _decode(raw: str) -> ClipSelection | None:
    try:
        selection = ClipSelection.model_validate(json.loads(raw))
    except (ValueError, ValidationError) as exc:
        logger.warning("课程片头/片尾配置无法解析，按未配置处理：%s", exc)
        return None
    return None if selection.is_empty else selection


def load_all(settings: Settings) -> dict[str, ClipSelection]:
    """Every stored selection, keyed by course slug."""

    try:
        with _factory(settings)() as session:
            rows = session.execute(select(CourseClipConfig)).scalars().all()
    except SQLAlchemyError as exc:
        logger.debug("读取课程片头/片尾失败，按未配置处理：%s", exc)
        return {}
    selections: dict[str, ClipSelection] = {}
    for row in rows:
        selection = _decode(row.config)
        if selection is not None:
            selections[row.course_slug] = selection
    return selections


def load(settings: Settings, slug: str) -> ClipSelection | None:
    """One course's stored selection, or ``None`` when nothing is configured."""

    slug = _validated_slug(slug)
    try:
        with _factory(settings)() as session:
            row = session.get(CourseClipConfig, slug)
    except SQLAlchemyError as exc:
        logger.debug("读取课程片头/片尾失败，按未配置处理：%s", exc)
        return None
    return _decode(row.config) if row is not None else None


def save(settings: Settings, slug: str, selection: ClipSelection | None) -> None:
    """Store or clear one course's selection; errors propagate to the admin page."""

    slug = _validated_slug(slug)
    session = _factory(settings)()
    try:
        if selection is None or selection.is_empty:
            session.execute(
                delete(CourseClipConfig).where(CourseClipConfig.course_slug == slug)
            )
        else:
            payload = json.dumps(
                selection.model_dump(exclude_none=True), ensure_ascii=False
            )
            row = session.get(CourseClipConfig, slug)
            if row is None:
                session.add(CourseClipConfig(course_slug=slug, config=payload))
            else:
                row.config = payload
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
