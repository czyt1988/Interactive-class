"""Scaffold a new course from ``course-template/``.

    python scripts/new_course.py <slug> --title "课程标题" \
        [--subtitle "..."] [--source-dir courses] [--template course-template] [--published]

Only ``course.json``, ``STORYBOARD.md`` and ``composition/`` are copied: the
template's authoring docs and agent instructions are for the template package
itself, not for the course folder. The manifest slug/title/subtitle/status and
``composition/package.json`` name are rewritten, and the template's two valid
placeholder screens are kept so the scaffold builds immediately.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.catalog.importing import EXCLUDED_NAMES, EXCLUDED_SUFFIXES  # noqa: E402
from app.catalog.models import SLUG_PATTERN  # noqa: E402

MAX_SLUG_LENGTH = 80
TITLE_MIN, TITLE_MAX = 2, 40
SUBTITLE_MIN, SUBTITLE_MAX = 1, 60


def _repo_path(value: Path) -> Path:
    """Resolve relative CLI paths against the repository root, not the cwd."""

    return value if value.is_absolute() else (ROOT / value).resolve()


def _display(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _copy_ignore(_directory: str, names: list[str]) -> set[str]:
    return {
        name
        for name in names
        if name.lower() in EXCLUDED_NAMES or Path(name).suffix.lower() in EXCLUDED_SUFFIXES
    }


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _rewrite_manifest(
    target: Path, *, slug: str, title: str, subtitle: str | None, published: bool
) -> None:
    manifest_path = target / "course.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("模板 course.json 顶层必须是对象")
    payload["slug"] = slug
    payload["title"] = title
    if subtitle is None:
        payload.pop("subtitle", None)
    else:
        payload["subtitle"] = subtitle
    payload["status"] = "published" if published else "draft"
    credits = payload.get("credits")
    if not isinstance(credits, dict):
        credits = {}
    credits["updatedAt"] = date.today().isoformat()
    payload["credits"] = credits
    _write_json(manifest_path, payload)


def _rewrite_package_name(target: Path, slug: str) -> None:
    package_path = target / "composition" / "package.json"
    package: object = {}
    if package_path.is_file():
        package = json.loads(package_path.read_text(encoding="utf-8"))
    if not isinstance(package, dict):
        package = {}
    package["name"] = f"course-{slug}"
    package.setdefault("private", True)
    _write_json(package_path, package)


def _validate_text(value: str, *, field: str, minimum: int, maximum: int) -> str | None:
    stripped = value.strip()
    if not minimum <= len(stripped) <= maximum:
        print(
            f"{field} 长度必须在 {minimum}–{maximum} 字符之间，当前 {len(stripped)}",
            file=sys.stderr,
        )
        return None
    return stripped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从 course-template/ 生成新课程脚手架")
    parser.add_argument("slug", help="课程 slug，例如 what-is-a-token")
    parser.add_argument("--title", required=True, help="课程标题（2–40 字符）")
    parser.add_argument("--subtitle", default=None, help="副标题（1–60 字符）")
    parser.add_argument(
        "--source-dir", type=Path, default=Path("courses"), help="课程源根目录，默认 courses/"
    )
    parser.add_argument(
        "--template", type=Path, default=Path("course-template"), help="模板目录，默认 course-template/"
    )
    parser.add_argument("--published", action="store_true", help="直接标记为 published（默认 draft）")
    args = parser.parse_args(argv)

    slug = args.slug.strip()
    if not SLUG_PATTERN.match(slug):
        print(
            f"slug 不合法：{args.slug!r}；必须匹配 ^[a-z0-9]+(?:-[a-z0-9]+)*$"
            "（小写字母/数字，用连字符分隔）",
            file=sys.stderr,
        )
        return 1
    if len(slug) > MAX_SLUG_LENGTH:
        print(f"slug 太长：{len(slug)} 字符，上限 {MAX_SLUG_LENGTH}", file=sys.stderr)
        return 1

    title = _validate_text(
        args.title, field="--title", minimum=TITLE_MIN, maximum=TITLE_MAX
    )
    if title is None:
        return 1
    subtitle: str | None = None
    if args.subtitle is not None:
        subtitle = _validate_text(
            args.subtitle, field="--subtitle", minimum=SUBTITLE_MIN, maximum=SUBTITLE_MAX
        )
        if subtitle is None:
            return 1

    template_dir = _repo_path(args.template)
    template_missing = [
        name
        for name in ("course.json", "STORYBOARD.md", "composition")
        if not (template_dir / name).exists()
    ]
    if template_missing:
        print(
            f"模板目录缺失或不完整：{template_dir}（缺 {', '.join(template_missing)}）\n"
            "先完成 course-template/ 抽取。",
            file=sys.stderr,
        )
        return 1

    source_dir = _repo_path(args.source_dir)
    target = source_dir / slug
    if target.exists():
        print(f"目标已存在：{target}\n脚手架绝不覆盖已有课程。", file=sys.stderr)
        return 1

    try:
        target.mkdir(parents=True)
        shutil.copy2(template_dir / "course.json", target / "course.json")
        shutil.copy2(template_dir / "STORYBOARD.md", target / "STORYBOARD.md")
        shutil.copytree(
            template_dir / "composition", target / "composition", ignore=_copy_ignore
        )
        _rewrite_manifest(
            target, slug=slug, title=title, subtitle=subtitle, published=args.published
        )
        _rewrite_package_name(target, slug)
    except (OSError, shutil.Error, json.JSONDecodeError, ValueError) as exc:
        shutil.rmtree(target, ignore_errors=True)
        print(f"生成脚手架失败：{exc}", file=sys.stderr)
        return 1

    print(f"已创建课程：{_display(target)}")
    print("下一步：")
    print(f"  1. 写 {_display(target / 'STORYBOARD.md')}：学习者、学完能、每屏一句话论题")
    print(
        f"  2. 做 composition：逐屏改 {_display(target / 'composition' / 'compositions')}/ 里的 scene，"
        "并挂到 composition/index.html"
    )
    print(f"  3. 构建：python scripts/build_courses.py --course {slug}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
