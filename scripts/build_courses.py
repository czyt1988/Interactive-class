"""Course build pipeline.

Source ``courses/<slug>/`` -> resolved manifest + static bundle in
``dist/courses/<slug>/``. This script is the only entry point allowed to turn
sources into bundles; ``dist/`` is never edited by hand.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
# 把仓库根放进 sys.path：同一个 .venv 可能被多个 git worktree 共享
# （见 scripts/worktree.py），否则 `python scripts/build_courses.py` 在
# 工作树里会经由 editable install 导入主工作树的 app。
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jinja2 import Environment, FileSystemLoader, select_autoescape  # noqa: E402

from app.catalog.assets import scan_composition  # noqa: E402
from app.catalog.models import CatalogError, ResolvedCourse  # noqa: E402
from app.catalog.resolver import CourseResolutionError, resolve_course  # noqa: E402

DEFAULT_SOURCE = ROOT / "courses"
DEFAULT_OUT = ROOT / "dist" / "courses"
DEFAULT_RUNTIME = ROOT / "runtime"

SKIP_COMPOSITION = {
    "node_modules",
    ".hyperframes",
    ".thumbnails",
    "renders",
    "package.json",
    "hyperframes.json",
    ".DS_Store",
    "Thumbs.db",
}
# Per-run authoring caches, also ignored by .gitignore. Their names carry a
# suffix (``.snaps-s19-v2``, ``.review-2026-11``), so they need a prefix check
# instead of an exact set entry.
SKIP_COMPOSITION_PREFIXES = (".snaps-", ".review-")
SKIP_SUFFIXES = {".mp4", ".map"}

MAX_COURSE_BYTES = 15 * 1024 * 1024
MAX_HTML_BYTES = 200 * 1024
MAX_IMAGE_BYTES = 500 * 1024
MAX_COVER_BYTES = 300 * 1024

# ``runtime/shell.html.j2`` declares one face, "Noto Sans SC", so the shell has
# to register the same file the composition uses. The font folder also holds
# faces such as JetBrains Mono; taking the alphabetically first ``.woff2``
# would register a mono subset under the Noto name and push the whole cover,
# control bar and transcript into system-font fallback.
SHELL_FONT_NAME = "NotoSansSC-VF.woff2"

LEVEL_LABELS = {"beginner": "入门", "intermediate": "进阶", "advanced": "高级"}


def level_label(level: str) -> str:
    return LEVEL_LABELS.get(level, level)


def shell_font_url(composition_dir: Path) -> str | None:
    """Font file the shell injects, relative to the built course page.

    Prefer the Noto subset the contract names; fall back to any ``.woff2`` so a
    course that ships a differently named face still gets a local font.
    """

    font_dir = composition_dir / "assets" / "fonts"
    if not font_dir.is_dir():
        return None
    preferred = font_dir / SHELL_FONT_NAME
    chosen = preferred if preferred.is_file() else next(iter(sorted(font_dir.glob("*.woff2"))), None)
    return f"./composition/assets/fonts/{chosen.name}" if chosen else None



def _skip_composition_name(name: str) -> bool:
    return name in SKIP_COMPOSITION or name.startswith(SKIP_COMPOSITION_PREFIXES)


@dataclass
class BuildResult:
    slug: str
    output_dir: Path
    screens: int = 0
    duration: float = 0
    content_hash: str = ""
    skipped: bool = False
    errors: list[CatalogError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and not self.skipped


class BuildError(Exception):
    def __init__(self, errors: list[CatalogError]) -> None:
        self.errors = errors
        super().__init__(f"{len(errors)} 个构建错误")


def _error(
    code: str,
    message: str,
    *,
    slug: str | None,
    file: str | Path | None = None,
    screen_id: str | None = None,
    field_name: str | None = None,
    expected: str | None = None,
) -> CatalogError:
    return CatalogError(
        code=code,
        message=message,
        slug=slug,
        file=str(file) if file is not None else None,
        screen_id=screen_id,
        field=field_name,
        expected=expected,
    )


def _iter_composition_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(root).parts
        if any(_skip_composition_name(part) for part in relative_parts):
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        files.append(path)
    return files


def content_hash(course_dir: Path, course: ResolvedCourse) -> str:
    digest = hashlib.sha256()
    candidates: list[Path] = [course_dir / "course.json"]
    composition = course_dir / "composition"
    candidates.extend(_iter_composition_files(composition))
    if course.cover:
        candidates.append(course_dir / course.cover)
    for path in sorted(set(candidates)):
        if not path.is_file():
            continue
        digest.update(path.relative_to(course_dir).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _validate_assets(course_dir: Path, course: ResolvedCourse) -> list[CatalogError]:
    errors: list[CatalogError] = []
    composition = course_dir / "composition"
    for issue in scan_composition(composition):
        errors.append(
            _error(
                issue.code,
                issue.message,
                slug=course.slug,
                file=issue.file,
                screen_id=issue.screen_id,
                field_name=issue.field,
                expected="课程包内部的相对路径",
            )
        )

    gsap = composition / "assets" / "vendor" / "gsap.min.js"
    if not gsap.is_file():
        errors.append(
            _error(
                "vendor_missing",
                "composition/assets/vendor/gsap.min.js 不存在",
                slug=course.slug,
                file=gsap,
                field_name="gsap",
                expected="运行 python scripts/sync_runtime.py",
            )
        )

    total = 0
    for path in _iter_composition_files(composition):
        size = path.stat().st_size
        total += size
        suffix = path.suffix.lower()
        if suffix in {".html", ".htm"} and size > MAX_HTML_BYTES:
            errors.append(
                _error(
                    "asset_budget_exceeded",
                    f"单个 HTML 文件 {size} 字节，超过 {MAX_HTML_BYTES} 字节",
                    slug=course.slug,
                    file=path,
                    field_name="size",
                    expected=f"<= {MAX_HTML_BYTES}",
                )
            )
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".avif"} and size > MAX_IMAGE_BYTES:
            errors.append(
                _error(
                    "asset_budget_exceeded",
                    f"图片 {size} 字节，超过 {MAX_IMAGE_BYTES} 字节",
                    slug=course.slug,
                    file=path,
                    field_name="size",
                    expected=f"<= {MAX_IMAGE_BYTES}",
                )
            )
    if total > MAX_COURSE_BYTES:
        errors.append(
            _error(
                "asset_budget_exceeded",
                f"课程 composition 总计 {total} 字节，超过 {MAX_COURSE_BYTES} 字节",
                slug=course.slug,
                file=composition,
                field_name="totalSize",
                expected=f"<= {MAX_COURSE_BYTES}",
            )
        )

    if course.cover:
        cover = course_dir / course.cover
        if cover.is_file() and cover.stat().st_size > MAX_COVER_BYTES:
            errors.append(
                _error(
                    "asset_budget_exceeded",
                    f"封面 {cover.stat().st_size} 字节，超过 {MAX_COVER_BYTES} 字节",
                    slug=course.slug,
                    file=cover,
                    field_name="cover",
                    expected=f"<= {MAX_COVER_BYTES}",
                )
            )
    return errors


def _copy_composition(source: Path, target: Path) -> None:
    def ignore(_directory: str, names: list[str]) -> set[str]:
        ignored: set[str] = set()
        for name in names:
            if _skip_composition_name(name) or Path(name).suffix.lower() in SKIP_SUFFIXES:
                ignored.add(name)
        return ignored

    shutil.copytree(source, target, ignore=ignore)


def _copy_runtime(runtime_dir: Path, target: Path) -> None:
    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {
            name
            for name in names
            if name in {"shell.html.j2", "__pycache__"} or name.endswith(".pyc")
        }

    shutil.copytree(runtime_dir, target, ignore=ignore)


def _site_origin(site_url: str) -> str:
    parts = urlsplit(site_url)
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}"


def course_url(course_base_url: str, site_url: str, slug: str) -> str:
    base = course_base_url.rstrip("/")
    if base.startswith(("http://", "https://")):
        return f"{base}/{slug}/"
    return f"{site_url.rstrip('/')}{base}/{slug}/"


def _render_shell(
    *,
    course: ResolvedCourse,
    runtime_dir: Path,
    build_hash: str,
    site_url: str,
    site_title: str,
    course_base_url: str,
    progress_sync: bool,
    output: Path,
    runtime_version: str,
    font_url: str | None,
) -> None:
    env = Environment(
        loader=FileSystemLoader(str(runtime_dir)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    def mmss(seconds: float) -> str:
        total = max(0, round(seconds))
        return f"{total // 60}:{total % 60:02d}"

    env.globals["mmss"] = mmss
    env.globals["level_label"] = level_label
    template = env.get_template("shell.html.j2")

    course_data = course.model_dump()
    manifest_json = json.dumps(course_data, ensure_ascii=False).replace("</", "<\\/")
    origin = _site_origin(site_url)
    progress = None
    if progress_sync and origin:
        progress = {"endpoint": "/api/progress", "origin": origin}

    cover_url = f"./{course.cover}" if course.cover else None
    home_url = course.site.homeUrl
    html = template.render(
        course=course_data,
        screens=course_data["screens"],
        site={
            "title": site_title,
            "homeUrl": home_url,
            "backLabel": course.site.backLabel,
        },
        theme={
            "accent": course.accent or "#E4572E",
            "coverUrl": cover_url,
            "fontUrl": font_url,
        },
        progress=progress,
        build={
            "hash": build_hash,
            "runtimeVersion": runtime_version,
            "courseUrl": course_url(course_base_url, site_url, course.slug),
        },
        manifest_json=manifest_json,
        asset_query=f"?v={build_hash[:10]}",
    )
    (output / "index.html").write_text(html, encoding="utf-8")


def build_course(
    course_dir: Path,
    *,
    out_root: Path,
    runtime_dir: Path = DEFAULT_RUNTIME,
    include_drafts: bool = False,
    check_only: bool = False,
    site_url: str = "http://127.0.0.1:8000",
    site_title: str = "AI Learning",
    course_base_url: str = "/courses",
    progress_sync: bool = True,
) -> BuildResult:
    course_dir = course_dir.resolve()
    slug = course_dir.name
    try:
        course = resolve_course(course_dir)
    except CourseResolutionError as exc:
        return BuildResult(slug=slug, output_dir=out_root / slug, errors=exc.errors)

    if course.status != "published" and not include_drafts:
        return BuildResult(slug=slug, output_dir=out_root / slug, skipped=True)

    errors = _validate_assets(course_dir, course)
    if errors:
        return BuildResult(slug=slug, output_dir=out_root / slug, errors=errors)

    digest = content_hash(course_dir, course)
    result = BuildResult(
        slug=slug,
        output_dir=out_root / slug,
        screens=len(course.screens),
        duration=course.composition.duration,
        content_hash=digest,
    )
    if check_only:
        return result

    out_root.mkdir(parents=True, exist_ok=True)
    runtime_version = "0.9.19"
    version_path = runtime_dir / "VERSION.json"
    if version_path.is_file():
        with contextlib.suppress(json.JSONDecodeError):
            runtime_version = json.loads(version_path.read_text(encoding="utf-8")).get(
                "hyperframes", runtime_version
            )

    staging = Path(tempfile.mkdtemp(prefix=f".build-{slug}-", dir=str(out_root)))
    target = out_root / slug
    try:
        _copy_composition(course_dir / "composition", staging / "composition")
        font_url = shell_font_url(staging / "composition")
        _copy_runtime(runtime_dir, staging / "runtime")
        if course.cover:
            shutil.copy2(course_dir / course.cover, staging / course.cover)

        payload = course.model_dump()
        payload["build"] = {
            "runtimeVersion": runtime_version,
            "contentHash": digest,
            "builtAt": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        (staging / "course.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _render_shell(
            course=course,
            runtime_dir=runtime_dir,
            build_hash=digest,
            site_url=site_url,
            site_title=site_title,
            course_base_url=course_base_url,
            progress_sync=progress_sync,
            output=staging,
            runtime_version=runtime_version,
            font_url=font_url,
        )
        if target.exists():
            shutil.rmtree(target)
        staging.rename(target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return result


def validate_course_source(
    course_dir: Path, *, slug: str | None = None
) -> tuple[ResolvedCourse | None, list[CatalogError]]:
    """Resolve ``course_dir`` and validate its assets without writing anything.

    ``slug`` lets importers validate an external folder whose directory name is
    not the manifest slug yet (the imported course will live under
    ``courses/<slug>``). Returns ``(course, [])`` on success, ``(None, errors)``
    otherwise. The errors keep file, field, screen id and expected value, same as
    the build pipeline.
    """

    resolved_dir = course_dir.resolve()
    try:
        course = resolve_course(resolved_dir, slug=slug)
    except CourseResolutionError as exc:
        return None, exc.errors
    errors = _validate_assets(resolved_dir, course)
    if errors:
        return None, errors
    return course, []


def discover_courses(source_root: Path) -> list[Path]:
    if not source_root.is_dir():
        return []
    return sorted(
        path
        for path in source_root.iterdir()
        if path.is_dir() and not path.name.startswith(("_", "."))
    )


def build_all(
    *,
    source_root: Path,
    out_root: Path,
    courses: list[str] | None = None,
    include_drafts: bool = False,
    check_only: bool = False,
    runtime_dir: Path = DEFAULT_RUNTIME,
    site_url: str = "http://127.0.0.1:8000",
    site_title: str = "AI Learning",
    course_base_url: str = "/courses",
    progress_sync: bool = True,
) -> list[BuildResult]:
    selected = set(courses or [])
    results: list[BuildResult] = []
    for course_dir in discover_courses(source_root):
        if selected and course_dir.name not in selected:
            continue
        results.append(
            build_course(
                course_dir,
                out_root=out_root,
                runtime_dir=runtime_dir,
                include_drafts=include_drafts,
                check_only=check_only,
                site_url=site_url,
                site_title=site_title,
                course_base_url=course_base_url,
                progress_sync=progress_sync,
            )
        )

    if not check_only:
        manifest = {
            "builtAt": datetime.now(UTC).isoformat(timespec="seconds"),
            "courses": [
                {
                    "slug": result.slug,
                    "screens": result.screens,
                    "durationSeconds": result.duration,
                    "contentHash": result.content_hash,
                }
                for result in results
                if result.ok
            ],
        }
        out_root.parent.mkdir(parents=True, exist_ok=True)
        (out_root.parent / "build.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return results


def _print_result(result: BuildResult) -> None:
    if result.skipped:
        print(f"skip  {result.slug}  (draft; use --include-drafts)")
        return
    if result.errors:
        print(f"FAIL  {result.slug}")
        for error in result.errors:
            location = ":".join(
                part
                for part in (error.file, error.field, error.screen_id, error.code)
                if part
            )
            print(f"      [{location}] {error.message}")
            if error.expected:
                print(f"      期望：{error.expected}")
        return
    print(
        f"ok    {result.slug}  {result.screens} 屏 / {result.duration:g}s  -> {result.output_dir}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="构建 AI Learning 课程包")
    parser.add_argument("--course", action="append", default=None, help="只构建指定 slug，可重复")
    parser.add_argument("--all", action="store_true", help="构建全部已发布课程")
    parser.add_argument("--check-only", action="store_true", help="只校验，不写产物")
    parser.add_argument("--include-drafts", action="store_true", help="同时构建 draft 课程")
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--site-url", default="http://127.0.0.1:8000")
    parser.add_argument("--site-title", default="AI Learning")
    parser.add_argument("--course-base-url", default="/courses")
    parser.add_argument("--no-progress-sync", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    courses = args.course
    if not courses and not args.all and args.source_dir.resolve() == DEFAULT_SOURCE.resolve():
        args.all = True
    if not courses and not args.all:
        parser.error("需要 --course <slug> 或 --all")

    results = build_all(
        source_root=args.source_dir,
        out_root=args.out_dir,
        courses=courses,
        include_drafts=args.include_drafts,
        check_only=args.check_only,
        runtime_dir=args.runtime_dir,
        site_url=args.site_url,
        site_title=args.site_title,
        course_base_url=args.course_base_url,
        progress_sync=not args.no_progress_sync,
    )
    if not results:
        print("没有找到可构建的课程", file=sys.stderr)
        return 1
    if not args.quiet:
        for result in results:
            _print_result(result)
    failed = [result for result in results if result.errors]
    if failed:
        print(f"\n构建失败：{len(failed)} 门课程", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
