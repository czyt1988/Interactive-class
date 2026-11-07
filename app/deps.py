"""FastAPI dependencies shared by the site and API routers."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session as OrmSession

from app.catalog.models import Catalog
from app.config import Settings


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_catalog(request: Request) -> Catalog:
    return request.app.state.catalog_loader.load(strict=False)


def get_db(request: Request) -> Iterator[OrmSession]:
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()
