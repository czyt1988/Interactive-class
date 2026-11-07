"""Anonymous learner sessions.

A session token is 32 random bytes, sent in an HttpOnly cookie; the database
stores only its SHA-256 hash. Read endpoints never create a user. Writes create
one anonymous user and session on first use.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.config import Settings
from app.models import Session, User

COOKIE_NAME = "al_session"
TOKEN_BYTES = 32


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def get_optional_learner(request: Request, db: OrmSession) -> User | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    session = db.scalar(
        select(Session).where(
            Session.token_hash == hash_token(token),
            Session.expires_at > utcnow(),
        )
    )
    if session is None:
        return None
    return db.get(User, session.user_id)


def create_learner(
    response: Response,
    db: OrmSession,
    settings: Settings,
) -> User:
    now = utcnow()
    user = User(is_anonymous=True, created_at=now, updated_at=now)
    db.add(user)
    db.flush()

    token = secrets.token_urlsafe(TOKEN_BYTES)
    session = Session(
        user_id=user.id,
        token_hash=hash_token(token),
        created_at=now,
        expires_at=now + timedelta(days=settings.session_cookie_days),
        last_seen_at=now,
    )
    db.add(session)
    db.flush()

    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_cookie_days * 24 * 60 * 60,
        httponly=True,
        secure=bool(settings.session_cookie_secure),
        samesite="lax",
        path="/",
    )
    return user


def get_or_create_learner(
    request: Request,
    response: Response,
    db: OrmSession,
    settings: Settings,
) -> User:
    existing = get_optional_learner(request, db)
    if existing is not None:
        return existing
    return create_learner(response, db, settings)


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")
