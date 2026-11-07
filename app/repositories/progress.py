"""Progress read/write logic.

The repository is the only module that decides what "completed" means. It
validates against the resolved catalog before writing, never stores course
content, and keeps ``course_progress`` and ``screen_progress`` consistent in
the same transaction.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.catalog.models import ResolvedCourse
from app.models import CourseProgress, ScreenProgress, User
from app.schemas import CourseProgressResponse, ProgressResponse


def _now() -> datetime:
    return datetime.now(UTC)


def _completed_screens(db: OrmSession, user_id: int, course_slug: str) -> list[str]:
    rows = db.scalars(
        select(ScreenProgress.screen_id)
        .where(
            ScreenProgress.user_id == user_id,
            ScreenProgress.course_slug == course_slug,
        )
        .order_by(ScreenProgress.completed_at)
    )
    return list(rows)


def get_progress(
    db: OrmSession,
    user: User,
    course: ResolvedCourse,
) -> ProgressResponse:
    row = db.get(CourseProgress, {"user_id": user.id, "course_slug": course.slug})
    if row is None:
        return ProgressResponse()
    completed = _completed_screens(db, user.id, course.slug)
    return ProgressResponse(
        lastScreenId=row.last_screen_id,
        completedScreens=completed,
        updatedAt=row.updated_at,
    )


def get_course_progress(
    db: OrmSession,
    user: User,
    course: ResolvedCourse,
) -> CourseProgressResponse:
    base = get_progress(db, user, course)
    row = db.get(CourseProgress, {"user_id": user.id, "course_slug": course.slug})
    return CourseProgressResponse(
        courseSlug=course.slug,
        completed=bool(row and row.completed_at),
        **base.model_dump(),
    )


def upsert_progress(
    db: OrmSession,
    user: User,
    course: ResolvedCourse,
    screen_id: str,
    completed: bool,
) -> ProgressResponse:
    now = _now()
    row = db.get(CourseProgress, {"user_id": user.id, "course_slug": course.slug})
    if row is None:
        row = CourseProgress(
            user_id=user.id,
            course_slug=course.slug,
            last_screen_id=screen_id,
            started_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        row.last_screen_id = screen_id
        row.updated_at = now

    if completed:
        key = {"user_id": user.id, "course_slug": course.slug, "screen_id": screen_id}
        if db.get(ScreenProgress, key) is None:
            db.add(
                ScreenProgress(
                    user_id=user.id,
                    course_slug=course.slug,
                    screen_id=screen_id,
                    completed_at=now,
                    updated_at=now,
                )
            )
    db.flush()

    total = len(course.screens)
    done = _completed_screens(db, user.id, course.slug)
    if row.completed_at is None and len(done) >= total:
        row.completed_at = now
        row.updated_at = now
        db.flush()

    return ProgressResponse(
        lastScreenId=row.last_screen_id,
        completedScreens=done,
        updatedAt=row.updated_at,
    )


def get_all_progress(
    db: OrmSession,
    user: User,
    courses: dict[str, ResolvedCourse],
) -> list[CourseProgressResponse]:
    rows = db.scalars(
        select(CourseProgress)
        .where(CourseProgress.user_id == user.id)
        .order_by(CourseProgress.updated_at.desc())
    )
    result: list[CourseProgressResponse] = []
    for row in rows:
        course = courses.get(row.course_slug)
        if course is None:
            continue
        completed = _completed_screens(db, user.id, row.course_slug)
        result.append(
            CourseProgressResponse(
                courseSlug=row.course_slug,
                lastScreenId=row.last_screen_id,
                completedScreens=completed,
                updatedAt=row.updated_at,
                completed=bool(row.completed_at),
            )
        )
    return result
