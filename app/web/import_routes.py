"""Dev-only course import page.

The page is a small, server-rendered form over ``app.catalog.importing``: it
lists the folders waiting in the course inbox, runs the same validate, copy and
build pipeline as ``scripts/import_course.py``, and records provenance in
SQLite. It only exists when ``Settings.course_import_enabled`` is true, which is
the default in development and off in production.

The import itself is synchronous. Building a course takes a few seconds and this
is an authoring tool, so there is no job queue to poll: the browser posts a plain
``application/x-www-form-urlencoded`` form, waits for the redirect, and lands back
on the page with a success or error message in the query string.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session as OrmSession

from app.catalog.importing import (
    ImportCandidate,
    ImportResult,
    discover_course_sources,
    import_course,
    inspect_course,
    list_imports,
    record_import,
)
from app.catalog.models import CatalogError
from app.config import BASE_DIR, Settings
from app.deps import get_db
from app.formatting import format_timestamp
from app.web.routes import site_context

router = APIRouter(tags=["import"])

MAX_RECENT_IMPORTS = 12
MAX_ERROR_CHARS = 180
PATH_SEPARATORS = ("/", "\\")
STATUS_LABELS = {
    "ready": "可导入",
    "exists": "已存在",
    "invalid": "需修复",
}


# -- helpers ---------------------------------------------------------------


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _require_enabled(request: Request) -> Settings:
    settings = _settings(request)
    if not settings.course_import_enabled:
        raise HTTPException(status_code=404)
    return settings


def _require_same_origin(request: Request) -> None:
    """Reject cross-site form posts: importing writes to the repository."""

    origin = request.headers.get("origin")
    if not origin:
        return
    host = request.headers.get("host", "")
    try:
        origin_host = urlsplit(origin).netloc
    except ValueError:
        origin_host = ""
    if not host or origin_host != host:
        raise HTTPException(status_code=403, detail="跨站请求被拒绝")


def _relative_label(path: Path) -> str:
    """Show paths inside the repository relative to its root, like /admin does."""

    try:
        return f"{path.relative_to(BASE_DIR).as_posix()}/"
    except ValueError:
        return f"{path}/"


def _short(message: str) -> str:
    collapsed = " ".join(message.split())
    if len(collapsed) <= MAX_ERROR_CHARS:
        return collapsed
    return f"{collapsed[: MAX_ERROR_CHARS - 1]}…"


def _redirect(**params: str) -> RedirectResponse:
    return RedirectResponse(f"/import?{urlencode(params)}", status_code=303)


def _inspect_inbox(settings: Settings) -> tuple[Path, bool, list[ImportCandidate]]:
    """Inspect every course folder in the inbox; one bad folder never 500s."""

    inbox = Path(settings.courses_inbox_dir)
    try:
        if not inbox.is_dir():
            return inbox, False, []
        sources = discover_course_sources(inbox)
    except OSError:
        return inbox, False, []

    candidates: list[ImportCandidate] = []
    for source in sources:
        try:
            candidate = inspect_course(
                source, courses_root=Path(settings.courses_src_dir)
            )
        except Exception as exc:  # surface the problem on the page, never 500
            candidate = ImportCandidate(
                name=source.name,
                path=source,
                status="invalid",
                errors=[
                    CatalogError(
                        code="inspect_failed",
                        message=f"无法读取课程文件夹：{exc}",
                        slug=source.name,
                    )
                ],
            )
        candidates.append(candidate)
    return inbox, True, candidates


def _recent_imports(db: OrmSession) -> tuple[list[dict[str, Any]], bool]:
    """Return the provenance rows shaped for the template, or an empty list."""

    try:
        rows = list(list_imports(db, limit=MAX_RECENT_IMPORTS))
    except SQLAlchemyError:
        with contextlib.suppress(SQLAlchemyError):
            db.rollback()
        return [], False
    recent = [
        {
            "title": row.title,
            "slug": row.slug,
            "screens": row.screens,
            "source_path": row.source_path,
            "updated_label": format_timestamp(
                row.updated_at.isoformat() if row.updated_at else None
            ),
        }
        for row in rows
    ]
    return recent, True


def _import_options(settings: Settings) -> dict[str, Any]:
    return {
        "courses_root": Path(settings.courses_src_dir),
        "dist_root": Path(settings.courses_dist_dir),
        "runtime_dir": Path(settings.runtime_dir),
        "include_drafts": bool(settings.include_drafts),
        "site_url": settings.site_url,
        "site_title": settings.site_title,
        "course_base_url": settings.course_base_url,
        "progress_sync": True,
    }


def _result_error(result: ImportResult) -> str:
    if result.errors:
        return _short(result.errors[0].message)
    return "导入失败，请检查课程文件夹。"


def _record_provenance(db: OrmSession, result: ImportResult) -> bool:
    """Write one provenance row; a missing table must not undo the import."""

    try:
        record_import(db, result)
        db.commit()
    except SQLAlchemyError:
        with contextlib.suppress(SQLAlchemyError):
            db.rollback()
        return False
    return True


def _folder_problem(folder: str) -> str | None:
    if not folder:
        return "没有指定课程文件夹。"
    if folder in {".", ".."} or any(separator in folder for separator in PATH_SEPARATORS):
        return "课程文件夹必须是收件箱下的目录名，不能包含路径。"
    if Path(folder).name != folder:
        return "课程文件夹必须是收件箱下的目录名。"
    return None


# -- pages -----------------------------------------------------------------


@router.get("/import")
def import_page(request: Request, db: OrmSession = Depends(get_db)) -> Response:
    settings = _require_enabled(request)
    inbox, inbox_exists, candidates = _inspect_inbox(settings)
    recent, db_ready = _recent_imports(db)

    context = {
        "site": site_context(settings),
        "canonical": f"{settings.site_url.rstrip('/')}/import",
        "page": "import",
        "inbox": inbox,
        "inbox_display": _relative_label(inbox),
        "inbox_exists": inbox_exists,
        "candidates": candidates,
        "ready_count": sum(1 for candidate in candidates if candidate.status == "ready"),
        "recent": recent,
        "db_ready": db_ready,
        "imported": request.query_params.get("imported"),
        "error": request.query_params.get("error"),
        "include_drafts": bool(settings.include_drafts),
        "env": settings.env,
        "status_labels": STATUS_LABELS,
    }
    response = request.app.state.templates.TemplateResponse(
        request=request,
        name="import.html",
        context=context,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/import")
async def submit_import(
    request: Request, db: OrmSession = Depends(get_db)
) -> Response:
    settings = _require_enabled(request)
    _require_same_origin(request)

    body = await request.body()
    fields = parse_qs(body.decode("utf-8", errors="replace"))
    folder = (fields.get("folder") or [""])[0].strip()
    action = (fields.get("action") or [""])[0].strip()
    overwrite = (fields.get("overwrite") or [""])[0].strip() == "1"

    if action == "all":
        return _import_all(request, settings, db)
    return _import_one(request, settings, db, folder=folder, overwrite=overwrite)


def _import_one(
    request: Request,
    settings: Settings,
    db: OrmSession,
    *,
    folder: str,
    overwrite: bool,
) -> Response:
    problem = _folder_problem(folder)
    if problem:
        return _redirect(error=problem)

    inbox = Path(settings.courses_inbox_dir)
    try:
        inbox_root = inbox.resolve()
        candidate_path = (inbox / folder).resolve()
    except (OSError, ValueError):
        return _redirect(error="无法解析收件箱里的课程文件夹路径。")

    if candidate_path.parent != inbox_root:
        return _redirect(error="课程文件夹必须是收件箱下的目录名，不能包含路径。")
    if not candidate_path.is_dir():
        return _redirect(error=f"收件箱里没有 {folder}/ 这个文件夹。")
    if candidate_path.name.startswith((".", "_")):
        return _redirect(error="以点或下划线开头的文件夹不会被导入。")

    try:
        result = import_course(
            candidate_path, overwrite=overwrite, **_import_options(settings)
        )
    except Exception as exc:  # report the failure instead of raising a 500
        return _redirect(error=_short(f"导入时出现意外错误：{exc}"))

    if not result.ok:
        return _redirect(error=_result_error(result))

    _record_provenance(db, result)
    request.app.state.catalog_loader.invalidate()
    return _redirect(imported=result.slug)


def _import_all(request: Request, settings: Settings, db: OrmSession) -> Response:
    inbox = Path(settings.courses_inbox_dir)
    try:
        inbox_exists = inbox.is_dir()
    except OSError:
        inbox_exists = False
    if not inbox_exists:
        return _redirect(error=f"收件箱不存在：{_relative_label(inbox)}")

    _inbox, _exists, candidates = _inspect_inbox(settings)
    ready = [candidate for candidate in candidates if candidate.status == "ready"]
    if not ready:
        return _redirect(
            error="收件箱里没有可导入的课程。先修复校验不过的课程，或放入新的课程文件夹。"
        )

    options = _import_options(settings)
    imported: list[str] = []
    failures: list[str] = []
    for candidate in ready:
        try:
            result = import_course(candidate.path, overwrite=False, **options)
        except Exception as exc:  # one folder must not stop the batch
            failures.append(f"{candidate.slug or candidate.name}：{_short(f'意外错误：{exc}')}")
            continue
        if not result.ok:
            failures.append(f"{result.slug}：{_result_error(result)}")
            continue
        imported.append(result.slug)
        _record_provenance(db, result)

    if imported:
        request.app.state.catalog_loader.invalidate()

    if failures:
        message = f"批量导入：成功 {len(imported)} 门，失败 {len(failures)} 门"
        if imported:
            message += f"（已导入 {'、'.join(imported)}）"
        message += "。" + "；".join(failures)
        return _redirect(error=_short(message))

    return _redirect(imported=f"批量导入 {len(imported)} 门")
