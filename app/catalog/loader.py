"""Load resolved manifests from ``dist/courses``.

The web process never reads ``courses/`` sources and never parses composition
HTML. It only reads the manifests written by the build, so a broken course
source cannot slow down or crash the site. Invalid courses are reported and
excluded unless the caller runs in strict mode.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from pydantic import ValidationError

from app.catalog.models import Catalog, CatalogError, CatalogStats, ResolvedCourse

logger = logging.getLogger(__name__)


class CatalogLoadError(Exception):
    def __init__(self, errors: list[CatalogError]) -> None:
        self.errors = errors
        super().__init__(f"课程目录加载失败（{len(errors)} 个错误）")


def _error(code: str, message: str, *, slug: str | None, file: str | None) -> CatalogError:
    return CatalogError(code=code, message=message, slug=slug, file=file)


class CatalogLoader:
    """Scan and cache resolved manifests.

    The cache signature uses manifest mtimes/sizes plus directory mtimes, so a
    completed build is visible on the next request without a process restart.
    """

    def __init__(self, dist_dir: Path, *, verify_bundles: bool = True) -> None:
        self.dist_dir = dist_dir
        self.verify_bundles = verify_bundles
        self._lock = threading.Lock()
        self._signature: tuple[tuple[str, int, int], ...] | None = None
        self._catalog: Catalog | None = None

    def load(self, *, strict: bool = False) -> Catalog:
        with self._lock:
            signature = self._build_signature()
            if self._catalog is not None and signature == self._signature:
                catalog = self._catalog
            else:
                catalog = self._scan()
                self._catalog = catalog
                self._signature = signature
            if strict and catalog.errors:
                raise CatalogLoadError(catalog.errors)
            return catalog

    def invalidate(self) -> None:
        with self._lock:
            self._catalog = None
            self._signature = None

    def _build_signature(self) -> tuple[tuple[str, int, int], ...]:
        entries: list[tuple[str, int, int]] = []
        if not self.dist_dir.is_dir():
            return tuple()
        root_stat = self.dist_dir.stat()
        entries.append((str(self.dist_dir), root_stat.st_mtime_ns, root_stat.st_size))
        for manifest in sorted(self.dist_dir.glob("*/course.json")):
            try:
                stat = manifest.stat()
                directory = manifest.parent.stat()
            except OSError:
                continue
            entries.append((str(manifest), stat.st_mtime_ns, stat.st_size))
            entries.append((str(manifest.parent), directory.st_mtime_ns, directory.st_size))
        return tuple(entries)

    def _scan(self) -> Catalog:
        courses: list[ResolvedCourse] = []
        errors: list[CatalogError] = []

        if not self.dist_dir.is_dir():
            logger.warning("courses dist dir does not exist: %s", self.dist_dir)
            return Catalog()

        for course_dir in sorted(path for path in self.dist_dir.iterdir() if path.is_dir()):
            manifest_path = course_dir / "course.json"
            if not manifest_path.is_file():
                continue
            slug = course_dir.name
            try:
                raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(
                    _error(
                        "manifest_invalid",
                        f"无法读取解析清单：{exc}",
                        slug=slug,
                        file=str(manifest_path),
                    )
                )
                continue
            if not isinstance(raw, dict):
                errors.append(
                    _error(
                        "manifest_invalid",
                        "解析清单顶层必须是对象",
                        slug=slug,
                        file=str(manifest_path),
                    )
                )
                continue
            try:
                course = ResolvedCourse.model_validate(raw)
            except ValidationError as exc:
                first = exc.errors()[0]
                field = ".".join(str(part) for part in first.get("loc", ()))
                errors.append(
                    _error(
                        "manifest_invalid",
                        f"{field}: {first.get('msg', '字段不合法')}",
                        slug=slug,
                        file=str(manifest_path),
                    )
                )
                continue

            if course.slug != slug:
                errors.append(
                    _error(
                        "slug_mismatch",
                        f"清单 slug={course.slug!r} 与目录名 {slug!r} 不一致",
                        slug=slug,
                        file=str(manifest_path),
                    )
                )
                continue

            bundle_errors = self._verify_bundle(course_dir, course)
            if bundle_errors:
                errors.extend(bundle_errors)
                continue
            courses.append(course)

        published = sum(1 for course in courses if course.status == "published")
        invalid = len({error.slug for error in errors if error.slug})
        return Catalog(
            courses=courses,
            errors=errors,
            stats=CatalogStats(total=len(courses), published=published, invalid=invalid),
        )

    def _verify_bundle(self, course_dir: Path, course: ResolvedCourse) -> list[CatalogError]:
        if not self.verify_bundles:
            return []
        required = [
            course_dir / "index.html",
            course_dir / course.composition.entry,
            course_dir / "composition",
            course_dir / "runtime",
        ]
        errors: list[CatalogError] = []
        for path in required:
            if not path.exists():
                errors.append(
                    _error(
                        "bundle_incomplete",
                        f"课程包缺少 {path.relative_to(course_dir).as_posix()}",
                        slug=course.slug,
                        file=str(path),
                    )
                )
        return errors


def load_catalog(
    dist_dir: Path,
    *,
    verify_bundles: bool = True,
    strict: bool = False,
) -> Catalog:
    """One-shot convenience wrapper for scripts and tests."""

    return CatalogLoader(dist_dir, verify_bundles=verify_bundles).load(strict=strict)
