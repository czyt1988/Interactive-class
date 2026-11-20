"""Import externally authored course folders into ``courses/``.

The pipeline is a thin wrapper around the build pipeline, and it keeps the same
architecture: course content stays in files, the site catalog keeps reading only
``dist/``, and SQLite only records provenance (see ``app.models.CourseImport``).

Order of operations for an external folder:

1. parse ``course.json`` and resolve + validate the whole course (assets too);
2. copy into a hidden staging directory inside ``courses/`` (``.import-*``),
   skipping authoring/tooling output and video/log files;
3. build the bundle from the staging copy so ``dist/`` gets its own atomic
   replace only after validation passes;
4. rename the staging course to ``courses/<slug>``, moving any previous copy to
   a backup first so a failed rename restores the old course;
5. delete the staging directory.

Any failure rolls back the staging copy; if the attempt already replaced
``dist/<slug>`` (only a successful build does that), that bundle is removed too
so the catalog can never serve a course that is not in ``courses/``.

Importing only depends on the app layer and the standard library. ``scripts`` is
imported lazily inside the functions that build, because the production image
ships only the ``app`` package: author tooling (``scripts/``) is not installed
there, and the import page that needs it is dev-only.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog.models import CatalogError, ResolvedCourse
from app.models import CourseImport

# Slugs that mean "the author forgot to rename the template". A real course may
# legitimately be named ``demo-course``, so only template placeholders are here.
RESERVED_SLUGS = {"_template", "template", "course-template", "your-course-slug"}

ImportStatus = Literal["ready", "invalid", "exists"]

# Authoring/tooling output and stray OS files never belong in a course folder.
EXCLUDED_NAMES = {
    ".git",
    "node_modules",
    ".hyperframes",
    "renders",
    "__pycache__",
    ".ds_store",
    "thumbs.db",
}
# Video and log files are local review output, not course assets. Audio is
# deliberately *not* excluded: narration is part of the shipped course.
EXCLUDED_SUFFIXES = {".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v", ".flv", ".wmv", ".log"}

DRAFT_WARNING = "草稿未构建：把 course.json 的 status 改成 published，或用 --include-drafts 重新导入。"


def _error(
    code: str,
    message: str,
    *,
    slug: str | None,
    file: str | Path | None = None,
    screen_id: str | None = None,
    field: str | None = None,
    expected: str | None = None,
) -> CatalogError:
    return CatalogError(
        code=code,
        message=message,
        slug=slug,
        file=str(file) if file is not None else None,
        screen_id=screen_id,
        field=field,
        expected=expected,
    )


def _build_tools():  # noqa: ANN202 - returns two callables from the lazy import
    """Import the author tooling lazily.

    The production image only installs the ``app`` package, so a module-level
    ``from scripts.build_courses import ...`` would make importing this module
    (and therefore the site) depend on author tooling being installed.
    """

    from scripts.build_courses import build_course, validate_course_source

    return build_course, validate_course_source


@dataclass
class ImportCandidate:
    """One discovered course folder, as shown before an import starts."""

    name: str
    path: Path
    status: ImportStatus
    slug: str | None = None
    title: str | None = None
    screens: int | None = None
    duration: float | None = None
    errors: list[CatalogError] = field(default_factory=list)


@dataclass
class ImportResult:
    """Outcome of one ``import_course`` call."""

    slug: str
    title: str
    source: Path
    ok: bool = False
    copied: bool = False
    built: bool = False
    was_existing: bool = False
    output_dir: Path | None = None
    screens: int = 0
    duration: float = 0.0
    content_hash: str = ""
    source_hash: str = ""
    errors: list[CatalogError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def discover_course_sources(root: Path) -> list[Path]:
    """Find course folders under ``root``.

    ``root`` may itself be a course folder (it has ``course.json``); otherwise
    its direct children are checked. Hidden and underscore-prefixed directories
    are skipped so ``.import-*`` staging and ``_template`` never become courses.
    """

    root = Path(root)
    if not root.is_dir():
        return []
    root = root.resolve()
    if (root / "course.json").is_file():
        return [root]
    return sorted(
        path
        for path in root.iterdir()
        if path.is_dir()
        and not path.name.startswith((".", "_"))
        and (path / "course.json").is_file()
    )


def _read_manifest(
    source_dir: Path,
) -> tuple[dict[str, object] | None, list[CatalogError]]:
    """Read ``course.json`` as a best-effort object; the resolver does the rest."""

    manifest_path = source_dir / "course.json"
    try:
        raw_bytes = manifest_path.read_bytes()
    except OSError as exc:
        return None, [
            _error(
                "manifest_invalid",
                f"找不到或无法读取 course.json：{exc}",
                slug=source_dir.name,
                file=manifest_path,
                expected="课程文件夹根目录的 course.json",
            )
        ]
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, [
            _error(
                "manifest_invalid",
                f"course.json 不是合法 JSON：{exc}",
                slug=source_dir.name,
                file=manifest_path,
                expected="合法 JSON 对象",
            )
        ]
    if not isinstance(payload, dict):
        return None, [
            _error(
                "manifest_invalid",
                "course.json 顶层必须是对象",
                slug=source_dir.name,
                file=manifest_path,
                expected="JSON object",
            )
        ]
    return payload, []


def _manifest_slug(payload: dict[str, object] | None) -> tuple[str | None, str | None]:
    slug: str | None = None
    title: str | None = None
    if payload is not None:
        raw_slug = payload.get("slug")
        if isinstance(raw_slug, str) and raw_slug.strip():
            slug = raw_slug.strip()
        raw_title = payload.get("title")
        if isinstance(raw_title, str) and raw_title.strip():
            title = raw_title.strip()
    return slug or None, title


def _reserved_slug_error(slug: str, source_dir: Path) -> CatalogError:
    return _error(
        "slug_reserved",
        f"slug={slug!r} 是模板占位符或保留名；把 course.json 的 slug 改成课程自己的小写连字符 slug",
        slug=slug,
        file=source_dir / "course.json",
        field="slug",
        expected="课程自己的 slug，例如 what-is-a-token",
    )


def _symlink_errors(source_dir: Path) -> list[CatalogError]:
    """Reject symlinks that point outside the course folder.

    A copied tree must not silently pull in files from the rest of the disk. The
    check is best effort: it walks the source tree without following links and
    only flags links whose resolved target leaves the folder. Tooling
    directories are pruned because they are excluded from the copy anyway.
    """

    root = source_dir.resolve()
    errors: list[CatalogError] = []
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name.lower() not in EXCLUDED_NAMES]
        for name in (*dirnames, *filenames):
            path = Path(current) / name
            if not path.is_symlink():
                continue
            try:
                target = path.resolve()
            except OSError as exc:
                errors.append(
                    _error(
                        "import_failed",
                        f"符号链接无法解析：{path}（{exc}）",
                        slug=root.name,
                        file=path,
                        expected="普通文件/目录，或指向课程文件夹内部的链接",
                    )
                )
                continue
            try:
                target.relative_to(root)
            except ValueError:
                errors.append(
                    _error(
                        "import_failed",
                        f"课程文件夹包含指向目录外的符号链接：{path} -> {target}",
                        slug=root.name,
                        file=path,
                        expected="课程文件夹内部的相对目标",
                    )
                )
                continue
            if not target.exists():
                errors.append(
                    _error(
                        "import_failed",
                        f"符号链接指向不存在的目标：{path} -> {target}",
                        slug=root.name,
                        file=path,
                        expected="存在的相对路径",
                    )
                )
    return errors


def _inspect_source(
    source_dir: Path, courses_root: Path
) -> tuple[ImportCandidate, ResolvedCourse | None]:
    """Return the candidate and, when it resolves, the ``ResolvedCourse``."""

    source_dir = source_dir.resolve()
    payload, errors = _read_manifest(source_dir)
    manifest_slug, title = _manifest_slug(payload)
    slug = manifest_slug or source_dir.name

    resolved: ResolvedCourse | None = None
    if payload is not None:
        _build, validate_course_source = _build_tools()
        resolved, validation_errors = validate_course_source(source_dir, slug=manifest_slug)
        errors.extend(validation_errors)
        if resolved is not None:
            title = resolved.title

    errors.extend(_symlink_errors(source_dir))

    if slug in RESERVED_SLUGS:
        errors.append(_reserved_slug_error(slug, source_dir))

    if errors:
        status: ImportStatus = "invalid"
    elif (courses_root / slug).exists():
        status = "exists"
    else:
        status = "ready"

    screens = resolved.stats.screenCount if resolved is not None else None
    duration = resolved.composition.duration if resolved is not None else None
    candidate = ImportCandidate(
        name=source_dir.name,
        path=source_dir,
        status=status,
        slug=slug,
        title=title,
        screens=screens,
        duration=duration,
        errors=errors,
    )
    return candidate, resolved


def inspect_course(source_dir: Path, *, courses_root: Path) -> ImportCandidate:
    """Validate one course folder without writing anything.

    The candidate status is ``invalid`` (errors on it), ``exists`` (the target
    ``courses/<slug>`` already exists) or ``ready``. ``overwrite`` does not
    affect this; the caller decides which button to offer.
    """

    candidate, _resolved = _inspect_source(Path(source_dir), Path(courses_root))
    return candidate


def _sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return os.path.normcase(str(left.absolute())) == os.path.normcase(str(right.absolute()))


def _remove_tree(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        with contextlib.suppress(OSError):
            path.unlink()
    elif path.is_dir():
        shutil.rmtree(path, ignore_errors=True)


def _copy_ignore(_directory: str, names: list[str]) -> set[str]:
    return {
        name
        for name in names
        if name.lower() in EXCLUDED_NAMES or Path(name).suffix.lower() in EXCLUDED_SUFFIXES
    }


def _remap_errors(
    errors: list[CatalogError], staged_course: Path, target: Path
) -> list[CatalogError]:
    """Point build errors at the final ``courses/<slug>`` path, not the staging copy."""

    staged_root = staged_course.resolve()
    remapped: list[CatalogError] = []
    for error in errors:
        if error.file:
            try:
                relative = Path(error.file).resolve().relative_to(staged_root)
            except (OSError, ValueError):
                pass
            else:
                error = error.model_copy(update={"file": str(target / relative)})
        remapped.append(error)
    return remapped


def _apply_build_result(
    result: ImportResult, build_result, *, fallback_output: Path
) -> None:
    if build_result.errors:
        result.errors = list(build_result.errors)
        result.ok = False
        return
    if build_result.skipped:
        result.warnings.append(DRAFT_WARNING)
        result.ok = True
        return
    result.built = True
    result.output_dir = build_result.output_dir or fallback_output
    result.screens = build_result.screens
    result.duration = build_result.duration
    result.content_hash = build_result.content_hash
    result.ok = True


def import_course(
    source_dir: Path,
    *,
    courses_root: Path,
    dist_root: Path,
    runtime_dir: Path,
    overwrite: bool = False,
    dry_run: bool = False,
    build: bool = True,
    include_drafts: bool = True,
    site_url: str = "http://127.0.0.1:8000",
    site_title: str = "页间课堂",
    course_base_url: str = "/courses",
    progress_sync: bool = True,
) -> ImportResult:
    """Validate, copy, build and record one course folder.

    Two modes:

    - ``source_dir`` is already ``courses/<slug>``: rebuild in place (``copied``
      stays ``False``); the manifest slug must equal the directory name.
    - any other folder: copy to hidden staging inside ``courses/``, build there,
      then atomically move it to ``courses/<slug>`` (with a backup + rollback
      when the target exists and ``overwrite=True``).

    ``dry_run`` validates only. ``build=False`` copies without building. A draft
    course with ``include_drafts=False`` is copied but not built, and gets a
    warning instead of an error.
    """

    source_dir = Path(source_dir).resolve()
    courses_root = Path(courses_root).resolve()
    dist_root = Path(dist_root).resolve()
    runtime_dir = Path(runtime_dir).resolve()

    candidate, resolved = _inspect_source(source_dir, courses_root)
    slug = candidate.slug or source_dir.name
    result = ImportResult(
        slug=slug,
        title=candidate.title or slug,
        source=source_dir,
        was_existing=(courses_root / slug).exists(),
        screens=candidate.screens or 0,
        duration=candidate.duration or 0.0,
        source_hash=_sha256_file(source_dir / "course.json"),
        errors=list(candidate.errors),
    )
    if result.errors:
        return result

    if resolved is None:  # defensive: validate_course_source returned a course on success
        result.errors = [
            _error(
                "import_failed",
                "课程校验通过但解析结果为空，导入中止",
                slug=slug,
                file=source_dir,
                expected="可解析的课程",
            )
        ]
        return result

    result.title = resolved.title
    result.screens = resolved.stats.screenCount
    result.duration = resolved.composition.duration
    target = courses_root / slug

    if dry_run:
        result.ok = True
        return result

    in_place = target.exists() and _same_path(target, source_dir)
    if in_place:
        return _rebuild_in_place(
            result,
            source_dir=source_dir,
            dist_root=dist_root,
            runtime_dir=runtime_dir,
            build=build,
            include_drafts=include_drafts,
            site_url=site_url,
            site_title=site_title,
            course_base_url=course_base_url,
            progress_sync=progress_sync,
        )

    if target.exists() and not overwrite:
        result.errors = [
            _error(
                "course_exists",
                f"courses/{slug}/ 已存在；确认覆盖请加 --overwrite（或换一个 slug）",
                slug=slug,
                file=target,
                expected="不存在的目标目录，或 --overwrite",
            )
        ]
        return result

    return _import_external(
        result,
        source_dir=source_dir,
        target=target,
        courses_root=courses_root,
        dist_root=dist_root,
        runtime_dir=runtime_dir,
        build=build,
        include_drafts=include_drafts,
        site_url=site_url,
        site_title=site_title,
        course_base_url=course_base_url,
        progress_sync=progress_sync,
    )


def _rebuild_in_place(
    result: ImportResult,
    *,
    source_dir: Path,
    dist_root: Path,
    runtime_dir: Path,
    build: bool,
    include_drafts: bool,
    site_url: str,
    site_title: str,
    course_base_url: str,
    progress_sync: bool,
) -> ImportResult:
    """Rebuild a course that already lives in ``courses/<slug>``."""

    result.was_existing = True
    build_course, validate_course_source = _build_tools()
    _resolved, errors = validate_course_source(source_dir, slug=None)
    if errors:
        result.errors = errors
        return result
    if not build:
        result.warnings.append("未构建：--no-build 只校验，现有课程目录和 dist 保持不变。")
        result.ok = True
        return result

    try:
        build_result = build_course(
            source_dir,
            out_root=dist_root,
            runtime_dir=runtime_dir,
            include_drafts=include_drafts,
            site_url=site_url,
            site_title=site_title,
            course_base_url=course_base_url,
            progress_sync=progress_sync,
        )
    except Exception as exc:  # noqa: BLE001 - surface any build crash as an import error
        result.errors = [
            _error(
                "import_failed",
                f"原地重建失败：{exc}",
                slug=result.slug,
                file=source_dir,
                expected="可构建的课程文件夹",
            )
        ]
        return result

    _apply_build_result(result, build_result, fallback_output=dist_root / result.slug)
    return result


def _import_external(
    result: ImportResult,
    *,
    source_dir: Path,
    target: Path,
    courses_root: Path,
    dist_root: Path,
    runtime_dir: Path,
    build: bool,
    include_drafts: bool,
    site_url: str,
    site_title: str,
    course_base_url: str,
    progress_sync: bool,
) -> ImportResult:
    """Copy to hidden staging, build, then atomically move into ``courses/``."""

    build_course, _validate = _build_tools()
    slug = result.slug
    dist_slug = dist_root / slug

    try:
        courses_root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".import-", dir=str(courses_root)))
    except OSError as exc:
        result.errors = [
            _error(
                "import_failed",
                f"无法创建导入临时目录：{exc}",
                slug=slug,
                file=courses_root,
                expected="可写的 courses 目录",
            )
        ]
        return result

    staged_course = staging / slug
    keep_staging = False
    try:
        try:
            shutil.copytree(source_dir, staged_course, ignore=_copy_ignore)
        except (OSError, shutil.Error) as exc:
            # No dist cleanup: build_course replaces dist atomically, so nothing
            # of this attempt exists in dist/ yet; the previous bundle (if any)
            # still matches the course directory that is still in place.
            result.errors = [
                _error(
                    "import_failed",
                    f"复制课程文件夹失败：{exc}",
                    slug=slug,
                    file=source_dir,
                    expected="可读取的课程文件夹",
                )
            ]
            return result

        if build:
            try:
                build_result = build_course(
                    staged_course,
                    out_root=dist_root,
                    runtime_dir=runtime_dir,
                    include_drafts=include_drafts,
                    site_url=site_url,
                    site_title=site_title,
                    course_base_url=course_base_url,
                    progress_sync=progress_sync,
                )
            except Exception as exc:  # noqa: BLE001 - surface any build crash as an import error
                result.errors = [
                    _error(
                        "import_failed",
                        f"构建失败：{exc}",
                        slug=slug,
                        file=target,
                        expected="可构建的课程文件夹",
                    )
                ]
                return result
            if build_result.errors:
                result.errors = _remap_errors(build_result.errors, staged_course, target)
                return result
            _apply_build_result(result, build_result, fallback_output=dist_slug)

        built_now = result.built
        # Only now touch the real courses/ tree. The backup lives inside the
        # staging directory so the whole rollback area disappears at the end.
        backup = staging / f".backup-{slug}"
        try:
            if target.exists():
                target.rename(backup)
            staged_course.rename(target)
        except OSError as exc:
            if backup.exists() and not target.exists():
                with contextlib.suppress(OSError):
                    backup.rename(target)
            keep_staging = backup.exists()
            message = f"无法把课程移动到 courses/{slug}/：{exc}"
            if keep_staging:
                message += f"；旧课程备份保留在 {backup}，可手动恢复"
            result.built = False
            result.copied = False
            result.output_dir = None
            result.errors = [
                _error(
                    "import_failed",
                    message,
                    slug=slug,
                    file=target,
                    expected="可写的 courses 目录",
                )
            ]
            if built_now:
                # This attempt replaced dist/<slug> with a bundle whose source is
                # not in courses/ now; drop it so the catalog cannot serve it.
                _remove_tree(dist_slug)
            return result

        result.copied = True
        result.ok = True
        if not build:
            if result.was_existing:
                # The source folder was replaced without a new bundle: the old
                # dist is now stale, so drop it rather than let the catalog serve
                # content that does not match courses/<slug>/.
                _remove_tree(dist_slug)
                result.warnings.append(
                    "未构建：旧的课程包已移除，需要重新构建才会出现在站点。"
                )
            else:
                result.warnings.append("未构建：--no-build 只复制课程文件夹，dist 未生成。")
        return result
    finally:
        if not keep_staging:
            shutil.rmtree(staging, ignore_errors=True)


def record_import(db: Session, result: ImportResult) -> None:
    """Upsert one provenance row by slug. The caller commits."""

    record = db.execute(
        select(CourseImport).where(CourseImport.slug == result.slug)
    ).scalar_one_or_none()
    if record is None:
        record = CourseImport(slug=result.slug)
        db.add(record)
    record.title = result.title or result.slug
    record.source_path = str(result.source)
    record.source_hash = result.source_hash
    record.content_hash = result.content_hash
    record.screens = result.screens
    record.duration_seconds = result.duration


def list_imports(db: Session, limit: int = 12) -> list[CourseImport]:
    """Most recently imported courses first."""

    rows = db.scalars(
        select(CourseImport)
        .order_by(CourseImport.updated_at.desc(), CourseImport.id.desc())
        .limit(max(1, limit))
    )
    return list(rows)
