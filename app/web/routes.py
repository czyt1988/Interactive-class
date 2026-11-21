"""Server-rendered site pages: home, library, about, sitemap and robots."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response

from app.catalog.models import Catalog, CourseSummary
from app.config import Settings

router = APIRouter()

LEVELS: tuple[tuple[str, str], ...] = (
    ("beginner", "入门"),
    ("intermediate", "进阶"),
    ("advanced", "高级"),
)
LEVEL_LABELS = dict(LEVELS)

SITE_DESCRIPTION = (
    "页间课堂是一个交互式视频课站点：课程像视频一样连续播放，"
    "翻开来是一页一页的动态幻灯片，每一页都能停。当前 AI Learning 系列讲 AI。"
)


def site_link(settings: Settings, path: str) -> str:
    """Prefix a root-absolute site path with the deployment's base path.

    A site published under ``/<repo>/`` (a GitHub Pages project page) cannot use
    ``/courses``: the browser resolves it to the domain root, outside the site.
    The base path is the only deployment-specific part; every template link goes
    through this helper so root deployments and sub-path deployments share one
    set of templates.
    """

    return f"{settings.site_base_path}{path}" if settings.site_base_path else path


def site_context(settings: Settings) -> dict[str, Any]:
    base = settings.site_base_path
    return {
        "title": settings.site_title,
        "url": f"{settings.site_url.rstrip('/')}{base}",
        "course_base_url": settings.course_base_url,
        "description": SITE_DESCRIPTION,
        "base_path": base,
        # Callable, not a string: templates ask for site.link("/courses") and the
        # current deployment decides the prefix once.
        "link": lambda path: site_link(settings, path),
        # The static export has no admin app and no progress API behind it.
        "admin": not settings.static_export,
        "static": settings.static_export,
    }


def _canonical(settings: Settings, path: str) -> str:
    return f"{settings.site_url.rstrip('/')}{settings.site_base_path}{path}"


def _absolute(settings: Settings, url: str) -> str:
    if url.startswith(("http://", "https://")):
        return url
    return f"{settings.site_url.rstrip('/')}{url}"


def _render(
    request: Request,
    template: str,
    *,
    canonical: str,
    page: str,
    **context: Any,
) -> HTMLResponse:
    settings: Settings = request.app.state.settings
    return request.app.state.templates.TemplateResponse(
        request=request,
        name=template,
        context={
            "site": site_context(settings),
            "canonical": canonical,
            "page": page,
            "levels": LEVELS,
            **context,
        },
    )


def _all_summaries(request: Request) -> list[CourseSummary]:
    settings: Settings = request.app.state.settings
    catalog: Catalog = request.app.state.catalog_loader.load(strict=False)
    return catalog.summaries(
        include_drafts=bool(settings.include_drafts),
        course_base_url=settings.course_base_url,
    )


@router.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    settings: Settings = request.app.state.settings
    courses = _all_summaries(request)
    return _render(
        request,
        "home.html",
        canonical=_canonical(settings, "/"),
        page="home",
        courses=courses,
    )


@router.get("/courses", response_class=HTMLResponse)
def library(request: Request, level: str | None = None, tag: str | None = None) -> HTMLResponse:
    settings: Settings = request.app.state.settings
    all_courses = _all_summaries(request)
    tags = sorted({tag_value for course in all_courses for tag_value in course.tags})

    selected_level = level if level in LEVEL_LABELS else None
    selected_tag = tag if tag in tags else None
    courses = [
        course
        for course in all_courses
        if (selected_level is None or course.level == selected_level)
        and (selected_tag is None or selected_tag in course.tags)
    ]

    return _render(
        request,
        "library.html",
        canonical=_canonical(settings, "/courses"),
        page="library",
        courses=courses,
        tags=tags,
        selected_level=selected_level,
        selected_tag=selected_tag,
    )


@router.get("/courses/")
def library_redirect(level: str | None = None, tag: str | None = None) -> RedirectResponse:
    query = {key: value for key, value in (("level", level), ("tag", tag)) if value}
    suffix = f"?{urlencode(query)}" if query else ""
    return RedirectResponse(url=f"/courses{suffix}", status_code=307)


@router.get("/about", response_class=HTMLResponse)
def about(request: Request) -> HTMLResponse:
    settings: Settings = request.app.state.settings
    return _render(
        request,
        "about.html",
        canonical=_canonical(settings, "/about"),
        page="about",
    )


@router.get("/sitemap.xml")
def sitemap(request: Request) -> Response:
    settings: Settings = request.app.state.settings
    base = f"{settings.site_url.rstrip('/')}{settings.site_base_path}"
    urls = [
        f"{base}/",
        f"{base}/courses",
        f"{base}/about",
        *[_absolute(settings, course.courseUrl) for course in _all_summaries(request)],
    ]
    items = "".join(f"<url><loc>{url}</loc></url>" for url in urls)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{items}</urlset>"
    )
    return Response(content=xml, media_type="application/xml")


@router.get("/robots.txt", response_class=PlainTextResponse)
def robots(request: Request) -> PlainTextResponse:
    settings: Settings = request.app.state.settings
    base = f"{settings.site_url.rstrip('/')}{settings.site_base_path}"
    return PlainTextResponse(
        "User-agent: *\n"
        "Allow: /\n"
        f"Disallow: {site_link(settings, '/admin')}\n"
        f"Sitemap: {base}/sitemap.xml\n"
    )
