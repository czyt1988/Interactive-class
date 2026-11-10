"""One-step environment preparation for the double-click launchers.

A fresh checkout has no ``.venv``, no pinned player assets and no built course
bundles, so ``star.cmd`` used to stop with "没有找到虚拟环境" and ask the user to
run a chain of commands by hand. ``scripts\\env.cmd`` now calls this module
first, so a beginner only ever double-clicks one file:

1. create ``.venv`` with a suitable Python;
2. install the project (``pip install -e ".[dev]"``);
3. download and sync the pinned player/runtime assets (``npm install`` followed
   by ``sync_runtime.py --skip-fonts``);
4. build the course bundles into ``dist/``;
5. apply the SQLite migrations.

Every step checks its own output first, so a second run only does the missing
work. This module stays on the standard library: on the very first run it is
executed by the system Python, before ``.venv`` and the dependencies exist.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import locale
import os
import shutil
import subprocess
import sys
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MIN_PYTHON = (3, 11)
MIN_NODE = (22, 0)
PLAYER_FILES = ("hyperframes-player.global.js", "hyperframe.runtime.iife.js")
REQUIRED_MODULES = ("uvicorn", "fastapi", "jinja2", "pydantic_settings", "sqlalchemy", "alembic")
INSTALL_TARGET = ".[dev]"

VENV_TIMEOUT_SECONDS = 600
INSTALL_TIMEOUT_SECONDS = 1800
BUILD_TIMEOUT_SECONDS = 600


class SetupError(Exception):
    """A problem a double-click user can fix, with one concrete next step."""

    def __init__(self, message: str, hint: str = "", details: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.details = details


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


# ---------------------------------------------------------------------------
# Process and console helpers


def _configure_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(ValueError):
                reconfigure(errors="replace")


def _decode(raw: bytes) -> str:
    if not raw:
        return ""
    preferred = locale.getpreferredencoding(False) or "utf-8"
    for encoding in ("utf-8", preferred):
        with contextlib.suppress(UnicodeDecodeError):
            return raw.decode(encoding)
    return raw.decode("utf-8", errors="replace")


def _tail(result: CommandResult, lines: int = 15) -> str:
    text = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    return "\n".join(text.splitlines()[-lines:])


def _run(
    command: list[str],
    *,
    cwd: Path = ROOT,
    timeout: float | None = None,
) -> CommandResult:
    try:
        completed = subprocess.run(command, cwd=str(cwd), capture_output=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise SetupError(
            f"无法运行 {command[0]}。",
            "重新双击 star.cmd；如果仍然失败，请确认这个程序还在 PATH 上。",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise SetupError(
            f"{command[0]} 运行超过 {int(timeout or 0)} 秒，已停止。",
            "检查网络后重新双击 star.cmd。",
        ) from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise SetupError(
            f"无法运行 {command[0]}：{exc}",
            "重新双击 star.cmd；如果问题仍在，请把这一行发给维护者。",
        ) from exc
    return CommandResult(completed.returncode, _decode(completed.stdout), _decode(completed.stderr))


class _Reporter:
    """Print progress only while work happens; skip noise on an ready machine."""

    def __init__(self, verbose: bool) -> None:
        self.verbose = verbose

    def info(self, text: str) -> None:
        if self.verbose:
            print(text, flush=True)

    def run(self, label: str, action: Callable[[], None]) -> None:
        print(f"  {label} ... ", end="", flush=True)
        started = time.monotonic()
        try:
            action()
        except SetupError:
            print("失败", flush=True)
            raise
        elapsed = time.monotonic() - started
        print("完成" if elapsed < 1 else f"完成（{elapsed:.0f} 秒）", flush=True)


# ---------------------------------------------------------------------------
# Virtual environment and dependencies


def venv_python(root: Path = ROOT) -> Path:
    if os.name == "nt":
        return root / ".venv" / "Scripts" / "python.exe"
    return root / ".venv" / "bin" / "python"


def _same_interpreter(python: Path) -> bool:
    try:
        left = os.path.normcase(os.path.realpath(python))
        right = os.path.normcase(os.path.realpath(sys.executable))
    except OSError:
        return False
    return left == right


def _python_version(python: Path) -> tuple[int, int] | None:
    result = _run(
        [str(python), "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
        timeout=120,
    )
    if not result.ok:
        return None
    parts = result.stdout.split()
    try:
        return int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        return None


def ensure_venv(reporter: _Reporter, root: Path = ROOT) -> Path:
    target = venv_python(root)
    if target.is_file():
        version = sys.version_info[:2] if _same_interpreter(target) else _python_version(target)
        if version is None or version < MIN_PYTHON:
            raise SetupError(
                "虚拟环境 .venv 已经损坏，或者里面的 Python 版本太旧。",
                "关闭所有 AI Learning 窗口，删除仓库根目录的 .venv 文件夹，"
                "然后重新双击 star.cmd 让它自动重建。",
            )
        reporter.info("  虚拟环境 .venv 已就绪")
        return target

    reporter.run("创建虚拟环境 .venv", lambda: _create_venv(root))
    return target


def _create_venv(root: Path) -> None:
    result = _run(
        [sys.executable, "-m", "venv", str(root / ".venv")],
        cwd=root,
        timeout=VENV_TIMEOUT_SECONDS,
    )
    if not result.ok or not venv_python(root).is_file():
        raise SetupError(
            "创建虚拟环境失败。",
            "确认 Python 安装完整（安装时勾选 Add python.exe to PATH），然后重新双击 star.cmd。",
            _tail(result),
        )


def _missing_modules(python: Path) -> list[str]:
    if _same_interpreter(python):
        return [name for name in REQUIRED_MODULES if importlib.util.find_spec(name) is None]
    result = _run([str(python), "-c", "import " + ", ".join(REQUIRED_MODULES)], timeout=120)
    return [] if result.ok else list(REQUIRED_MODULES)


def ensure_dependencies(reporter: _Reporter, root: Path = ROOT) -> bool:
    python = venv_python(root)
    missing = _missing_modules(python)
    if not missing:
        reporter.info("  项目依赖已就绪")
        return False
    reporter.run(
        "安装项目依赖（需要联网，第一次通常 1 到 3 分钟）",
        lambda: _pip_install(root, python),
    )
    return True


def _pip_install(root: Path, python: Path) -> None:
    result = _run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--quiet",
            "-e",
            INSTALL_TARGET,
        ],
        cwd=root,
        timeout=INSTALL_TIMEOUT_SECONDS,
    )
    if not result.ok:
        raise SetupError(
            "安装项目依赖失败。",
            "检查网络后重新双击 star.cmd。国内网络可以先在命令行执行 "
            "set PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple 再重试。",
            _tail(result),
        )


# ---------------------------------------------------------------------------
# Player / runtime assets


def _runtime_dir(root: Path) -> Path:
    return root / "runtime"


def _player_assets_ready(root: Path) -> bool:
    vendor = _runtime_dir(root) / "vendor"
    if not (_runtime_dir(root) / "VERSION.json").is_file():
        return False
    return all((vendor / name).is_file() for name in PLAYER_FILES)


def _course_vendor_ready(root: Path) -> bool:
    courses = root / "courses"
    if not courses.is_dir():
        return True
    for course_dir in sorted(courses.iterdir()):
        if not course_dir.is_dir() or course_dir.name.startswith((".", "_")):
            continue
        assets = course_dir / "composition" / "assets"
        if not (assets / "course.css").is_file():
            continue
        if not (assets / "vendor" / "gsap.min.js").is_file():
            return False
    return True


def runtime_assets_ready(root: Path = ROOT) -> bool:
    return _player_assets_ready(root) and _course_vendor_ready(root)


def _tools_installed(root: Path) -> bool:
    node_modules = root / "tools" / "node_modules"
    hyperframes = node_modules / "hyperframes" / "dist"
    gsap = node_modules / "gsap" / "dist"
    return (
        all((hyperframes / name).is_file() for name in PLAYER_FILES)
        and (gsap / "gsap.min.js").is_file()
    )


def _node_executable() -> str | None:
    return shutil.which("node")


def _npm_executable(node: str) -> str | None:
    suffix = "npm.cmd" if os.name == "nt" else "npm"
    beside_node = Path(node).with_name(suffix)
    if beside_node.is_file():
        return str(beside_node)
    return shutil.which("npm")


def _node_major(node: str) -> int | None:
    result = _run([node, "--version"], timeout=60)
    if not result.ok:
        return None
    text = result.stdout.strip().lstrip("v")
    try:
        return int(text.split(".")[0])
    except (IndexError, ValueError):
        return None


def _require_node() -> tuple[str, str]:
    node = _node_executable()
    if node is None:
        raise SetupError(
            "准备播放器资源需要 Node.js 22 或更高版本，这台电脑上没有找到。",
            "从 https://nodejs.org/zh-cn 安装 Node.js 22，装好后重新双击 star.cmd；"
            "如果已经装过，把它的安装目录加进 PATH。",
        )
    major = _node_major(node)
    if major is not None and major < MIN_NODE[0]:
        raise SetupError(
            f"Node.js 版本太旧（当前 v{major}），需要 22 或更高版本。",
            "从 https://nodejs.org/zh-cn 安装新版 Node.js，然后重新双击 star.cmd。",
        )
    npm = _npm_executable(node)
    if npm is None:
        raise SetupError(
            "找到了 Node.js，但没有找到 npm。",
            "重新安装 Node.js 22（安装包自带 npm），然后重新双击 star.cmd。",
        )
    return node, npm


def ensure_runtime_assets(reporter: _Reporter, root: Path = ROOT) -> bool:
    if runtime_assets_ready(root):
        reporter.info("  播放器资源已就绪")
        return False

    _node, npm = _require_node() if not _tools_installed(root) else (None, None)
    if npm is not None:
        reporter.run(
            "下载播放器资源（npm install，需要联网，第一次通常 1 到 3 分钟）",
            lambda: _npm_install(root, npm),
        )
    reporter.run(
        "同步播放器、GSAP 与设计令牌",
        lambda: _run_python(
            root,
            [str(root / "scripts" / "sync_runtime.py"), "--skip-fonts"],
            timeout=BUILD_TIMEOUT_SECONDS,
            title="同步播放器资源",
        ),
    )
    if not runtime_assets_ready(root):
        raise SetupError(
            "播放器资源没有同步成功。",
            "重新双击 star.cmd；如果仍然失败，请把上面的错误信息发给维护者。",
        )
    return True


def _npm_install(root: Path, npm: str) -> None:
    result = _run(
        [npm, "install", "--no-fund", "--no-audit", "--loglevel=error"],
        cwd=root / "tools",
        timeout=INSTALL_TIMEOUT_SECONDS,
    )
    if not result.ok:
        raise SetupError(
            "下载播放器资源失败（npm install）。",
            "检查网络后重新双击 star.cmd；npm 的报错在下面。",
            _tail(result),
        )


# ---------------------------------------------------------------------------
# Course bundles, database and the whole pipeline


def ensure_courses_built(reporter: _Reporter, root: Path = ROOT) -> bool:
    if (root / "dist" / "courses").is_dir() and (root / "dist" / "build.json").is_file():
        reporter.info("  课程页面已就绪")
        return False
    reporter.run(
        "构建课程页面",
        lambda: _run_python(
            root,
            [str(root / "scripts" / "build_courses.py"), "--all"],
            timeout=BUILD_TIMEOUT_SECONDS,
            title="构建课程页面",
        ),
    )
    if not (root / "dist" / "courses").is_dir():
        raise SetupError(
            "课程页面没有构建成功。",
            "重新双击 star.cmd；如果仍然失败，请把上面的错误信息发给维护者。",
        )
    return True


def ensure_database(reporter: _Reporter, root: Path = ROOT) -> None:
    def migrate() -> None:
        _run_python(
            root,
            ["-m", "alembic", "upgrade", "head"],
            timeout=BUILD_TIMEOUT_SECONDS,
            title="更新数据库表结构",
        )

    if reporter.verbose:
        reporter.run("更新数据库表结构", migrate)
    else:
        # Fast and harmless when the schema is current, so it runs quietly on
        # every start; a failure still raises with its own explanation.
        migrate()


def _run_python(
    root: Path,
    arguments: list[str],
    *,
    timeout: float,
    title: str,
) -> None:
    result = _run([str(venv_python(root)), *arguments], cwd=root, timeout=timeout)
    if not result.ok:
        raise SetupError(
            f"{title}失败。",
            "按上面的提示处理后重新双击 star.cmd。",
            _tail(result),
        )


def ensure(root: Path = ROOT, *, verbose: bool = False) -> list[str]:
    """Make ``root`` runnable and return the steps that actually did work."""

    reporter = _Reporter(verbose)
    actions: list[str] = []
    ensure_venv(reporter, root)
    if ensure_dependencies(reporter, root):
        actions.append("dependencies")
    if ensure_runtime_assets(reporter, root):
        actions.append("runtime")
    if ensure_courses_built(reporter, root):
        actions.append("courses")
    ensure_database(reporter, root)
    return actions


# ---------------------------------------------------------------------------
# CLI


def _check_interpreter() -> None:
    if sys.version_info < MIN_PYTHON:
        raise SetupError(
            f"当前 Python 是 {sys.version.split()[0]}，版本太旧。",
            f"安装 Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} 或更高版本"
            "（https://www.python.org/downloads/，安装时勾选 Add python.exe to PATH），"
            "然后重新双击 star.cmd。",
        )


def _print_error(exc: SetupError) -> None:
    print()
    print(f"[错误] {exc.message}")
    if exc.details:
        print()
        print("  最后几行输出：")
        for line in exc.details.splitlines():
            print(f"    {line}")
    if exc.hint:
        print()
        for line in exc.hint.splitlines():
            print(f"  {line}")
    print()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="准备 AI Learning 的本地运行环境")
    parser.add_argument("--quiet", action="store_true", help="已就绪时不打印任何内容")
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_output()
    args = build_parser().parse_args(argv)

    if not args.quiet:
        print()
        print("=" * 60)
        print("  AI Learning - 准备运行环境")
        print("=" * 60)
        print("  第一次需要联网下载依赖，可能要几分钟；只做一次。")
        print()

    try:
        _check_interpreter()
        ensure(ROOT, verbose=not args.quiet)
    except SetupError as exc:
        _print_error(exc)
        return 1
    except Exception:
        print()
        print("[错误] 准备环境时出现意外错误，请把下面的信息发给维护者。")
        traceback.print_exc()
        return 1

    if not args.quiet:
        print()
        print("环境已就绪。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
