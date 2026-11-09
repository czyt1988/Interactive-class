"""Admin settings page and the endpoints behind its video buttons.

The page is server-rendered: with JavaScript off it still lists courses and the
generate form works, showing the result after a refresh. The small script only
polls status and keeps the running state fresh.
"""

from __future__ import annotations

import hashlib
import os
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)

from app.catalog.models import Catalog, ResolvedCourse
from app.config import BASE_DIR, Settings
from app.formatting import format_bytes, format_duration, format_timestamp
from app.videos.manager import RenderBusy, RenderManager, RenderUnavailable
from app.videos.models import VideoStatus
from app.videos.toolchain import discover_toolchain
from app.web.routes import site_context

router = APIRouter(prefix="/admin", tags=["admin"])

ADMIN_COOKIE = "al_admin"
MAX_LOGIN_BODY_BYTES = 4096
QUALITY_LABELS = {"draft": "草稿", "looks": "标准", "delivery": "交付"}
NOTICES = {
    "auth": "请先输入管理密码。",
    "started": "已开始生成视频，页面会自动更新状态。",
    "busy": "已有视频正在生成，等它完成后再试。",
    "unready": "生成环境还没就绪，先看下面的检查结果补齐依赖。",
    "unavailable": "这门课暂时不能生成视频，请检查服务器上的课程包。",
    "notfound": "没有找到这门课。",
}


# -- request helpers -------------------------------------------------------


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _manager(request: Request) -> RenderManager:
    return request.app.state.video_manager


def _catalog(request: Request) -> Catalog:
    return request.app.state.catalog_loader.load(strict=False)


def _templates(request: Request) -> Any:
    return request.app.state.templates


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _authenticated(request: Request) -> bool:
    expected = _settings(request).admin_token
    if not expected:
        return True
    header = request.headers.get("x-admin-token")
    if header and secrets.compare_digest(header, expected):
        return True
    cookie = request.cookies.get(ADMIN_COOKIE)
    return bool(cookie and secrets.compare_digest(cookie, _token_digest(expected)))


def _require_same_origin(request: Request) -> None:
    """Reject cross-site form posts that would otherwise start heavy renders."""

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


def _no_store(response: Response) -> Response:
    response.headers["Cache-Control"] = "no-store"
    return response


def _base_context(request: Request, *, page: str = "admin") -> dict[str, Any]:
    settings = _settings(request)
    return {
        "site": site_context(settings),
        "canonical": f"{settings.site_url.rstrip('/')}/admin",
        "page": page,
    }


def _notice(request: Request) -> str | None:
    code = request.query_params.get("notice")
    return NOTICES.get(code or "")


def _display_dir(path: Path) -> str:
    try:
        return path.relative_to(BASE_DIR).as_posix()
    except ValueError:
        return "自定义目录"


def _output_dir_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".write-check-{os.getpid()}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _environment(request: Request) -> dict[str, Any]:
    settings = _settings(request)
    toolchain = discover_toolchain(settings)
    output_label = _display_dir(settings.video_output_dir)
    writable = _output_dir_writable(settings.video_output_dir)
    checks = [
        {"key": check.key, "label": check.label, "ok": check.ok, "detail": check.detail}
        for check in toolchain.checks
    ]
    return {
        "ready": toolchain.ready and writable,
        "checks": checks,
        "output_label": output_label,
        "output_writable": writable,
        "quality": settings.video_quality,
        "quality_label": QUALITY_LABELS.get(settings.video_quality, settings.video_quality),
    }


def _status_label(status: VideoStatus) -> tuple[str, str | None]:
    if status.state == "running":
        elapsed = status.job.elapsed_seconds if status.job else 0
        return "生成中", f"已用 {format_duration(elapsed)}"
    if status.state == "ready":
        return "已生成", None
    if status.state == "failed":
        return "生成失败", None
    return "未生成", None


def _row(course: ResolvedCourse, status: VideoStatus, *, busy: bool, ready: bool) -> dict[str, Any]:
    label, elapsed_label = _status_label(status)
    artifact = status.artifact
    running = status.state == "running"
    can_generate = ready and not running and not busy
    reason: str | None = None
    if not ready:
        reason = "生成环境未就绪，先按上面的检查补齐依赖。"
    elif busy and not running:
        reason = "已有视频正在生成，等它完成后再试。"
    render_count = 1 if artifact is not None else 0

    notes: list[str] = []
    if status.message:
        notes.append(status.message)
    if running and artifact is not None:
        notes.append("正在重新生成，当前可下载上一版视频。")
    if status.stale:
        notes.append("课程在上次构建后更新过，可以重新生成。")

    return {
        "slug": course.slug,
        "title": course.title,
        "screen_count": course.stats.screenCount,
        "duration_label": format_duration(course.stats.durationSeconds),
        "status": status.state,
        "status_label": label,
        "elapsed_label": elapsed_label,
        "render_label": "生成中" if running else ("重新生成" if render_count else "生成视频"),
        "can_generate": can_generate,
        "can_download": artifact is not None,
        "download_url": f"/admin/videos/{course.slug}/download",
        "render_url": f"/admin/videos/{course.slug}/render",
        "size_label": format_bytes(artifact.size_bytes) if artifact else None,
        "generated_label": format_timestamp(artifact.generated_at) if artifact else None,
        "note": " ".join(notes) or None,
        "reason": reason,
    }


def _rows(request: Request) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    environment = _environment(request)
    manager = _manager(request)
    busy = manager.is_busy()
    rows: list[dict[str, Any]] = []
    for course in _catalog(request).courses:
        status = manager.status(course.slug, content_hash=course.build.contentHash)
        row = _row(course, status, busy=busy, ready=bool(environment["ready"]))
        if manager.project_dir(course) is None and not row["reason"]:
            row["reason"] = "服务器上找不到这门课的 composition，不能生成。"
            row["can_generate"] = False
        rows.append(row)
    return rows, environment


# -- pages -----------------------------------------------------------------


def _login_page(request: Request, *, error: str | None, status_code: int) -> Response:
    context = {
        **_base_context(request),
        "error": error,
    }
    response = _templates(request).TemplateResponse(
        request=request,
        name="admin_login.html",
        context=context,
        status_code=status_code,
    )
    return _no_store(response)


@router.get("", response_class=HTMLResponse)
def admin_page(request: Request) -> Response:
    if not _authenticated(request):
        return _login_page(request, error=None, status_code=401)
    rows, environment = _rows(request)
    context = {
        **_base_context(request),
        "rows": rows,
        "environment": environment,
        "generated_count": sum(1 for row in rows if row["can_download"]),
        "busy": _manager(request).is_busy(),
        "admin_protected": bool(_settings(request).admin_token),
        "notice": _notice(request),
    }
    response = _templates(request).TemplateResponse(
        request=request,
        name="admin.html",
        context=context,
    )
    return _no_store(response)


@router.get("/", include_in_schema=False)
def admin_slash() -> RedirectResponse:
    return RedirectResponse("/admin", status_code=307)


@router.post("/login")
async def admin_login(request: Request) -> Response:
    settings = _settings(request)
    expected = settings.admin_token
    if not expected:
        return RedirectResponse("/admin", status_code=303)
    _require_same_origin(request)
    body = await request.body()
    if len(body) > MAX_LOGIN_BODY_BYTES:
        raise HTTPException(status_code=413, detail="请求体过大")
    fields = parse_qs(body.decode("utf-8", errors="replace"))
    provided = (fields.get("token") or [""])[0]
    if not provided or not secrets.compare_digest(provided, expected):
        return _login_page(request, error="管理密码不对。", status_code=401)
    response = RedirectResponse("/admin", status_code=303)
    response.set_cookie(
        ADMIN_COOKIE,
        _token_digest(expected),
        httponly=True,
        samesite="lax",
        secure=bool(settings.session_cookie_secure),
        path="/",
    )
    return _no_store(response)


# -- video actions ---------------------------------------------------------


@router.post("/videos/{slug}/render")
def start_render(slug: str, request: Request) -> Response:
    if not _authenticated(request):
        return _no_store(RedirectResponse("/admin?notice=auth", status_code=303))
    _require_same_origin(request)

    course = _catalog(request).by_slug(slug)
    if course is None:
        return _no_store(RedirectResponse("/admin?notice=notfound", status_code=303))
    if not discover_toolchain(_settings(request)).ready:
        return _no_store(RedirectResponse("/admin?notice=unready", status_code=303))
    try:
        _manager(request).start(course)
    except RenderBusy:
        return _no_store(RedirectResponse("/admin?notice=busy", status_code=303))
    except RenderUnavailable:
        return _no_store(RedirectResponse("/admin?notice=unavailable", status_code=303))
    return _no_store(RedirectResponse("/admin?notice=started", status_code=303))


@router.get("/videos/{slug}/download")
def download_video(slug: str, request: Request) -> Response:
    if not _authenticated(request):
        return _no_store(RedirectResponse("/admin?notice=auth", status_code=303))
    if _catalog(request).by_slug(slug) is None:
        raise HTTPException(status_code=404, detail="没有找到这门课")
    artifact = _manager(request).library.artifact(slug)
    if artifact is None:
        raise HTTPException(status_code=404, detail="视频还没有生成")
    return FileResponse(
        artifact.path,
        media_type="video/mp4",
        filename=f"{slug}.mp4",
        content_disposition_type="attachment",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/status")
def admin_status(request: Request) -> Response:
    if not _authenticated(request):
        return _no_store(
            JSONResponse(
                {"error": {"code": "unauthorized", "message": "需要管理密码", "details": {}}},
                status_code=401,
            )
        )
    manager = _manager(request)
    videos: dict[str, Any] = {}
    for course in _catalog(request).courses:
        status = manager.status(course.slug, content_hash=course.build.contentHash)
        artifact = status.artifact
        videos[course.slug] = {
            "state": status.state,
            "elapsedSeconds": (
                round(status.job.elapsed_seconds, 1)
                if status.state == "running" and status.job is not None
                else None
            ),
            "generatedAt": artifact.generated_at if artifact else None,
            "sizeBytes": artifact.size_bytes if artifact else None,
            "stale": status.stale,
            "message": status.message,
        }
    return _no_store(
        JSONResponse({"busy": manager.is_busy(), "videos": videos})
    )
