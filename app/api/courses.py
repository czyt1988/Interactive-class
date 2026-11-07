"""Read-only course catalog API and health endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.orm import Session as OrmSession

from app.api.errors import ApiError
from app.catalog.models import Catalog
from app.config import Settings
from app.deps import get_catalog, get_db, get_settings

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/courses")
def list_courses(
    settings: Settings = Depends(get_settings),
    catalog: Catalog = Depends(get_catalog),
) -> dict[str, Any]:
    return {
        "courses": [
            summary.model_dump()
            for summary in catalog.summaries(
                include_drafts=bool(settings.include_drafts),
                course_base_url=settings.course_base_url,
            )
        ],
        "stats": catalog.stats.model_dump(),
    }


@router.get("/courses/{slug}")
def get_course(
    slug: str,
    settings: Settings = Depends(get_settings),
    catalog: Catalog = Depends(get_catalog),
) -> dict[str, Any]:
    course = catalog.by_slug(slug)
    if course is None or (course.status != "published" and not settings.include_drafts):
        raise ApiError(404, "course_not_found", f"没有找到课程 {slug!r}", slug=slug)
    return course.model_dump()


def _schema_version(db: OrmSession) -> str | None:
    try:
        return db.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar_one_or_none()
    except Exception:
        return None


@router.get("/health")
def api_health(
    request: Request,
    catalog: Catalog = Depends(get_catalog),
    db: OrmSession = Depends(get_db),
) -> dict[str, Any]:
    db_ok = True
    schema_version: str | None = None
    try:
        db.execute(text("SELECT 1")).scalar_one()
        schema_version = _schema_version(db)
    except Exception:
        db_ok = False
        schema_version = None

    return {
        "status": "ok" if not catalog.errors and db_ok else "degraded",
        "published": catalog.stats.published,
        "drafts": catalog.stats.total - catalog.stats.published,
        "total": catalog.stats.total,
        "invalid": catalog.stats.invalid,
        "db": {"ok": db_ok, "schemaVersion": schema_version},
        "errors": [error.model_dump() for error in catalog.errors],
        "build": getattr(request.app.state, "build_info", {}),
    }
