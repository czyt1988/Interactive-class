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
from starlette.concurrency import run_in_threadpool

from app.catalog import clip_store, watermark_store
from app.catalog import clips as clip_edit
from app.catalog import watermark as watermark_edit
from app.catalog.clips import ClipBuildError, ClipLibrary, build_context, clip_frame_html
from app.catalog.models import Catalog, ClipKind, ClipSelection, ResolvedCourse, WatermarkConfig
from app.catalog.watermark import (
    POSITION_FIELD_KEYS,
    POSITION_LABELS,
    POSITIONS,
    PREVIEW_TILES,
)
from app.config import BASE_DIR, Settings
from app.formatting import format_bytes, format_duration, format_timestamp
from app.videos.manager import RenderBusy, RenderManager, RenderUnavailable
from app.videos.models import VideoStatus
from app.videos.toolchain import discover_toolchain
from app.web.routes import site_context

router = APIRouter(prefix="/admin", tags=["admin"])

ADMIN_COOKIE = "al_admin"
MAX_LOGIN_BODY_BYTES = 4096
MAX_WATERMARK_BODY_BYTES = watermark_edit.MAX_FORM_BYTES
QUALITY_LABELS = {"draft": "草稿", "looks": "标准", "delivery": "交付"}
NOTICES = {
    "auth": "请先输入管理密码。",
    "started": "已开始生成视频，页面会自动更新状态。",
    "busy": "已有视频正在生成，等它完成后再试。",
    "unready": "生成环境还没就绪，先看下面的检查结果补齐依赖。",
    "unavailable": "这门课暂时不能生成视频，请检查服务器上的课程包。",
    "notfound": "没有找到这门课。",
}
WATERMARK_NOTICES = {
    "saved": "水印已保存，课程包已重新构建，刷新课程页即可看到。",
    "cleared": "水印已清除，课程包已重新构建。",
}
WATERMARK_SOURCE_HINT = (
    "这台机器上没有课程源文件 {path}，无法重新构建课程包。水印本身保存在站点数据库里、"
    "不写课程源文件，但构建需要课程源，请在持有课程源的机器上配置。"
)
WATERMARK_FORM_CONTENT_TYPE = "application/x-www-form-urlencoded"
WATERMARK_FORM_FIELDS = (
    {"action", "enabled"}
    | {
        f"corner_{key}_{field}"
        for key in POSITION_FIELD_KEYS.values()
        for field in ("text", "fontSize", "color", "opacity")
    }
    | {
        "repeat_text",
        "repeat_fontSize",
        "repeat_color",
        "repeat_opacity",
        "repeat_gapX",
        "repeat_gapY",
        "repeat_rotate",
    }
)

CLIP_NOTICES = {
    "saved": "片头片尾已保存，课程包已重新构建，刷新课程页即可看到。",
    "cleared": "片头片尾已清除，课程包已重新构建。",
}
CLIP_SOURCE_HINT = (
    "这台机器上没有课程源文件 {path}，无法重新构建课程包。片头/片尾配置保存在站点数据库里、"
    "不写课程源文件，但构建需要课程源，请在持有课程源的机器上配置。"
)
CLIP_FORM_CONTENT_TYPE = "application/x-www-form-urlencoded"
CLIP_FORM_FIELDS = {"action", "intro", "outro"}
MAX_CLIP_BODY_BYTES = 16 * 1024
CLIP_FRAME_CSP = (
    "default-src 'self'; "
    "img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline'; "
    "font-src 'self'; "
    "script-src 'self'; "
    "frame-ancestors 'self'"
)


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


def _base_context(
    request: Request, *, page: str = "admin", canonical: str | None = None
) -> dict[str, Any]:
    settings = _settings(request)
    return {
        "site": site_context(settings),
        "canonical": canonical or f"{settings.site_url.rstrip('/')}/admin",
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


def _clip_label(selection: ClipSelection | None) -> str:
    if selection is None or selection.is_empty:
        return "未配置片头片尾"
    if selection.intro and selection.outro:
        return "片头片尾已配置"
    return "片头已配置" if selection.intro else "片尾已配置"


def _row(
    course: ResolvedCourse,
    status: VideoStatus,
    *,
    busy: bool,
    ready: bool,
    watermark: WatermarkConfig | None,
    clips: ClipSelection | None,
) -> dict[str, Any]:
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
    if watermark is None:
        watermark_label = "未配置水印"
    elif watermark.enabled:
        watermark_label = "水印已配置"
    else:
        watermark_label = "水印已关闭"

    return {
        "slug": course.slug,
        "title": course.title,
        "screen_count": course.stats.screenCount,
        "duration_label": format_duration(course.stats.durationSeconds),
        "watermark_label": watermark_label,
        "watermark_url": f"/admin/courses/{course.slug}/watermark",
        "clips_label": _clip_label(clips),
        "clips_url": f"/admin/courses/{course.slug}/clips",
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
    settings = _settings(request)
    watermarks = watermark_store.load_all(settings)
    clip_configs = clip_store.load_all(settings)
    busy = manager.is_busy()
    rows: list[dict[str, Any]] = []
    for course in _catalog(request).courses:
        status = manager.status(course.slug, content_hash=course.build.contentHash)
        row = _row(
            course,
            status,
            busy=busy,
            ready=bool(environment["ready"]),
            watermark=watermarks.get(course.slug),
            clips=clip_configs.get(course.slug),
        )
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


# -- watermark config ------------------------------------------------------


def _watermark_url(slug: str) -> str:
    return f"/admin/courses/{slug}/watermark"


def _source_manifest(settings: Settings, slug: str) -> Path:
    return watermark_edit.manifest_path(settings, slug)


def _source_label(settings: Settings, slug: str) -> str:
    source = _source_manifest(settings, slug)
    try:
        return source.relative_to(BASE_DIR).as_posix()
    except ValueError:
        return f"自定义目录/{slug}/course.json"


def _source_available(settings: Settings, slug: str) -> bool:
    """Whether this machine can rebuild the bundle.

    The watermark itself comes from the database; the source tree is only needed
    because saving a watermark rebuilds the course bundle.
    """

    return _source_manifest(settings, slug).is_file()


def _decode_form(body: bytes) -> dict[str, list[str]]:
    return parse_qs(body.decode("utf-8", errors="replace"))


def _watermark_page(
    request: Request,
    course: ResolvedCourse,
    *,
    values: dict[str, Any] | None = None,
    errors: list[str] | None = None,
    status_code: int = 200,
) -> Response:
    settings = _settings(request)
    source_available = _source_available(settings, course.slug)
    problems = list(errors or [])

    if values is None:
        values = watermark_edit.form_values(
            watermark_store.load(settings, course.slug)
        )

    context = {
        **_base_context(
            request,
            canonical=f"{settings.site_url.rstrip('/')}{_watermark_url(course.slug)}",
        ),
        "course": course,
        "values": values,
        "positions": [
            {
                "value": position,
                "label": POSITION_LABELS[position],
                "key": POSITION_FIELD_KEYS[position],
            }
            for position in POSITIONS
        ],
        "preview_tiles": PREVIEW_TILES,
        "errors": problems,
        "notice": WATERMARK_NOTICES.get(request.query_params.get("notice") or ""),
        "source_available": source_available,
        "source_label": _source_label(settings, course.slug),
        "posted_url": _watermark_url(course.slug),
    }
    response = _templates(request).TemplateResponse(
        request=request,
        name="admin_watermark.html",
        context=context,
        status_code=status_code,
    )
    return _no_store(response)


@router.get("/courses/{slug}/watermark")
def watermark_page(slug: str, request: Request) -> Response:
    if not _authenticated(request):
        return _login_page(request, error=None, status_code=401)
    course = _catalog(request).by_slug(slug)
    if course is None:
        return _no_store(RedirectResponse("/admin?notice=notfound", status_code=303))
    return _watermark_page(request, course)


@router.post("/courses/{slug}/watermark")
async def save_watermark_page(slug: str, request: Request) -> Response:
    if not _authenticated(request):
        return _no_store(RedirectResponse("/admin?notice=auth", status_code=303))
    _require_same_origin(request)

    course = _catalog(request).by_slug(slug)
    if course is None:
        return _no_store(RedirectResponse("/admin?notice=notfound", status_code=303))

    settings = _settings(request)
    current = watermark_store.load(settings, slug)
    if not _source_available(settings, slug):
        return _watermark_page(
            request,
            course,
            values=watermark_edit.form_values(current),
            errors=[
                WATERMARK_SOURCE_HINT.format(path=_source_label(settings, slug))
            ],
            status_code=409,
        )

    content_type = (
        request.headers.get("content-type", "").split(";")[0].strip().lower()
    )
    if content_type != WATERMARK_FORM_CONTENT_TYPE:
        return _watermark_page(
            request,
            course,
            values=watermark_edit.form_values(current),
            errors=["水印配置只接受表单提交，水印没有改动。"],
            status_code=415,
        )

    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            declared_length = int(declared)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Content-Length 不合法") from exc
        if declared_length > MAX_WATERMARK_BODY_BYTES:
            raise HTTPException(status_code=413, detail="请求体过大")

    body = await request.body()
    if len(body) > MAX_WATERMARK_BODY_BYTES:
        raise HTTPException(status_code=413, detail="请求体过大")
    fields = _decode_form(body)
    if not set(fields) & WATERMARK_FORM_FIELDS:
        return _watermark_page(
            request,
            course,
            values=watermark_edit.form_values(current),
            errors=["表单内容为空或字段无法识别，水印没有改动。"],
            status_code=400,
        )

    action = (fields.get("action") or [""])[0].strip()
    if action not in {"save", "clear"}:
        return _watermark_page(
            request,
            course,
            values=watermark_edit.form_values_from_request(fields),
            errors=["表单动作无法识别，水印没有改动。"],
            status_code=400,
        )

    if action == "clear":
        watermark = None
    else:
        watermark, errors = watermark_edit.parse_form(fields)
        if errors:
            return _watermark_page(
                request,
                course,
                values=watermark_edit.form_values_from_request(fields),
                errors=errors,
                status_code=422,
            )

    try:
        result = await run_in_threadpool(
            watermark_edit.apply_watermark, settings, slug, watermark
        )
    except Exception as exc:  # noqa: BLE001 - report the failure on the page
        return _watermark_page(
            request,
            course,
            values=watermark_edit.form_values(watermark),
            errors=[f"保存或重新构建课程包时出现意外错误：{exc}"],
            status_code=500,
        )

    request.app.state.catalog_loader.invalidate()

    if getattr(result, "skipped", False):
        return _watermark_page(
            request,
            course,
            values=watermark_edit.form_values(watermark),
            errors=[
                "水印已保存到数据库，但课程是草稿，构建被跳过。"
                "把 status 改成 published 后重新保存。"
            ],
            status_code=422,
        )
    build_errors = watermark_edit.build_error_messages(result)
    if build_errors:
        return _watermark_page(
            request,
            course,
            values=watermark_edit.form_values(watermark),
            errors=[
                "水印已保存到数据库，但重新构建课程包失败，修好后重新保存：",
                *build_errors,
            ],
            status_code=422,
        )

    notice = "cleared" if action == "clear" or watermark is None else "saved"
    return _no_store(
        RedirectResponse(f"{_watermark_url(slug)}?notice={notice}", status_code=303)
    )


# -- intro / outro clips ---------------------------------------------------


def _clips_url(slug: str) -> str:
    return f"/admin/courses/{slug}/clips"


def _course_page_url(settings: Settings, slug: str) -> str:
    base = settings.course_base_url.rstrip("/")
    if base.startswith(("http://", "https://")):
        return f"{base}/{slug}/"
    return f"{settings.site_url.rstrip('/')}{base}/{slug}/"


def _clip_library(settings: Settings) -> ClipLibrary:
    return ClipLibrary(Path(settings.clips_dir))


def _clip_values(selection: ClipSelection | None) -> dict[str, str]:
    return {
        "intro": (selection.intro or "") if selection else "",
        "outro": (selection.outro or "") if selection else "",
    }


def _first_field(fields: dict[str, list[str]], key: str) -> str:
    values = fields.get(key) or [""]
    return values[0].strip()


def _parse_clip_form(
    fields: dict[str, list[str]], library: ClipLibrary
) -> tuple[ClipSelection | None, dict[str, str], list[str]]:
    """Turn the two radio values into a validated selection."""

    values = {
        "intro": _first_field(fields, "intro"),
        "outro": _first_field(fields, "outro"),
    }
    errors: list[str] = []
    for slot, label in (("intro", "片头"), ("outro", "片尾")):
        clip_id = values[slot]
        if not clip_id:
            continue
        clip = library.get(clip_id)
        if clip is None:
            errors.append(f"找不到{label}模板 {clip_id!r}，刷新页面后重试。")
        elif clip.kind != slot:
            errors.append(f"{label}位置不能使用 {clip.kind} 类型的模板 {clip_id!r}。")
    if errors:
        return None, values, errors
    try:
        selection = ClipSelection(
            intro=values["intro"] or None, outro=values["outro"] or None
        )
    except ValueError as exc:  # pydantic ValidationError is a ValueError
        return None, values, [f"片头/片尾 id 不合法：{exc}"]
    return selection, values, []


def _clip_choices(
    library: ClipLibrary, kind: ClipKind, *, course_slug: str
) -> list[dict[str, Any]]:
    choices: list[dict[str, Any]] = []
    for clip in library.for_kind(kind):
        choices.append(
            {
                "id": clip.id,
                "title": clip.title,
                "summary": clip.summary,
                "description": clip.description,
                "duration": f"{clip.duration:g}",
                "frame_url": f"/admin/clips/{clip.id}/frame?course={course_slug}",
            }
        )
    return choices


def _clips_page(
    request: Request,
    course: ResolvedCourse,
    *,
    values: dict[str, str] | None = None,
    errors: list[str] | None = None,
    status_code: int = 200,
) -> Response:
    settings = _settings(request)
    library = _clip_library(settings)
    selection = clip_store.load(settings, course.slug)
    problems = list(errors or [])
    if values is None:
        values = _clip_values(selection)

    current_intro = library.get(selection.intro) if selection and selection.intro else None
    current_outro = library.get(selection.outro) if selection and selection.outro else None
    for clip_id, label, defined in (
        (selection.intro if selection else None, "片头", current_intro),
        (selection.outro if selection else None, "片尾", current_outro),
    ):
        if clip_id and defined is None:
            problems.append(
                f"已配置的{label} {clip_id!r} 在 clips/ 里找不到：补齐模板或重选一个。"
            )

    context = {
        **_base_context(
            request,
            canonical=f"{settings.site_url.rstrip('/')}{_clips_url(course.slug)}",
        ),
        "course": course,
        "values": values,
        "intro_clips": _clip_choices(library, "intro", course_slug=course.slug),
        "outro_clips": _clip_choices(library, "outro", course_slug=course.slug),
        "current": {
            "intro": current_intro,
            "outro": current_outro,
            "intro_id": selection.intro if selection else None,
            "outro_id": selection.outro if selection else None,
            "intro_frame": (
                f"/admin/clips/{current_intro.id}/frame?course={course.slug}"
                if current_intro
                else None
            ),
            "outro_frame": (
                f"/admin/clips/{current_outro.id}/frame?course={course.slug}"
                if current_outro
                else None
            ),
        },
        "library_issues": [
            {"code": issue.code, "message": issue.message, "clip_id": issue.clip_id}
            for issue in library.issues()
        ],
        "errors": problems,
        "notice": CLIP_NOTICES.get(request.query_params.get("notice") or ""),
        "source_available": _source_available(settings, course.slug),
        "source_label": _source_label(settings, course.slug),
        "posted_url": _clips_url(course.slug),
    }
    response = _templates(request).TemplateResponse(
        request=request,
        name="admin_clips.html",
        context=context,
        status_code=status_code,
    )
    return _no_store(response)


@router.get("/courses/{slug}/clips")
def clips_page(slug: str, request: Request) -> Response:
    if not _authenticated(request):
        return _login_page(request, error=None, status_code=401)
    course = _catalog(request).by_slug(slug)
    if course is None:
        return _no_store(RedirectResponse("/admin?notice=notfound", status_code=303))
    return _clips_page(request, course)


@router.post("/courses/{slug}/clips")
async def save_clips_page(slug: str, request: Request) -> Response:
    if not _authenticated(request):
        return _no_store(RedirectResponse("/admin?notice=auth", status_code=303))
    _require_same_origin(request)

    course = _catalog(request).by_slug(slug)
    if course is None:
        return _no_store(RedirectResponse("/admin?notice=notfound", status_code=303))

    settings = _settings(request)
    library = _clip_library(settings)
    selection = clip_store.load(settings, course.slug)
    if not _source_available(settings, slug):
        return _clips_page(
            request,
            course,
            values=_clip_values(selection),
            errors=[CLIP_SOURCE_HINT.format(path=_source_label(settings, slug))],
            status_code=409,
        )

    content_type = (
        request.headers.get("content-type", "").split(";")[0].strip().lower()
    )
    if content_type != CLIP_FORM_CONTENT_TYPE:
        return _clips_page(
            request,
            course,
            values=_clip_values(selection),
            errors=["片头片尾只接受表单提交，设置没有改动。"],
            status_code=415,
        )

    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            declared_length = int(declared)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Content-Length 不合法") from exc
        if declared_length > MAX_CLIP_BODY_BYTES:
            raise HTTPException(status_code=413, detail="请求体过大")

    body = await request.body()
    if len(body) > MAX_CLIP_BODY_BYTES:
        raise HTTPException(status_code=413, detail="请求体过大")
    fields = _decode_form(body)
    if not set(fields) & CLIP_FORM_FIELDS:
        return _clips_page(
            request,
            course,
            values=_clip_values(selection),
            errors=["表单内容为空或字段无法识别，设置没有改动。"],
            status_code=400,
        )

    action = _first_field(fields, "action")
    if action not in {"save", "clear"}:
        return _clips_page(
            request,
            course,
            values=_clip_values(selection),
            errors=["表单动作无法识别，设置没有改动。"],
            status_code=400,
        )

    if action == "clear":
        selection = None
        values = {"intro": "", "outro": ""}
    else:
        selection, values, errors = _parse_clip_form(fields, library)
        if errors or selection is None:
            return _clips_page(
                request,
                course,
                values=values,
                errors=errors or ["片头/片尾设置不合法，没有保存。"],
                status_code=422,
            )

    try:
        result = await run_in_threadpool(
            clip_edit.apply_selection, settings, slug, selection
        )
    except Exception as exc:  # noqa: BLE001 - report the failure on the page
        return _clips_page(
            request,
            course,
            values=values,
            errors=[f"保存或重新构建课程包时出现意外错误：{exc}"],
            status_code=500,
        )

    request.app.state.catalog_loader.invalidate()

    if getattr(result, "skipped", False):
        return _clips_page(
            request,
            course,
            values=values,
            errors=[
                "片头/片尾已保存到数据库，但课程是草稿，构建被跳过。"
                "把 status 改成 published 后重新保存。"
            ],
            status_code=422,
        )
    build_errors = watermark_edit.build_error_messages(result)
    if build_errors:
        return _clips_page(
            request,
            course,
            values=values,
            errors=[
                "片头/片尾已保存到数据库，但重新构建课程包失败，修好后重新保存：",
                *build_errors,
            ],
            status_code=422,
        )

    notice = "cleared" if action == "clear" or selection is None else "saved"
    return _no_store(
        RedirectResponse(f"{_clips_url(slug)}?notice={notice}", status_code=303)
    )


@router.get("/clips/{clip_id}/frame")
def clip_frame(clip_id: str, request: Request, course: str | None = None) -> Response:
    """One still of a clip's final frame, rendered for this course.

    The preview runs the clip's CSS layout and a tiny local script that scales
    the 1920×1080 surface into the iframe; it never boots the player or the clip
    timeline. It is only reachable from the authenticated admin page, so the
    response gets its own CSP: inline styles for the scene, one same-origin
    script, no images or fonts from anywhere else.
    """

    if not _authenticated(request):
        return _login_page(request, error=None, status_code=401)
    settings = _settings(request)
    library = _clip_library(settings)
    clip = library.get(clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="没有找到这个片头/片尾模板")
    target = _catalog(request).by_slug(course or "")
    if target is None:
        raise HTTPException(status_code=404, detail="没有找到这门课")
    context = build_context(
        target,
        site_title=settings.site_title,
        project_url=settings.project_url,
        course_url=_course_page_url(settings, target.slug),
    )
    source = library.scene_path(clip).read_text(encoding="utf-8")
    try:
        html = clip_frame_html(clip, source, context)
    except ClipBuildError as exc:
        raise HTTPException(
            status_code=500, detail=exc.errors[0].message if exc.errors else "预览失败"
        ) from exc
    return _no_store(
        HTMLResponse(
            html,
            headers={
                "Content-Security-Policy": CLIP_FRAME_CSP,
                "X-Robots-Tag": "noindex",
            },
        )
    )


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
