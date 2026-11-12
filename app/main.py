"""FastAPI application factory.

The site has two jobs: render the catalog pages and serve the built course
bundles. It does not parse course sources at request time, except the
authenticated watermark editor, which writes one course's source manifest and
rebuilds that bundle.
"""

from __future__ import annotations

import json
import logging
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.api.courses import router as courses_api_router
from app.api.errors import ApiError
from app.api.progress import router as progress_api_router
from app.catalog.loader import CatalogLoader
from app.config import Settings, get_settings
from app.db import create_db_engine, create_session_factory
from app.formatting import format_duration
from app.videos.manager import RenderManager
from app.web.admin import router as admin_router
from app.web.import_routes import router as import_router
from app.web.routes import LEVEL_LABELS, SITE_DESCRIPTION
from app.web.routes import router as web_router

logger = logging.getLogger(__name__)
APP_DIR = Path(__file__).resolve().parent

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Frame-Options": "SAMEORIGIN",
}

SITE_CSP = (
    "default-src 'self'; "
    "img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; "
    "font-src 'self'; "
    "frame-ancestors 'self'; "
    "base-uri 'self'; "
    "form-action 'self'"
)

# Windows registries and minimal Linux images disagree about a few extensions;
# a course bundle is only playable if its ES module is served as JavaScript.
MIME_TYPES = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".woff2": "font/woff2",
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".svg": "image/svg+xml",
}


def register_mime_types() -> None:
    """Pin the MIME types a course bundle needs.

    ``mimetypes`` reads the Windows registry, where ``.js`` is sometimes mapped
    to ``text/plain``; browsers then refuse to execute the deck's module script.
    """

    for suffix, content_type in MIME_TYPES.items():
        mimetypes.add_type(content_type, suffix)


register_mime_types()


def level_label(level: str) -> str:
    return LEVEL_LABELS.get(level, level)


def _build_info(settings: Settings) -> dict[str, Any]:
    path = settings.courses_dist_dir.parent / "build.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _error_payload(code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details}}


def create_app(settings: Settings | None = None) -> FastAPI:
    active = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        catalog = app.state.catalog_loader.load(strict=bool(active.strict_catalog))
        app.state.catalog = catalog
        app.state.build_info = _build_info(active)
        logger.info(
            "catalog loaded: %s courses (%s published), %s errors",
            catalog.stats.total,
            catalog.stats.published,
            catalog.stats.invalid,
        )
        # A previous process may have died mid-render; mark it interrupted so
        # the admin page never shows a stale "generating" row forever.
        app.state.video_manager.reconcile()
        try:
            yield
        finally:
            app.state.video_manager.close()

    app = FastAPI(
        title=active.site_title,
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs" if not active.is_prod else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if not active.is_prod else None,
    )

    app.state.settings = active
    app.state.catalog_loader = CatalogLoader(
        active.courses_dist_dir,
        verify_bundles=bool(active.verify_course_bundles),
    )
    app.state.video_manager = RenderManager(active)
    app.state.engine = create_db_engine(active.database_url)
    app.state.session_factory = create_session_factory(app.state.engine)
    app.state.build_info = {}
    app.state.catalog = None

    templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
    templates.env.globals.update(
        format_duration=format_duration,
        level_label=level_label,
        site_description=SITE_DESCRIPTION,
    )
    app.state.templates = templates

    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        # Course pages inject the player, the inline manifest and scene scripts,
        # so they get their own CSP at the static/CDN layer rather than the site one.
        if not request.url.path.startswith("/courses"):
            response.headers.setdefault("Content-Security-Policy", SITE_CSP)
        return response

    @app.exception_handler(ApiError)
    async def handle_api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(exc.payload(), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            {"field": ".".join(str(part) for part in item.get("loc", ())), "message": item.get("msg")}
            for item in exc.errors()
        ]
        return JSONResponse(
            _error_payload("invalid_request", "请求参数不合法", errors=details),
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> Response:
        if request.url.path.startswith("/api/"):
            return JSONResponse(
                _error_payload("http_error", str(exc.detail), status=exc.status_code),
                status_code=exc.status_code,
            )
        if exc.status_code == 404:
            return templates.TemplateResponse(
                request=request,
                name="404.html",
                context={
                    "site": {
                        "title": active.site_title,
                        "url": active.site_url.rstrip("/"),
                        "course_base_url": active.course_base_url,
                        "description": SITE_DESCRIPTION,
                    },
                    "canonical": f"{active.site_url.rstrip('/')}{request.url.path}",
                    "page": "404",
                },
                status_code=404,
            )
        return JSONResponse(
            _error_payload("http_error", str(exc.detail), status=exc.status_code),
            status_code=exc.status_code,
        )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/readyz")
    def readyz(request: Request) -> Response:
        db = request.app.state.session_factory()
        try:
            db.execute(text("SELECT 1")).scalar_one()
            version = db.execute(
                text("SELECT version_num FROM alembic_version LIMIT 1")
            ).scalar_one_or_none()
        except Exception as exc:  # noqa: BLE001 - health endpoint must not raise
            return JSONResponse(
                {"status": "unavailable", "db": {"ok": False, "error": type(exc).__name__}},
                status_code=503,
            )
        finally:
            db.close()
        if version is None:
            return JSONResponse(
                {"status": "unavailable", "db": {"ok": True, "schemaVersion": None}},
                status_code=503,
            )
        return JSONResponse({"status": "ok", "db": {"ok": True, "schemaVersion": version}})

    app.include_router(web_router)
    app.include_router(import_router)
    app.include_router(admin_router)
    app.include_router(courses_api_router)
    app.include_router(progress_api_router)

    app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
    app.mount(
        "/courses",
        StaticFiles(directory=str(active.courses_dist_dir), html=True, check_dir=False),
        name="courses",
    )

    return app


app = create_app()
