"""Learning progress API.

Writes create an anonymous learner and session on first use; reads never
create one. Writes are validated against the resolved catalog, so a bad slug
or screen id can never enter the database.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session as OrmSession

from app.api.errors import ApiError
from app.auth.sessions import get_optional_learner, get_or_create_learner
from app.catalog.models import Catalog, ResolvedCourse
from app.config import Settings
from app.deps import get_catalog, get_db, get_settings
from app.repositories.progress import get_all_progress, get_progress, upsert_progress
from app.schemas import AllProgressResponse, ProgressResponse, ProgressUpdate

router = APIRouter(prefix="/api/progress", tags=["progress"])


def _get_course(slug: str, catalog: Catalog, settings: Settings) -> ResolvedCourse:
    course = catalog.by_slug(slug)
    if course is None or (course.status != "published" and not settings.include_drafts):
        raise ApiError(404, "course_not_found", f"没有找到课程 {slug!r}", slug=slug)
    return course


@router.get("/{course_slug}", response_model=ProgressResponse)
def read_progress(
    course_slug: str,
    request: Request,
    settings: Settings = Depends(get_settings),
    catalog: Catalog = Depends(get_catalog),
    db: OrmSession = Depends(get_db),
) -> ProgressResponse:
    course = _get_course(course_slug, catalog, settings)
    user = get_optional_learner(request, db)
    if user is None:
        return ProgressResponse()
    return get_progress(db, user, course)


@router.put("/{course_slug}", response_model=ProgressResponse)
def write_progress(
    course_slug: str,
    payload: ProgressUpdate,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    catalog: Catalog = Depends(get_catalog),
    db: OrmSession = Depends(get_db),
) -> ProgressResponse:
    length = request.headers.get("content-length")
    if length is not None:
        try:
            if int(length) > settings.progress_max_body_bytes:
                raise ApiError(413, "body_too_large", "请求体超过限制")
        except ValueError as exc:
            raise ApiError(400, "invalid_request", "Content-Length 不合法") from exc

    origin = request.headers.get("origin")
    if origin is not None and origin != f"{request.url.scheme}://{request.url.netloc}":
        raise ApiError(403, "origin_not_allowed", "只接受同源写请求", origin=origin)

    course = _get_course(course_slug, catalog, settings)
    if payload.screenId not in {screen.id for screen in course.screens}:
        raise ApiError(
            422,
            "screen_not_found",
            f"课程 {course_slug!r} 没有屏幕 {payload.screenId!r}",
            slug=course_slug,
            screenId=payload.screenId,
        )

    user = get_or_create_learner(request, response, db, settings)
    result = upsert_progress(db, user, course, payload.screenId, payload.completed)
    db.commit()
    return result


@router.get("", response_model=AllProgressResponse)
def read_all_progress(
    request: Request,
    settings: Settings = Depends(get_settings),
    catalog: Catalog = Depends(get_catalog),
    db: OrmSession = Depends(get_db),
) -> AllProgressResponse:
    user = get_optional_learner(request, db)
    if user is None:
        return AllProgressResponse()
    courses = {course.slug: course for course in catalog.courses}
    return AllProgressResponse(courses=get_all_progress(db, user, courses))


@router.get("/", include_in_schema=False)
def read_all_progress_slash(
    request: Request,
    settings: Settings = Depends(get_settings),
    catalog: Catalog = Depends(get_catalog),
    db: OrmSession = Depends(get_db),
) -> AllProgressResponse:
    return read_all_progress(request, settings, catalog, db)
