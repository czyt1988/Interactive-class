"""SQLAlchemy models for users, sessions and progress.

The schema is deliberately login-ready: anonymous learners and future accounts
share ``users``; anonymous and authenticated sessions share ``sessions``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str | None] = mapped_column(String(320), unique=True, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    is_anonymous: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    sessions: Mapped[list[Session]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    progress: Mapped[list[CourseProgress]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    user: Mapped[User] = relationship(back_populates="sessions")


class CourseProgress(Base):
    __tablename__ = "course_progress"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    course_slug: Mapped[str] = mapped_column(String(80), primary_key=True)
    last_screen_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="progress")


class ScreenProgress(Base):
    __tablename__ = "screen_progress"
    __table_args__ = (
        Index("ix_screen_progress_user_course", "user_id", "course_slug"),
        UniqueConstraint("user_id", "course_slug", "screen_id", name="uq_screen_progress"),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    course_slug: Mapped[str] = mapped_column(String(80), primary_key=True)
    screen_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class CourseWatermark(Base):
    """A course watermark kept in the site database instead of the course source.

    Watermarks identify who a deployment is shown to, not what the course says,
    so they must not travel with ``courses/<slug>/course.json`` or the repository
    history. The build reads the row and bakes the layer into the built
    composition, so the standalone bundle still carries it at play time without
    the database. ``config`` is the validated ``WatermarkConfig`` JSON.
    """

    __tablename__ = "course_watermarks"

    course_slug: Mapped[str] = mapped_column(String(80), primary_key=True)
    config: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class CourseClipConfig(Base):
    """Which intro/outro clips a course plays, kept out of the course source.

    A clip is shared site content, not part of a portable course manifest: the
    build injects the rendered scene into the built composition and the source
    ``course.json`` stays free of deployment choices. ``config`` is the validated
    ``ClipSelection`` JSON (``{"intro": "...", "outro": "..."}``).
    """

    __tablename__ = "course_clips"

    course_slug: Mapped[str] = mapped_column(String(80), primary_key=True)
    config: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class CourseImport(Base):
    """Where an imported course came from.

    Course content never enters this table: files under ``courses/<slug>/`` stay
    the single source of truth and the catalog still reads only ``dist/``. This
    row answers "which external folder produced this course, and when was it last
    imported", which is enough for the import page and provenance questions.
    """

    __tablename__ = "course_imports"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    source_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    screens: Mapped[int] = mapped_column(nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
