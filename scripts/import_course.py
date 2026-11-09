"""Import externally authored course folders into ``courses/``.

The CLI is a thin shell over ``app.catalog.importing``:

    python scripts/import_course.py <课程文件夹>
    python scripts/import_course.py <父文件夹>        # 批量，导入其下所有含 course.json 的目录
    python scripts/import_course.py --inbox          # 批量，扫描仓库根 course-inbox/
    python scripts/import_course.py courses/<slug>   # 课程已在 courses/：只校验并重新构建

Each course is validated first, then copied to a hidden staging directory,
built, and atomically moved to ``courses/<slug>``. After a successful import the
source is recorded in the ``course_imports`` table; that step is best effort so
an unmigrated database never blocks an import (run ``alembic upgrade head``).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy.exc import SQLAlchemyError  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.catalog.importing import (  # noqa: E402
    ImportCandidate,
    ImportResult,
    discover_course_sources,
    import_course,
    inspect_course,
    record_import,
)
from app.config import get_settings  # noqa: E402
from app.db import create_db_engine, create_session_factory  # noqa: E402


def _print_candidate(candidate: ImportCandidate) -> None:
    if candidate.screens is None:
        detail = "-"
    else:
        detail = f"{candidate.screens} 屏 / {candidate.duration:g}s"
    label = candidate.slug or candidate.name
    title = candidate.title or ""
    print(f"  {candidate.status:<7}  {label:<28}  {detail:<12}  {title}")
    print(f"           {candidate.path}")


def _print_error(result: ImportResult) -> None:
    for error in result.errors:
        location = " / ".join(
            part for part in (error.file, error.field, error.screen_id) if part
        )
        print(f"      [{error.code}] {error.message}")
        if location:
            print(f"      位置：{location}")
        if error.expected:
            print(f"      期望：{error.expected}")


def _print_result(result: ImportResult) -> None:
    if not result.ok:
        print(f"FAIL  {result.slug}  ({result.source})")
        _print_error(result)
        for warning in result.warnings:
            print(f"      warn  {warning}")
        return
    if result.built:
        action = f"构建 -> {result.output_dir}"
    elif result.copied:
        action = "已复制（未构建）"
    else:
        action = "只校验"
    print(f"ok    {result.slug}  {result.screens} 屏 / {result.duration:g}s  {action}")
    for warning in result.warnings:
        print(f"      warn  {warning}")


def _record_provenance(
    factory: sessionmaker[Session], result: ImportResult
) -> bool:
    """Write one provenance row. Returns False when the database is unusable."""

    try:
        with factory() as session:
            record_import(session, result)
            session.commit()
    except SQLAlchemyError as exc:
        print(
            f"  跳过数据库记录（先 alembic upgrade head）：{exc}",
            file=sys.stderr,
        )
        return False
    return True


def _resolve_sources(
    path: str | None, *, inbox: bool, inbox_dir: Path
) -> tuple[list[Path], str] | None:
    if inbox or path is None:
        if not inbox_dir.is_dir():
            print(
                f"收件箱不存在：{inbox_dir}\n"
                f"把外部课程文件夹放进 {inbox_dir.name}/，或显式传入课程文件夹路径。",
                file=sys.stderr,
            )
            return None
        return discover_course_sources(inbox_dir), f"{inbox_dir.name}/"

    target = Path(path).expanduser()
    if not target.exists():
        print(f"路径不存在：{target}", file=sys.stderr)
        return None
    resolved = target.resolve()
    return discover_course_sources(resolved), str(resolved)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="导入外部课程文件夹：校验 -> 复制到 courses/ -> 构建 dist -> 记录来源"
    )
    parser.add_argument("path", nargs="?", help="课程文件夹，或包含多个课程文件夹的父目录")
    parser.add_argument(
        "--inbox", action="store_true", help="扫描课程收件箱（Settings.courses_inbox_dir，默认 course-inbox/）"
    )
    parser.add_argument("--slug", default=None, help="只导入指定 slug")
    parser.add_argument(
        "--overwrite", action="store_true", help="courses/<slug>/ 已存在时替换（默认报 course_exists）"
    )
    parser.add_argument("--dry-run", action="store_true", help="只校验，不复制不构建")
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="只复制课程文件夹，不构建 dist；覆盖已有课程时会移除旧课程包",
    )
    parser.add_argument("--no-db", action="store_true", help="不写 course_imports 来源记录")
    args = parser.parse_args(argv)

    settings = get_settings()
    resolved = _resolve_sources(
        args.path, inbox=args.inbox, inbox_dir=Path(settings.courses_inbox_dir)
    )
    if resolved is None:
        return 1
    sources, origin = resolved
    if not sources:
        print(f"{origin} 里没有找到含 course.json 的课程文件夹", file=sys.stderr)
        return 1

    courses_root = Path(settings.courses_src_dir)
    dist_root = Path(settings.courses_dist_dir)
    runtime_dir = Path(settings.runtime_dir)

    candidates = [
        inspect_course(source, courses_root=courses_root) for source in sources
    ]
    if args.slug:
        candidates = [
            candidate
            for candidate in candidates
            if candidate.slug == args.slug or candidate.name == args.slug
        ]
        if not candidates:
            print(f"{origin} 里没有 slug 为 {args.slug!r} 的课程", file=sys.stderr)
            return 1

    print(f"候选课程（{len(candidates)} 门，来自 {origin}）：")
    for candidate in candidates:
        _print_candidate(candidate)
    print()

    session_factory: sessionmaker[Session] | None = None
    if not args.no_db and not args.dry_run:
        try:
            engine = create_db_engine(settings.database_url)
            session_factory = create_session_factory(engine)
        except SQLAlchemyError as exc:
            print(
                f"跳过数据库记录（先 alembic upgrade head）：{exc}", file=sys.stderr
            )

    results: list[ImportResult] = []
    for candidate in candidates:
        result = import_course(
            candidate.path,
            courses_root=courses_root,
            dist_root=dist_root,
            runtime_dir=runtime_dir,
            overwrite=args.overwrite,
            dry_run=args.dry_run,
            build=not args.no_build,
            include_drafts=bool(settings.include_drafts),
            site_url=settings.site_url,
            site_title=settings.site_title,
            course_base_url=settings.course_base_url,
            progress_sync=True,
        )
        _print_result(result)
        results.append(result)
        if (
            result.ok
            and session_factory is not None
            and not _record_provenance(session_factory, result)
        ):
            session_factory = None
        print()

    failed = [result for result in results if not result.ok]
    if failed:
        print(f"导入失败：{len(failed)} 门课程", file=sys.stderr)
        return 1
    if args.dry_run:
        print(f"校验通过：{len(results)} 门课程（未复制、未构建）")
    else:
        print(f"导入成功：{len(results)} 门课程")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
