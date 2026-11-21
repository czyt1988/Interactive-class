"""Export the site as a static directory that GitHub Pages (or any file host) can serve.

The site normally runs on FastAPI: the cover pages are rendered per request,
progress and the admin are backed by SQLite, and the courses are static bundles
under ``dist/courses``. GitHub Pages only serves files, so publishing needs a
third artifact: the same pages rendered once, next to the same course bundles.

This script is the only entry point for that artifact:

1. build every published course into ``<output>/courses/`` (no progress API and
   no watermark; intro/outro clips come from the committed
   ``deploy/publish.json``, because the private ``course_clips`` table is not
   available to CI);
2. render ``/``, ``/courses``, ``/about``, the 404 page, the sitemap and robots
   with the real FastAPI app, so the static copy cannot drift from the dynamic
   one;
3. copy the site's static assets and write ``.nojekyll``;
4. verify every internal reference resolves to an exported file.

The output is a plain directory: upload it anywhere. GitHub Actions does this on
every push to ``main`` and deploys it to Pages (``.github/workflows/pages.yml``).

Run with: ``python scripts/export_site.py --site-url https://<user>.github.io --base-path /<repo>``
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from textwrap import dedent
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
# Same reason as build_courses.py: a shared .venv across git worktrees must not
# make ``import app`` resolve to the main worktree's checkout.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from app.catalog.clips import ClipLibrary  # noqa: E402
from app.catalog.models import SLUG_PATTERN, ClipSelection  # noqa: E402
from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from scripts.build_courses import DEFAULT_CLIPS, build_all  # noqa: E402

DEFAULT_OUTPUT = ROOT / "dist" / "site"
DEFAULT_SITE_SOURCE = ROOT / "courses"
DEFAULT_STATIC_DIR = ROOT / "app" / "static"
DEFAULT_RUNTIME_DIR = ROOT / "runtime"
DEFAULT_PUBLISH_CONFIG = ROOT / "deploy" / "publish.json"

# Route -> file in the export. Directory-style files keep GitHub Pages' existing
# redirect behaviour working: it serves ``/courses/`` from ``courses/index.html``
# and 301-redirects ``/courses`` to it.
PAGE_ROUTES: tuple[tuple[str, str], ...] = (
    ("/", "index.html"),
    ("/courses", "courses/index.html"),
    ("/about", "about/index.html"),
)
TEXT_ROUTES: tuple[tuple[str, str], ...] = (
    ("/sitemap.xml", "sitemap.xml"),
    ("/robots.txt", "robots.txt"),
)
NOT_FOUND_PROBE = "/__static_export_not_found__"

# References a browser resolves elsewhere or inline; no file has to exist.
EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "data:", "javascript:", "//")
# Attributes that can point at a file we ship.
REFERENCE_ATTRIBUTES = frozenset({"href", "src", "poster"})


class ExportError(Exception):
    """A publish failure with the concrete problems the operator has to fix."""

    def __init__(self, message: str, problems: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.message = message
        self.problems = list(problems)


@dataclass(frozen=True)
class ExportReport:
    output: Path
    site_url: str
    base_path: str
    courses: int
    screens: int
    pages: int
    files: int


def normalise_base_path(value: str) -> str:
    """Validate and normalise ``--base-path`` (``""`` or ``/repo``)."""

    path = value.strip().rstrip("/")
    if not path:
        return ""
    if not path.startswith("/") or path.startswith("//") or ".." in path.split("/") or "//" in path:
        raise ExportError(f"站点子路径不合法：{value!r}（应形如 /repo）")
    return path


def load_publish_clips(path: Path | None) -> dict[str, ClipSelection]:
    """Read the committed clip selection for the published site.

    The admin stores clip choices in SQLite because they are deployment
    configuration. CI has no access to that database, so a published site takes
    its selection from ``deploy/publish.json`` instead. A missing file means
    "publish without intro/outro", not an error.
    """

    if path is None or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ExportError(f"发布配置 {path} 无法读取：{exc}") from exc
    if not isinstance(payload, dict):
        raise ExportError(f"发布配置 {path} 必须是 JSON 对象")

    unknown = sorted(set(payload) - {"clips"})
    if unknown:
        raise ExportError(f"发布配置 {path} 有未知字段：{', '.join(unknown)}")

    raw_clips = payload.get("clips", {})
    if not isinstance(raw_clips, dict):
        raise ExportError(f"发布配置 {path} 的 clips 必须是对象，键为课程 slug")
    selections: dict[str, ClipSelection] = {}
    for slug, raw in raw_clips.items():
        if not isinstance(slug, str) or not SLUG_PATTERN.fullmatch(slug):
            raise ExportError(f"发布配置 {path} 里的课程 slug 不合法：{slug!r}")
        try:
            selection = ClipSelection.model_validate(raw)
        except ValidationError as exc:
            raise ExportError(f"发布配置 {path} 里 {slug} 的片头/片尾不合法：{exc}") from exc
        if not selection.is_empty:
            selections[slug] = selection
    return selections


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


class _ReferenceParser(HTMLParser):
    """Collect the file references of one HTML document."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value for name, value in attrs}
        for name, value in attrs:
            if name in REFERENCE_ATTRIBUTES and value:
                self.references.append(value)
        # Social previews are the one reference that lives in a meta tag.
        if tag == "meta" and values.get("property") in {"og:image", "og:url"}:
            content = values.get("content")
            if content:
                self.references.append(content)


def exported_pages(output: Path) -> list[Path]:
    """HTML documents whose links must resolve inside the export."""

    pages = [output / relative for _, relative in PAGE_ROUTES]
    pages.append(output / "404.html")
    pages.extend(sorted(output.glob("courses/*/index.html")))
    return [page for page in pages if page.is_file()]


def resolve_reference(reference: str, page: Path, output: Path, base_path: str) -> Path | str | None:
    """Map a document reference to a file in the export.

    Returns the target path, a problem description, or ``None`` when the browser
    resolves the reference elsewhere (absolute URL, fragment, inline data).
    """

    reference = reference.strip()
    if not reference or reference.startswith("#"):
        return None
    lowered = reference.lower()
    if lowered.startswith(EXTERNAL_PREFIXES):
        return None
    parts = urlsplit(reference)
    path = unquote(parts.path)
    if not path:
        return None

    if path.startswith("/"):
        if base_path:
            if path == base_path:
                path = "/"
            elif path.startswith(base_path + "/"):
                path = path[len(base_path) :]
            else:
                return "站内链接没有带站点子路径前缀"
        candidate = (output / path.lstrip("/")).resolve()
    else:
        candidate = (page.parent / path).resolve()

    try:
        candidate.relative_to(output.resolve())
    except ValueError:
        return "引用跑到了发布目录之外"

    if path.endswith("/") or candidate.is_dir():
        return candidate / "index.html"
    if candidate.suffix:
        return candidate
    nested = candidate / "index.html"
    return nested if nested.is_file() else candidate


def check_output(output: Path, *, site_url: str, base_path: str) -> list[str]:
    """Every internal reference, sitemap URL and robots hint must point at the export."""

    problems: list[str] = []
    for page in exported_pages(output):
        relative = page.relative_to(output).as_posix()
        text = page.read_text(encoding="utf-8")
        if "127.0.0.1" in text or "localhost" in text:
            problems.append(f"{relative}：产物里还有本机地址（检查 --site-url）")
        if "/api/progress" in text:
            problems.append(f"{relative}：课程页还在调用 /api/progress（静态发布没有这个接口）")

        parser = _ReferenceParser()
        parser.feed(text)
        for reference in parser.references:
            target = resolve_reference(reference, page, output, base_path)
            if target is None:
                continue
            if isinstance(target, str):
                problems.append(f"{relative} 的 {reference!r}：{target}")
            elif not target.is_file():
                problems.append(f"{relative} 的 {reference!r} 指向不存在的文件")

    site_root = f"{site_url.rstrip('/')}{base_path}"
    sitemap_path = output / "sitemap.xml"
    if sitemap_path.is_file():
        sitemap = sitemap_path.read_text(encoding="utf-8")
        if f"<loc>{site_root}/</loc>" not in sitemap:
            problems.append("sitemap.xml：首页地址和 --site-url / --base-path 不一致")
    else:
        problems.append("sitemap.xml：没有导出")

    robots_path = output / "robots.txt"
    if robots_path.is_file():
        robots = robots_path.read_text(encoding="utf-8")
        if f"Sitemap: {site_root}/sitemap.xml" not in robots:
            problems.append("robots.txt：Sitemap 地址和 --site-url / --base-path 不一致")
    else:
        problems.append("robots.txt：没有导出")
    return problems


def export_site(
    *,
    site_url: str,
    output: Path = DEFAULT_OUTPUT,
    base_path: str = "",
    publish_config: Path | None = DEFAULT_PUBLISH_CONFIG,
    source_root: Path = DEFAULT_SITE_SOURCE,
    runtime_dir: Path = DEFAULT_RUNTIME_DIR,
    clips_dir: Path = DEFAULT_CLIPS,
    static_dir: Path = DEFAULT_STATIC_DIR,
    project_url: str | None = None,
    courses: Sequence[str] | None = None,
) -> ExportReport:
    """Build the course bundles, render the site pages and verify the result."""

    base_path = normalise_base_path(base_path)
    site_url = site_url.strip().rstrip("/")
    if not site_url.startswith(("http://", "https://")):
        raise ExportError(f"--site-url 必须是 http/https 地址：{site_url!r}")

    clips = load_publish_clips(publish_config)

    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    courses_dir = output / "courses"

    settings = Settings(
        env="prod",
        site_url=site_url,
        site_base_path=base_path,
        static_export=True,
        courses_src_dir=source_root,
        courses_dist_dir=courses_dir,
        runtime_dir=runtime_dir,
        clips_dir=clips_dir,
        # Nothing in an export reads or writes the site database; an in-memory
        # one keeps CI from creating data/ by accident.
        database_url="sqlite://",
        video_output_dir=output.parent / ".export-videos",
        video_work_dir=output.parent / ".export-videos" / ".work",
    )

    results = build_all(
        source_root=source_root,
        out_root=courses_dir,
        courses=list(courses) if courses else None,
        include_drafts=False,
        runtime_dir=runtime_dir,
        site_url=site_url,
        site_title=settings.site_title,
        course_base_url=settings.course_base_url,
        base_path=base_path,
        progress_sync=False,
        watermarks={},
        clips=clips,
        clip_library=ClipLibrary(clips_dir),
        project_url=project_url or settings.project_url,
    )
    failed = [result for result in results if result.errors]
    if failed:
        problems = [
            f"{error.code}: {error.message}"
            for result in failed
            for error in result.errors
        ]
        raise ExportError("课程构建失败，不能发布", problems)
    built = [result for result in results if result.ok]

    app = create_app(settings)
    with TestClient(app) as client:
        for route, relative in PAGE_ROUTES:
            response = client.get(route)
            if response.status_code != 200:
                raise ExportError(f"渲染 {route} 失败：HTTP {response.status_code}")
            _write_text(output / relative, response.text)
        for route, relative in TEXT_ROUTES:
            response = client.get(route)
            if response.status_code != 200:
                raise ExportError(f"渲染 {route} 失败：HTTP {response.status_code}")
            _write_text(output / relative, response.text)
        not_found = client.get(NOT_FOUND_PROBE)
        if not_found.status_code != 404:
            raise ExportError(f"渲染 404 页面失败：HTTP {not_found.status_code}")
        _write_text(output / "404.html", not_found.text)

    shutil.copytree(static_dir, output / "static")
    # Branch-based Pages runs Jekyll and would rewrite or drop parts of the
    # bundle; the Actions artifact path does not. Writing the marker keeps the
    # same directory valid for both hosting modes.
    _write_text(output / ".nojekyll", "")

    problems = check_output(output, site_url=site_url, base_path=base_path)
    if problems:
        raise ExportError("静态发布检查失败", problems)

    files = sum(1 for path in output.rglob("*") if path.is_file())
    return ExportReport(
        output=output,
        site_url=site_url,
        base_path=base_path,
        courses=len(built),
        screens=sum(result.screens for result in built),
        pages=len(PAGE_ROUTES) + 1,
        files=files,
    )


def _print_report(report: ExportReport) -> None:
    print(f"导出完成：{report.output}")
    print(f"  站点地址  {report.site_url}{report.base_path}/")
    print(f"  课程      {report.courses} 门 / {report.screens} 屏")
    print(f"  页面      {report.pages} 个（含 404）")
    print(f"  文件      {report.files} 个")
    if report.base_path:
        print(f"  子路径    {report.base_path}（GitHub Pages 项目页）")


def _print_error(error: ExportError) -> None:
    print(f"发布失败：{error.message}", file=sys.stderr)
    for problem in error.problems:
        print(f"  - {problem}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="导出可直接托管在 GitHub Pages 的静态站点",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=dedent(
            """\
            例子：
              python scripts/export_site.py --site-url https://czyt1988.github.io --base-path /interactive-class
              python scripts/export_site.py --site-url https://learn.example.com --base-path ""
            """
        ),
    )
    parser.add_argument("--site-url", required=True, help="站点 origin，例如 https://czyt1988.github.io")
    parser.add_argument(
        "--base-path",
        default="",
        help="站点子路径，GitHub Pages 项目页形如 /interactive-class；根域名部署留空",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--publish-config",
        type=Path,
        default=DEFAULT_PUBLISH_CONFIG,
        help="静态发布的片头/片尾配置（默认 deploy/publish.json）",
    )
    parser.add_argument(
        "--no-publish-config",
        action="store_true",
        help="忽略发布配置，构建不带片头/片尾的课程",
    )
    parser.add_argument("--project-url", default=None, help="片头里印的开源项目地址")
    parser.add_argument("--course", action="append", default=None, help="只导出指定 slug，可重复")
    args = parser.parse_args(argv)

    try:
        report = export_site(
            site_url=args.site_url,
            output=args.output.resolve(),
            base_path=args.base_path,
            publish_config=None if args.no_publish_config else args.publish_config,
            project_url=args.project_url,
            courses=args.course,
        )
    except ExportError as exc:
        _print_error(exc)
        return 1
    _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
