"""Rebuild the whole project after edits, from one double-clicked ``build.cmd``.

``bootstrap.py`` prepares a machine: it only fills in what is missing, which is
fast to call before every start but does not notice edited course copy, design
tokens or a new migration. After a user changes the project they need the
opposite: run every generation step again and trust the newest sources. This
module is that "always rebuild" pass, and ``build.cmd`` is its double-click
wrapper.

Steps, in order (the order is part of the contract):

1. import the backend: catches missing dependencies and broken modules before
   the slower steps;
2. ``sync_runtime.py``: copy the pinned player/runtime and GSAP files, and
   regenerate the design tokens and font subsets from the current course and
   site copy (not ``--skip-fonts``: edited copy needs new glyphs);
3. ``alembic upgrade head``: so the course build reads the current watermark
   table;
4. ``build_courses.py``: rebuild ``dist/courses/<slug>/`` for every published
   course, with the site URL taken from ``start.cmd`` so the port the user
   actually opens and the built progress-sync origin agree.

Run with: ``python scripts/build.py`` (``build.cmd`` does this for you).
"""

from __future__ import annotations

import argparse
import contextlib
import subprocess
import sys
import time
import traceback
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Same reason as build_courses.py: a shared .venv across git worktrees must not
# make ``import app`` resolve to the main worktree's checkout.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.bootstrap import venv_python  # noqa: E402
from scripts.launcher import (  # noqa: E402
    endpoint_from_config,
    process_matches,
    read_state,
    state_file,
)


class BuildError(Exception):
    """A failure with one concrete next step for a double-click user."""

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


@dataclass(frozen=True)
class Step:
    title: str
    command: list[str]


def _configure_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(ValueError):
                reconfigure(errors="replace")


def site_url(root: Path = ROOT, override: str | None = None) -> str:
    """Origin the built course bundles should call for progress sync.

    ``start.cmd`` is the launcher the user actually double-clicks, and its
    ``APP_PORT`` / ``APP_HOST`` decide the local URL. Building with the default
    ``127.0.0.1:8000`` would silently disable progress sync on the 8081 port the
    launcher binds, so derive the URL from the same file; ``--site-url``
    overrides it for deployments.
    """

    if override:
        return override.rstrip("/")
    return endpoint_from_config(root / "start.cmd").local_url


def build_plan(
    root: Path = ROOT,
    *,
    site_url_override: str | None = None,
    courses: Sequence[str] | None = None,
) -> list[Step]:
    python = str(venv_python(root))
    scripts = root / "scripts"
    course_args: list[str] = []
    for slug in courses or ():
        course_args.extend(("--course", slug))
    if not course_args:
        course_args.append("--all")
    return [
        Step(
            "检查后端依赖与代码（导入 app.main）",
            [python, "-c", "import sys; sys.path.insert(0, '.'); import app.main"],
        ),
        Step(
            "同步播放器、字体子集与设计令牌",
            [python, str(scripts / "sync_runtime.py")],
        ),
        Step(
            "更新数据库表结构",
            [python, "-m", "alembic", "upgrade", "head"],
        ),
        Step(
            "构建课程页面",
            [
                python,
                str(scripts / "build_courses.py"),
                *course_args,
                "--site-url",
                site_url(root, site_url_override),
            ],
        ),
    ]


def _format_elapsed(seconds: float) -> str:
    return "完成" if seconds < 1 else f"完成（{seconds:.0f} 秒）"


def run_step(step: Step, *, root: Path = ROOT) -> None:
    """Run one build step with inherited stdio so its output is visible live."""

    try:
        completed = subprocess.run([str(part) for part in step.command], cwd=str(root))
    except FileNotFoundError as exc:
        raise BuildError(
            f"无法运行 {step.command[0]}。",
            "重新双击 build.cmd；如果仍然失败，请确认虚拟环境 .venv 完整。",
        ) from exc
    except OSError as exc:
        raise BuildError(
            f"无法运行 {step.command[0]}：{exc}",
            "重新双击 build.cmd；如果问题仍在，请把这一行发给维护者。",
        ) from exc
    if completed.returncode != 0:
        raise BuildError(
            f"{step.title}失败（退出码 {completed.returncode}）。",
            "按上面的错误信息处理后，重新双击 build.cmd。",
        )


def execute(
    plan: Sequence[Step],
    *,
    root: Path = ROOT,
    runner: Callable[[Step], None] | None = None,
) -> None:
    for index, step in enumerate(plan, 1):
        print(f"\n  [{index}/{len(plan)}] {step.title} ...", flush=True)
        started = time.monotonic()
        if runner is None:
            run_step(step, root=root)
        else:
            runner(step)
        print(f"       {_format_elapsed(time.monotonic() - started)}", flush=True)


def _service_running(root: Path) -> bool:
    state = read_state(state_file(root))
    return state is not None and process_matches(state)


def build(
    root: Path = ROOT,
    *,
    site_url_override: str | None = None,
    courses: Sequence[str] | None = None,
    runner: Callable[[Step], None] | None = None,
) -> list[Step]:
    """Run the full rebuild and return the steps that were executed."""

    if not venv_python(root).is_file():
        raise BuildError(
            "没有找到虚拟环境 .venv，构建无法开始。",
            "先双击 start.cmd 完成第一次环境准备（只需要一次），再双击 build.cmd。",
        )
    plan = build_plan(root, site_url_override=site_url_override, courses=courses)
    execute(plan, root=root, runner=runner)
    return plan


def _print_error(exc: BuildError) -> None:
    print()
    print(f"[错误] {exc.message}")
    if exc.hint:
        print()
        for line in exc.hint.splitlines():
            print(f"  {line}")
    print()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="重新构建页间课堂全项目")
    parser.add_argument(
        "--course",
        action="append",
        default=None,
        help="只重建指定 slug 的课程页面，可重复；默认重建全部已发布课程",
    )
    parser.add_argument(
        "--site-url",
        default=None,
        help="构建产物里课程页使用的站点地址；默认读取 start.cmd 的 APP_PORT / APP_HOST",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_output()
    args = build_parser().parse_args(argv)

    print()
    print("=" * 60)
    print("  页间课堂 - 一键构建")
    print("=" * 60)
    print(f"  项目目录  {ROOT}")
    print(f"  站点地址  {site_url(ROOT, args.site_url)}")
    print("  构建内容  后端导入检查 / 运行时与字体 / 数据库迁移 / 课程页面")
    print("-" * 60)

    try:
        build(ROOT, site_url_override=args.site_url, courses=args.course)
    except BuildError as exc:
        _print_error(exc)
        return 1
    except KeyboardInterrupt:
        print()
        print("已取消。")
        return 130
    except Exception:
        print()
        print("[错误] 构建时出现意外错误，请把下面的信息发给维护者。")
        traceback.print_exc()
        return 1

    print()
    print("=" * 60)
    print("  构建完成。")
    print("=" * 60)
    if _service_running(ROOT):
        print("  站点正在运行：课程页面刷新即可看到；改了站点代码请双击 restart.cmd。")
    else:
        print("  现在双击 start.cmd 启动最新版本。")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
