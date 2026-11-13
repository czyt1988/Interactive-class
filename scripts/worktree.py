"""git 工作树助手：并行开发时每个任务一个独立工作区，复用主工作树的依赖。

背景
----
这个仓库经常有多个 Agent 会话并行开发。多个任务挤在同一个工作区里，切分支、
暂存区、未提交改动会互相污染，所以每个任务都在 ``<仓库根>/.worktree/<分支名>``
下开一个独立的 git 工作树，完成后合并回集成分支 ``main``（见 AGENTS.md）。

裸 ``git worktree add`` 在本仓库里不够用，脚本补上三件事:

1. **复用依赖，不重新下载**
   ``.venv``（Python 依赖，通常几百 MB）、``tools/node_modules``（HyperFrames /
   GSAP 创作工具）、``tools/ffmpeg``（本地视频导出工具）都以目录联接（Windows
   junction / POSIX 软链接）挂进工作树。新工作树立刻可跑 ``pytest`` / ``ruff``，
   不需要 ``pip install``、``npm install``，也不消耗网络。

2. **复制"应该各写各的"生成物**
   ``runtime/vendor``（由 ``sync_runtime.py`` 生成）和 ``.env`` 复制而不是共享：
   在工作树里重跑同步脚本不会改到主工作树；本地配置也可以各用各的。
   ``courses/*/narration/cache/``（TTS 缓存）只读复用，避免重新联网合成；
   它和 ``pip install`` / ``npm install`` 一样属于"串行步骤"，不要并行重建旁白。

3. **安全创建与拆除**
   Windows 的目录联接在不同工具/版本里的递归删除行为不一致，可能跟随到目标
   目录（也就是主工作树的 ``.venv``、``node_modules``）。``remove`` 先拆联接、
   再删工作树，并且绝不递归删除仍含联接的目录；工作树有未提交改动时拒绝删除
   （``--force`` 才丢弃）。``merge`` 冲突失败会 ``git merge --abort``，不让主
   工作树停在冲突状态。不要手工 ``rm -rf .worktree/<名字>``，用 ``remove``。

用法
----
::

    python scripts/worktree.py add feat/course-xyz        # 从 main 切出工作树
    python scripts/worktree.py add fix/player-crash --base main
    python scripts/worktree.py list                       # 列出工作树与共享状态
    python scripts/worktree.py link                       # 补齐/修复共享目录（刷新副本）
    python scripts/worktree.py remove feat-course-xyz     # 删除工作树（保留分支）
    python scripts/worktree.py remove feat-course-xyz --force   # 丢弃未提交改动后删除
    python scripts/worktree.py merge feat/course-xyz --remove
                                                          # 验证 + 快进合并回 main + 清理

共享不是永久承诺：主工作树升级了依赖（``pip install``）或 ``tools`` 依赖后，
新装的包会通过联接自动可见；升级 ``tools/package.json`` 并 ``npm install`` 属于
"串行步骤"，请在主工作树做，不要在多个工作树里同时装。
"""

from __future__ import annotations

import argparse
import contextlib
import filecmp
import os
import shutil
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

BASE_BRANCH = "main"
WORKTREE_DIR = ".worktree"


class WorktreeError(Exception):
    """A user-fixable problem; the CLI prints it without a traceback."""


# ---------------------------------------------------------------------------
# Console / subprocess helpers


def _configure_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(ValueError):
                reconfigure(errors="replace")


def _note(text: str = "", *, end: str = "\n") -> None:
    print(text, end=end, flush=True)


def _warn(text: str) -> None:
    print(f"警告: {text}", file=sys.stderr, flush=True)


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    return env


def _run(
    command: list[str],
    *,
    cwd: Path,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=_git_env(),
        )
    except FileNotFoundError as exc:
        raise WorktreeError(f"找不到命令 {command[0]}；请确认它已安装并在 PATH 上") from exc
    except subprocess.TimeoutExpired as exc:
        raise WorktreeError(f"命令超时（{int(timeout or 0)} 秒）: {' '.join(command)}") from exc
    except OSError as exc:
        raise WorktreeError(f"无法运行 {' '.join(command)}：{exc}") from exc


def run_git(*args: str, cwd: Path, check: bool = True) -> str:
    completed = _run(["git", *args], cwd=cwd)
    if check and completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise WorktreeError(f"git {' '.join(args)} 失败：\n{detail}")
    return completed.stdout.strip()


def git_ok(*args: str, cwd: Path) -> str | None:
    """Run git and return stdout, or None when it exits non-zero."""

    completed = _run(["git", *args], cwd=cwd)
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _tail(text: str, lines: int = 25) -> str:
    rows = [row for row in (text or "").splitlines() if row.strip()]
    return "\n".join(rows[-lines:])


# ---------------------------------------------------------------------------
# Path helpers


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(
        os.path.abspath(str(right))
    )


def venv_python(root: Path) -> Path:
    if os.name == "nt":
        return root / ".venv" / "Scripts" / "python.exe"
    return root / ".venv" / "bin" / "python"


def is_link(path: Path) -> bool:
    """True for POSIX symlinks, Windows symlinks and Windows directory junctions."""

    if os.path.islink(path):
        return True
    is_junction = getattr(os.path, "isjunction", None)
    if is_junction is not None and is_junction(path):
        return True
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return bool(getattr(info, "st_reparse_tag", 0))


def _ps_quote(value: Path) -> str:
    # PowerShell: single-quoted strings escape a quote by doubling it.
    return str(value).replace("'", "''")


def _create_junction(source: Path, destination: Path) -> None:
    command = (
        "$ErrorActionPreference='Stop'; "
        f"New-Item -ItemType Junction -Path '{_ps_quote(destination)}' "
        f"-Target '{_ps_quote(source)}' | Out-Null"
    )
    completed = _run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=destination.parent,
        timeout=120,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise WorktreeError(f"创建目录联接失败: {destination} -> {source}\n{detail}")


def create_dir_link(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if is_link(destination):
        return
    if os.name == "nt":
        _create_junction(source, destination)
    else:
        os.symlink(source, destination, target_is_directory=True)


def remove_link(path: Path) -> None:
    """Remove one link/junction itself; never touch its target."""

    try:
        os.unlink(path)
        return
    except OSError:
        pass
    try:
        os.rmdir(path)
        return
    except OSError as exc:
        raise WorktreeError(f"拆除共享目录失败: {path}（{exc}）") from exc


def find_reparse_points(root: Path) -> list[Path]:
    """Every link/junction below ``root`` (does not descend into them)."""

    found: list[Path] = []
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError:
            continue
        for entry in entries:
            path = Path(entry.path)
            try:
                info = os.lstat(path)
            except OSError:
                continue
            if is_link(path):
                found.append(path)
                continue
            if stat.S_ISDIR(info.st_mode):
                stack.append(path)
    return found


# ---------------------------------------------------------------------------
# Sharing the main worktree's dependencies


@dataclass(frozen=True)
class Share:
    """One relative path copied or linked from the main worktree."""

    relative: str
    mode: str  # "link" | "copy"
    note: str


SHARES: tuple[Share, ...] = (
    Share(
        ".venv",
        "link",
        "Python 虚拟环境与已装依赖（不重装、不联网）",
    ),
    Share(
        "tools/node_modules",
        "link",
        "HyperFrames / GSAP 创作工具依赖（不重新 npm install）",
    ),
    Share(
        "tools/ffmpeg",
        "link",
        "本地视频导出工具 ffmpeg / ffprobe（不进 Git）",
    ),
    Share(
        "runtime/vendor",
        "copy",
        "播放器运行时文件（复制；工作树里重跑 sync_runtime 不会改主工作树）",
    ),
    Share(
        ".env",
        "copy",
        "本地配置（复制，各工作树用自己的一份）",
    ),
    Share(
        "courses/*/narration/cache",
        "link",
        "旁白 TTS 缓存（不重新联网合成）",
    ),
)


@dataclass
class WorktreeEntry:
    path: Path
    branch: str | None = None
    head: str | None = None


@dataclass
class Repo:
    main: Path
    wt_root: Path
    current: Path
    worktrees: list[WorktreeEntry]

    def is_main(self, path: Path) -> bool:
        return _same_path(path, self.main)


def _parse_worktree_list(text: str) -> list[WorktreeEntry]:
    entries: list[WorktreeEntry] = []
    current: WorktreeEntry | None = None
    for line in text.splitlines():
        if line.startswith("worktree "):
            if current is not None:
                entries.append(current)
            current = WorktreeEntry(path=Path(line[len("worktree ") :]))
        elif current is None:
            continue
        elif line.startswith("HEAD "):
            current.head = line[len("HEAD ") :]
        elif line.startswith("branch "):
            current.branch = line[len("branch ") :].removeprefix("refs/heads/")
        elif line == "detached":
            current.branch = None
    if current is not None:
        entries.append(current)
    return entries


def discover_repo() -> Repo:
    current_raw = git_ok("rev-parse", "--show-toplevel", cwd=Path.cwd())
    if not current_raw:
        raise WorktreeError("当前目录不在 git 仓库里；请先 cd 到仓库根目录再运行")
    current = Path(current_raw)

    entries = _parse_worktree_list(run_git("worktree", "list", "--porcelain", cwd=current))
    if not entries:
        raise WorktreeError("git 没有返回任何工作树信息")
    main = entries[0].path
    if not main.is_dir():
        raise WorktreeError(f"主工作树目录不存在: {main}")
    return Repo(
        main=main,
        wt_root=main / WORKTREE_DIR,
        current=current,
        worktrees=entries,
    )


def _share_sources(repo: Repo) -> list[tuple[Share, Path, Path]]:
    """(share, absolute source, relative path) for every share present in main."""

    pairs: list[tuple[Share, Path, Path]] = []
    for share in SHARES:
        if "*" in share.relative:
            matches = sorted(repo.main.glob(share.relative))
        else:
            candidate = repo.main / share.relative
            matches = [candidate] if candidate.exists() else []
        for source in matches:
            if not (source.exists() or is_link(source)):
                continue
            pairs.append((share, source, source.relative_to(repo.main)))
    return pairs


def _copy_path(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)


def _copy_matches(source: Path, destination: Path) -> bool:
    """True when a copied share (``runtime/vendor``、``.env``) is already current."""

    if source.is_dir() != destination.is_dir():
        return False
    if source.is_file():
        return filecmp.cmp(source, destination, shallow=False)
    comparison = filecmp.dircmp(source, destination)
    if comparison.left_only or comparison.right_only or comparison.funny_files:
        return False
    _match, mismatch, errors = filecmp.cmpfiles(
        source, destination, comparison.common_files, shallow=False
    )
    if mismatch or errors:
        return False
    return all(_copy_matches(source / name, destination / name) for name in comparison.common_dirs)


def _share_candidates(root: Path, share: Share) -> list[Path]:
    """Existing paths in ``root`` matching a share pattern (dangling links included)."""

    if "*" in share.relative:
        return sorted(root.glob(share.relative))
    candidate = root / share.relative
    return [candidate] if (candidate.exists() or is_link(candidate)) else []


def apply_shares(
    repo: Repo, worktree: Path, *, refresh: bool = False
) -> tuple[list[str], list[str]]:
    """Copy/link every available share into ``worktree``. Idempotent.

    ``refresh=True`` re-copies snapshot shares whose content changed in the main
    worktree, so ``link`` really repairs ``runtime/vendor`` and ``.env``.
    """

    done: list[str] = []
    problems: list[str] = []

    # 悬空的共享联接（目标被移走/改名）会让同步悄悄失效。先清掉再按主工作树
    # 当前状态重建；没有源可重建时明确报错，而不是静默“已就绪”。
    for share in SHARES:
        if share.mode != "link":
            continue
        for path in _share_candidates(worktree, share):
            if is_link(path) and not path.exists():
                remove_link(path)
                problems.append(
                    f"{path.relative_to(worktree).as_posix()} 的共享联接已失效"
                    "（目标不存在），已清理；确认主工作树环境完好后重新运行 link"
                )

    for share, source, relative in _share_sources(repo):
        destination = worktree / relative
        try:
            if share.mode == "copy":
                if destination.exists():
                    if refresh and not _copy_matches(source, destination):
                        if destination.is_dir():
                            shutil.rmtree(destination)
                        else:
                            destination.unlink()
                        _copy_path(source, destination)
                        done.append(f"刷新  {relative.as_posix():<24} {share.note}")
                    continue
                _copy_path(source, destination)
                done.append(f"复制  {relative.as_posix():<24} {share.note}")
                continue
            if is_link(destination):
                if destination.exists():
                    continue
                remove_link(destination)
            if destination.exists():
                problems.append(
                    f"{relative.as_posix()} 已存在真实目录，未共享；确认内容无用后可删掉它再运行 link"
                )
                continue
            create_dir_link(source, destination)
            done.append(f"共享  {relative.as_posix():<24} {share.note}")
        except (OSError, WorktreeError) as exc:
            problems.append(f"{relative.as_posix()} 共享失败：{exc}")
    return done, problems


def missing_shares(repo: Repo, worktree: Path) -> list[str]:
    """Share paths that are absent, dangling or stale in ``worktree``."""

    missing: set[str] = set()
    expected = {relative.as_posix() for _share, _source, relative in _share_sources(repo)}

    for share in SHARES:
        for path in _share_candidates(worktree, share):
            relative = path.relative_to(worktree).as_posix()
            if not path.exists():  # 悬空联接
                missing.add(relative)
            elif share.mode == "copy" and "*" not in share.relative:
                source = repo.main / relative
                if source.exists() and not _copy_matches(source, path):
                    missing.add(relative)

    for relative in expected:
        if not (worktree / relative).exists():
            missing.add(relative)
    return sorted(missing)


def _unlink_known_shares(worktree: Path) -> list[str]:
    """Unlink every known share that is still a link; return their relative paths."""

    removed: list[str] = []
    for share in SHARES:
        if share.mode != "link":
            continue
        if "*" in share.relative:
            candidates = sorted(worktree.glob(share.relative))
        else:
            candidate = worktree / share.relative
            candidates = [candidate] if (candidate.exists() or is_link(candidate)) else []
        for path in candidates:
            if not is_link(path):
                continue
            remove_link(path)
            removed.append(path.relative_to(worktree).as_posix())
    return removed


# ---------------------------------------------------------------------------
# Worktree state helpers


def dirty_files(worktree: Path) -> list[str]:
    output = git_ok("status", "--porcelain", cwd=worktree)
    if output is None:
        raise WorktreeError(f"无法读取工作树状态: {worktree}")
    rows: list[str] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        # .worktree/ 是本脚本自己的目录：即使 .gitignore 漏了它，也不该因此
        # 阻塞合并（否则每台新机器第一次合并都会误报主工作树有未提交改动）。
        path = line[3:].strip().strip('"')
        if path.rstrip("/") == WORKTREE_DIR:
            continue
        rows.append(line)
    return rows


def tracked_changes(worktree: Path) -> list[str]:
    """Porcelain rows for modified/deleted tracked files (untracked noise excluded)."""

    return [line for line in dirty_files(worktree) if not line.startswith("??")]


def find_worktree(
    repo: Repo, *, path: Path | None = None, branch: str | None = None
) -> WorktreeEntry | None:
    for entry in repo.worktrees:
        if path is not None and _same_path(entry.path, path):
            return entry
        if branch is not None and entry.branch == branch:
            return entry
    return None


def _branch_exists(repo: Repo, branch: str) -> bool:
    return (
        git_ok("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", cwd=repo.main)
        is not None
    )


def _ensure_base_branch(repo: Repo, base: str) -> None:
    if not _branch_exists(repo, base):
        raise WorktreeError(f"基线分支不存在: {base}（先用 git branch 确认分支名）")


# ---------------------------------------------------------------------------
# add


def cmd_add(repo: Repo, args: argparse.Namespace) -> int:
    branch: str = args.branch
    base: str = args.base

    if branch == BASE_BRANCH:
        raise WorktreeError(f"{BASE_BRANCH} 是集成分支，不能为它创建工作树")
    check = _run(["git", "check-ref-format", "--branch", branch], cwd=repo.main)
    if check.returncode != 0:
        raise WorktreeError(f"分支名不合法: {branch}")

    directory = branch.replace("/", "-")
    worktree = repo.wt_root / directory
    if worktree.exists() or is_link(worktree):
        existing = find_worktree(repo, path=worktree)
        if existing is not None and existing.branch:
            raise WorktreeError(
                f"工作树目录已存在: {worktree}（对应分支 {existing.branch}）；"
                f"先合并/删除它（remove {directory}），或换一个分支名"
            )
        raise WorktreeError(
            f"工作树目录已存在: {worktree}（未在 git 注册，可能是上次删除的残留；"
            f"可运行 remove {directory} 清理）"
        )

    repo.wt_root.mkdir(parents=True, exist_ok=True)

    _note("=== 创建工作树 ===")
    if _branch_exists(repo, branch):
        _note(f"  分支 {branch} 已存在，直接检出")
        run_git("worktree", "add", str(worktree), branch, cwd=repo.main)
    else:
        _ensure_base_branch(repo, base)
        _note(f"  从 {base} 切出新分支 {branch}")
        run_git("worktree", "add", "-b", branch, str(worktree), base, cwd=repo.main)
    head = run_git("rev-parse", "--short", "HEAD", cwd=worktree)
    _note(f"  目录 {worktree}（{branch} @ {head}）")

    ignore_check = git_ok("check-ignore", "-q", WORKTREE_DIR, cwd=repo.main)
    if ignore_check is None:
        _warn(
            f"{WORKTREE_DIR}/ 没有被 .gitignore 忽略，git status 会看到工作树目录；"
            f"请把它加进 .gitignore（或本仓库尚未合并该改动）"
        )

    share_problems = False
    if args.share:
        _note("=== 复用主工作树的依赖与本地配置 ===")
        done, problems = apply_shares(repo, worktree, refresh=False)
        for line in done:
            _note(f"  {line}")
        if not done:
            _note("  没有需要共享的目录（可能已就绪）")
        for problem in problems:
            _warn(problem)
        share_problems = bool(problems)
        _report_venv(worktree)
        _warn_missing(repo, worktree)
    else:
        _warn("已跳过依赖共享（--no-share）；需要时运行 python scripts/worktree.py link")

    if args.build:
        _prepare_build(worktree)

    _print_next_steps(branch, worktree, base)
    if share_problems:
        _warn(
            "工作树已创建，但共享依赖没有全部就绪；按上面的提示修复后运行 "
            "python scripts/worktree.py link，失败前不要把它当成可用环境"
        )
        return 1
    return 0


def _report_venv(worktree: Path) -> None:
    python = venv_python(worktree)
    if not python.is_file():
        _warn(
            "主工作树没有可用的 .venv；新工作树暂时不能跑测试。"
            '先在主工作树准备环境（双击 start.cmd 或 pip install -e ".[dev]"），再运行 link'
        )
        return
    try:
        completed = _run([str(python), "-V"], cwd=worktree, timeout=120)
    except WorktreeError as exc:
        _warn(f"共享的 .venv 无法运行: {exc}")
        return
    if completed.returncode != 0:
        _warn(f"共享的 .venv 无法运行: {(completed.stderr or completed.stdout).strip()}")
        return
    version = (completed.stdout or completed.stderr).strip()
    _note(f"  环境  {version}（复用主工作树 .venv）")


def _warn_missing(repo: Repo, worktree: Path) -> None:
    missing = missing_shares(repo, worktree)
    if missing:
        _warn(
            "以下共享项在创建时仍缺失（可稍后运行 python scripts/worktree.py link 补齐）: "
            + ", ".join(missing)
        )


def _prepare_build(worktree: Path) -> None:
    _note("=== 预构建课程包（顺便验证工作树可用） ===")
    python = venv_python(worktree)
    script = worktree / "scripts" / "build_courses.py"
    if not python.is_file() or not script.is_file():
        _warn(
            "缺少 .venv 或 scripts/build_courses.py，跳过预构建；准备环境后运行 python scripts/build_courses.py --all"
        )
        return
    started = time.monotonic()
    try:
        completed = _run([str(python), str(script), "--all"], cwd=worktree, timeout=1800)
    except WorktreeError as exc:
        _warn(f"预构建课程包失败（工作树本身可用）: {exc}")
        return
    elapsed = time.monotonic() - started
    if completed.returncode != 0:
        _warn("预构建课程包失败（工作树本身可用）:\n" + _tail(completed.stdout + completed.stderr))
        return
    _note(f"  已构建 dist/（{elapsed:.0f} 秒）")


def _print_next_steps(branch: str, worktree: Path, base: str) -> None:
    merge_choice = "" if base == BASE_BRANCH else f" --base {base}"
    _note("")
    _note("=== 完成 ===")
    _note(f"  工作树: {worktree}")
    _note(f"  分支:   {branch}")
    _note("")
    _note("下一步:")
    _note(f'  cd "{worktree}"')
    _note("  python -m pytest -q && ruff check .        # 与主工作树相同的验收命令")
    _note(
        f"  python scripts/worktree.py merge {branch}{merge_choice} --remove"
        f"   # 验证 + 合并回 {base} + 清理"
    )
    _note("")
    _note("提醒:")
    _note(
        "  1. 不要在 worktree 里 pip install / npm install：依赖目录是共享的，会波及主工作树和其它会话"
    )
    _note("  2. 删除工作树用 python scripts/worktree.py remove，不要手工删目录")
    _note("     （目录联接被递归删除时可能跟随到主工作树的目标目录）")
    _note("  3. 有未提交改动时 remove 会拒绝；确认要丢弃才加 --force")
    _note("  4. 工作树里启动站点请换端口，避免和主工作树抢 8081：")
    _note("     PowerShell: $env:APP_PORT=8082    CMD: set APP_PORT=8082")
    _note("  5. 构建/测试产物（dist/、data/、缓存）都是工作树私有的，不会影响主工作树")


# ---------------------------------------------------------------------------
# list


def cmd_list(repo: Repo, _args: argparse.Namespace) -> int:
    _note(f"工作树列表（主工作树: {repo.main}）")
    for entry in repo.worktrees:
        label = "主" if repo.is_main(entry.path) else "树"
        _note(f"  [{label}] {entry.path}")
        detail: list[str] = [entry.branch or "(detached HEAD)"]
        if not entry.path.is_dir():
            detail.append("目录不存在（可运行 remove 清理注册记录）")
        else:
            try:
                changes = dirty_files(entry.path)
            except WorktreeError:
                changes = []
            detail.append("工作区干净" if not changes else f"{len(changes)} 项未提交改动")
            if not repo.is_main(entry.path):
                missing = missing_shares(repo, entry.path)
                if missing:
                    detail.append("共享缺失: " + ", ".join(missing))
        _note("       " + " · ".join(detail))

    registered = {entry.path for entry in repo.worktrees}
    if repo.wt_root.is_dir():
        leftovers = [
            candidate
            for candidate in sorted(repo.wt_root.iterdir())
            if candidate.is_dir() and not any(_same_path(candidate, known) for known in registered)
        ]
        for candidate in leftovers:
            _note(f"  [残留] {candidate}")
            _note("       未在 git 注册（上次删除可能中断）；可运行 remove 清理")

    _note("")
    _note(
        "新增: python scripts/worktree.py add <分支>    删除: python scripts/worktree.py remove <名字>"
    )
    return 0


# ---------------------------------------------------------------------------
# link


def _resolve_registered(repo: Repo, name: str | None) -> WorktreeEntry:
    if name is None:
        entry = find_worktree(repo, path=repo.current)
        if entry is None:
            raise WorktreeError(
                "当前目录不在任何已注册的工作树里；请在目标工作树里运行，或显式给出名字"
            )
        return entry
    candidate = Path(name)
    if candidate.is_absolute() or candidate.parent != Path("."):
        entry = find_worktree(repo, path=candidate)
        if entry is not None:
            return entry
    if "/" in name:
        entry = find_worktree(repo, branch=name)
        if entry is not None:
            return entry
        raise WorktreeError(f"没有分支 {name} 的工作树")
    entry = find_worktree(repo, path=repo.wt_root / name)
    if entry is not None:
        return entry
    entry = find_worktree(repo, branch=name)
    if entry is not None:
        return entry
    raise WorktreeError(f"找不到工作树: {name}（用 list 查看）")


def cmd_link(repo: Repo, args: argparse.Namespace) -> int:
    if args.all:
        targets = [entry for entry in repo.worktrees if not repo.is_main(entry.path)]
        if not targets:
            _note("没有其它工作树")
            return 0
    else:
        targets = [_resolve_registered(repo, args.name)]

    failed = False
    for entry in targets:
        _note(f"=== 补齐共享: {entry.path} ===")
        if not entry.path.is_dir():
            _warn(f"工作树目录不存在: {entry.path}")
            failed = True
            continue
        if repo.is_main(entry.path):
            _note("  这是主工作树，不需要共享")
            continue
        done, problems = apply_shares(repo, entry.path, refresh=True)
        for line in done:
            _note(f"  {line}")
        for problem in problems:
            _warn(problem)
        if not done and not problems:
            _note("  已就绪，无需改动")
        failed = failed or bool(problems)
        _report_venv(entry.path)
    return 1 if failed else 0


# ---------------------------------------------------------------------------
# remove / merge


def _registered_now(repo: Repo, path: Path) -> bool:
    """Ask git right now (the Repo snapshot can be stale after a failed delete)."""

    entries = _parse_worktree_list(run_git("worktree", "list", "--porcelain", cwd=repo.main))
    return any(_same_path(entry.path, path) for entry in entries)


def _remove_worktree(
    repo: Repo,
    entry: WorktreeEntry,
    *,
    delete_branch: bool,
    force: bool = True,
    merged_into: str | None = None,
) -> bool:
    """Delete one worktree; return False when requested cleanup could not finish."""

    path = entry.path
    if repo.is_main(path):
        raise WorktreeError(
            "拒绝删除主工作树；如果这个分支正检出在主工作树，先把它切回集成分支再操作"
        )
    if _same_path(path, repo.current):
        raise WorktreeError("当前 shell 正停留在要删除的工作树里；请先 cd 到主工作树再执行 remove")

    if path.exists() and not force:
        changes = dirty_files(path)
        if changes:
            preview = "\n".join(f"    {line}" for line in changes[:10])
            raise WorktreeError(
                f"工作树有未提交改动，拒绝删除（先提交/清理，或加 --force 丢弃）: {path}\n{preview}"
            )

    _note("=== 删除工作树 ===")
    if not path.exists():
        run_git("worktree", "prune", cwd=repo.main)
        _note(f"  工作树目录已不存在，已清理 git 注册记录: {path}")
    else:
        for relative in _unlink_known_shares(path):
            _note(f"  已拆除共享: {relative}")
        leftovers = find_reparse_points(path)
        if leftovers:
            detail = "\n".join(f"    {item}" for item in leftovers)
            raise WorktreeError(
                "目录里仍有未识别的目录联接/软链接，拒绝递归删除"
                "（不同工具可能跟随联接删到目标目录）。\n"
                f"请先确认并手工拆除，再重试:\n{detail}"
            )
        completed = _run(["git", "worktree", "remove", "--force", str(path)], cwd=repo.main)
        if completed.returncode != 0:
            if _registered_now(repo, path):
                raise WorktreeError(
                    "git worktree remove 失败，工作树仍处于注册状态；"
                    "确认没有编辑器/终端/MSBuild 停留在里面后重试：\n"
                    + _tail(completed.stderr or completed.stdout)
                )
            _warn(
                "git worktree remove 未能删除目录（多为被占用），改为删除残留目录：\n"
                + _tail(completed.stderr or completed.stdout)
            )
            _rmtree_with_retries(path)
        run_git("worktree", "prune", cwd=repo.main)
        _note(f"  已删除: {path}")

    branch_ok = True
    if delete_branch:
        branch = entry.branch
        if not branch:
            _warn("这是 detached HEAD 工作树，没有分支可删除")
        elif merged_into:
            branch_ok = _delete_branch_if_merged(repo, branch, merged_into)
        else:
            completed = _run(["git", "branch", "-d", branch], cwd=repo.main)
            if completed.returncode != 0:
                branch_ok = False
                _warn(
                    f"分支 {branch} 未删除（可能仍未合并）；确认后可用 git branch -D {branch}\n"
                    + _tail(completed.stderr or completed.stdout)
                )
            else:
                _note(f"  已删除分支: {branch}")
    elif entry.branch:
        _note(f"  分支 {entry.branch} 保留；合并后可用 git branch -d {entry.branch} 删除")
    return branch_ok


def _rmtree_with_retries(path: Path) -> None:
    for attempt in range(1, 4):
        try:
            shutil.rmtree(path)
            return
        except OSError:
            if attempt == 3:
                raise WorktreeError(
                    f"残留目录仍未删除: {path}（常见原因是终端/编辑器还停在里面，退出后手工删除即可）"
                ) from None
            time.sleep(1)


def _is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except (OSError, ValueError):
        return False


@dataclass
class RemovalTarget:
    """What ``remove`` was asked to delete: a registered worktree or a leftover dir."""

    path: Path
    entry: WorktreeEntry | None = None
    branch: str | None = None


def _delete_branch_if_merged(repo: Repo, branch: str, into: str) -> bool:
    merged = git_ok("merge-base", "--is-ancestor", branch, into, cwd=repo.main) is not None
    if not merged:
        _warn(f"分支 {branch} 还没有完全合并进 {into}，未删除；确认后可用 git branch -D {branch}")
        return False
    completed = _run(["git", "branch", "-D", branch], cwd=repo.main)
    if completed.returncode == 0:
        _note(f"  已删除分支: {branch}")
        return True
    _warn(f"分支 {branch} 删除失败；确认后可用 git branch -D {branch}")
    return False


def _cleanup_orphan(repo: Repo, path: Path) -> None:
    """Remove a directory under ``.worktree/`` that git no longer registers.

    This is the state left behind when a previous ``remove`` was interrupted by a
    file lock: git dropped the registration but the directory (and its links)
    survived. Only touched after the same link-safety checks as a normal remove.
    """

    if repo.is_main(path) or _same_path(path, repo.current):
        raise WorktreeError("拒绝删除主工作树或当前工作树")
    if not _is_under(path, repo.wt_root):
        raise WorktreeError(f"{path} 不在 {repo.wt_root} 下，拒绝删除")
    if not (path.exists() or is_link(path)):
        raise WorktreeError(f"找不到工作树目录: {path}")

    _note("=== 清理未注册的残留目录 ===")
    for relative in _unlink_known_shares(path):
        _note(f"  已拆除共享: {relative}")
    leftovers = find_reparse_points(path)
    if leftovers:
        detail = "\n".join(f"    {item}" for item in leftovers)
        raise WorktreeError(
            f"残留目录里仍有未识别的目录联接/软链接，拒绝递归删除；请先确认并手工拆除:\n{detail}"
        )
    _rmtree_with_retries(path)
    _note(f"  已清理: {path}（git 已不再登记它）")


def _resolve_removable(repo: Repo, name: str) -> RemovalTarget:
    candidate = Path(name)
    if candidate.is_absolute() or candidate.parent != Path("."):
        path = candidate if candidate.is_absolute() else Path.cwd() / candidate
        entry = find_worktree(repo, path=path)
        if entry is not None:
            return RemovalTarget(entry.path, entry, entry.branch)
        if path.exists() or is_link(path):
            if not _is_under(path, repo.wt_root):
                raise WorktreeError(f"{path} 不在 {repo.wt_root} 下，拒绝删除")
            return RemovalTarget(path)
        raise WorktreeError(f"找不到工作树目录: {path}")

    # 分支名优先：feat/a-b 与 feat/a/b 都会映射到 feat-a-b，先按分支找。
    entry = find_worktree(repo, branch=name)
    if entry is not None:
        return RemovalTarget(entry.path, entry, entry.branch)

    # 目录名按原样匹配，不做 "/" 到 "-" 的模糊映射：否则 remove feat/a/b
    # 可能删掉分支 feat/a-b 的工作树。目录名（feat-a-b）始终可用。
    path = repo.wt_root / name
    entry = find_worktree(repo, path=path)
    if entry is not None:
        return RemovalTarget(entry.path, entry, entry.branch)
    if path.exists() or is_link(path):
        return RemovalTarget(path)
    raise WorktreeError(f"找不到工作树: {name}（用 list 查看；目录名是分支名把 / 换成 -）")


def cmd_remove(repo: Repo, args: argparse.Namespace) -> int:
    target = _resolve_removable(repo, args.name)
    if target.entry is None:
        _cleanup_orphan(repo, target.path)
        return 0
    removed = _remove_worktree(
        repo,
        target.entry,
        delete_branch=args.delete_branch,
        force=args.force,
    )
    return 0 if removed else 1


def _find_ruff(repo: Repo, worktree: Path) -> str | None:
    names = ("ruff.exe",) if os.name == "nt" else ("ruff",)
    for root in (worktree, repo.main):
        venv = root / ".venv"
        for name in names:
            for sub in ("Scripts", "bin"):
                candidate = venv / sub / name
                if candidate.is_file():
                    return str(candidate)
    return shutil.which("ruff")


def _verify_worktree(repo: Repo, worktree: Path) -> None:
    python = venv_python(worktree)
    if not python.is_file():
        python = Path(sys.executable)
    steps: list[tuple[str, list[str]]] = [("pytest -q", [str(python), "-m", "pytest", "-q"])]
    ruff = _find_ruff(repo, worktree)
    if ruff:
        steps.append(("ruff check .", [ruff, "check", "."]))
    else:
        _warn("找不到 ruff，跳过代码检查（可先在主工作树准备 .venv）")

    _note("=== 合并前验证（在工作树里） ===")
    failures: list[str] = []
    for label, command in steps:
        _note(f"  {label} ... ", end="")
        try:
            completed = _run(command, cwd=worktree, timeout=1800)
        except WorktreeError as exc:
            failures.append(f"{label}: {exc}")
            _note("失败")
            continue
        if completed.returncode != 0:
            failures.append(f"{label} 失败:\n{_tail(completed.stdout + completed.stderr)}")
            _note("失败")
        else:
            _note("通过")
    if failures:
        raise WorktreeError(
            "合并前验证未通过，先在工作树里修好再合并（或加 --no-verify 跳过）:\n\n"
            + "\n\n".join(failures)
        )


def _remove_temp_worktree(repo: Repo, path: Path) -> None:
    completed = _run(["git", "worktree", "remove", "--force", str(path)], cwd=repo.main)
    if completed.returncode != 0 and path.exists():
        leftovers = find_reparse_points(path)
        if leftovers:
            _warn(f"临时合并目录里仍有联接，未自动删除: {path}")
        else:
            _rmtree_with_retries(path)
    run_git("worktree", "prune", cwd=repo.main)


def _abort_merge_if_in_progress(merge_cwd: Path) -> str:
    """Roll back a conflicted merge; return a human readable outcome."""

    merge_head = run_git("rev-parse", "--git-path", "MERGE_HEAD", cwd=merge_cwd).strip()
    merge_head_path = Path(merge_head)
    if not merge_head_path.is_absolute():
        merge_head_path = merge_cwd / merge_head_path
    if not merge_head_path.exists():
        return ""
    completed = _run(["git", "merge", "--abort"], cwd=merge_cwd)
    if completed.returncode == 0:
        return f"已在 {merge_cwd} 自动执行 git merge --abort，没有留下冲突状态。"
    return f"自动 git merge --abort 失败，请到 {merge_cwd} 手工执行 git merge --abort：\n" + _tail(
        completed.stdout + completed.stderr
    )


def cmd_merge(repo: Repo, args: argparse.Namespace) -> int:
    branch: str = args.branch
    base: str = args.base
    if branch == base:
        raise WorktreeError("不能把分支合并到它自己")
    if not _branch_exists(repo, branch):
        raise WorktreeError(f"分支不存在: {branch}")
    _ensure_base_branch(repo, base)

    branch_entry = find_worktree(repo, branch=branch)
    base_entry = find_worktree(repo, branch=base)

    if branch_entry is not None and branch_entry.path.is_dir():
        changes = dirty_files(branch_entry.path)
        if changes:
            preview = "\n".join(f"    {line}" for line in changes[:10])
            raise WorktreeError(
                f"工作树有未提交改动，先提交或清理再合并: {branch_entry.path}\n{preview}"
            )
    if args.remove and branch_entry is not None and _same_path(branch_entry.path, repo.current):
        raise WorktreeError(
            "当前 shell 正停留在要删除的工作树里；请先 cd 到主工作树，再执行 merge --remove"
        )
    if args.remove and branch_entry is not None and repo.is_main(branch_entry.path):
        raise WorktreeError(
            f"分支 {branch} 正检出在主工作树里，合并后无法删除它。"
            f"先在主工作树切回 {base}（git checkout {base}）再重试，或去掉 --remove"
        )

    merge_cwd: Path | None = None
    if base_entry is not None and base_entry.path.is_dir():
        changes = dirty_files(base_entry.path)
        if changes:
            preview = "\n".join(f"    {line}" for line in changes[:10])
            raise WorktreeError(
                f"{base} 检出在 {base_entry.path}，但有未提交改动；先处理干净再合并"
                f"（不要抢其它会话正在用的工作树）:\n{preview}"
            )
        merge_cwd = base_entry.path

    if args.verify:
        if branch_entry is not None and branch_entry.path.is_dir():
            _verify_worktree(repo, branch_entry.path)
            # 验证命令不应改动已跟踪的文件；改动了说明“验证过的状态”和“提交的状态”不一致。
            # 未跟踪的测试缓存（__pycache__ 等）不算，仓库的 .gitignore 会忽略它们。
            changes = tracked_changes(branch_entry.path)
            if changes:
                preview = "\n".join(f"    {line}" for line in changes[:10])
                raise WorktreeError(
                    f"验证过程修改了工作树，先确认并处理再合并: {branch_entry.path}\n{preview}"
                )
        else:
            raise WorktreeError(
                "分支没有检出到工作树，无法执行默认的合并前验证。\n"
                "  先为它开工作树（add）再合并；确实已经验证过，才加 --no-verify 跳过"
            )

    ahead_text = run_git("rev-list", "--count", f"{base}..{branch}", cwd=repo.main).strip()
    ahead = int(ahead_text or 0)
    if ahead == 0:
        _note(f"注意: {base} 已包含 {branch} 的全部提交（合并是空操作）")

    temp_path: Path | None = None
    if merge_cwd is None:
        temp_path = repo.wt_root / f"_merge-{base.replace('/', '-')}"
        if temp_path.exists():
            raise WorktreeError(
                f"临时合并目录已存在: {temp_path}；可能上次中断，确认后手工删除再重试"
            )
        repo.wt_root.mkdir(parents=True, exist_ok=True)
        run_git("worktree", "add", str(temp_path), base, cwd=repo.main)
        merge_cwd = temp_path

    non_ff = False
    _note("=== 合并 ===")
    try:
        completed = _run(["git", "merge", "--ff-only", branch], cwd=merge_cwd)
        if completed.returncode != 0:
            if not args.merge:
                raise WorktreeError(
                    f"无法快进合并: {base} 上已有 {branch} 没有的提交。\n"
                    f"  先在工作树里同步基线再重试: git -C <工作树> merge {base}\n"
                    "  或加 --merge 生成合并提交（合并后要在主工作树重跑验证）"
                )
            _note("  基线已前进，生成合并提交（--merge）")
            completed = _run(
                ["git", "merge", "--no-ff", "-m", f"merge: 合并 {branch} 到 {base}", branch],
                cwd=merge_cwd,
            )
            if completed.returncode != 0:
                rollback = _abort_merge_if_in_progress(merge_cwd)
                raise WorktreeError(
                    "合并提交失败（冲突），已尝试回滚。"
                    + (f"\n{rollback}" if rollback else "")
                    + f"\n先在工作树里 git merge {base} 并解决冲突、提交后再重试，"
                    "或确认 --merge 是否必要：\n" + _tail(completed.stdout + completed.stderr)
                )
            non_ff = True
        _note(f"  {branch} -> {base}（{ahead} 个提交）")
    finally:
        if temp_path is not None:
            _remove_temp_worktree(repo, temp_path)

    cleanup_ok = True
    if args.remove:
        if branch_entry is not None:
            cleanup_ok = _remove_worktree(
                repo,
                branch_entry,
                delete_branch=True,
                force=True,
                merged_into=base,
            )
        else:
            cleanup_ok = _delete_branch_if_merged(repo, branch, base)

    head_info = git_ok("log", "--oneline", "-1", base, cwd=repo.main) or ""
    _note("")
    _note("=== 合并完成 ===")
    _note(f"  {base} 当前提交: {head_info}")
    if non_ff:
        _warn(
            "非快进合并生成了合并提交；合并前的验证没有覆盖基线合入后的结果，"
            "请在主工作树再跑一遍 python -m pytest -q 与 ruff check ."
        )
    _note("  主工作树现在包含这些改动；若站点正在运行，重建 dist/ 并重启后再看效果。")
    if not cleanup_ok:
        _warn("合并已完成，但工作树/分支清理没有全部完成；按上面的提示处理后收尾")
        return 1
    return 0


# ---------------------------------------------------------------------------
# CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python scripts/worktree.py",
        description="git 工作树助手：每个任务一个工作区，复用主工作树的依赖",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="创建工作树（默认从 main 切出）")
    add.add_argument("branch", help="分支名，如 feat/course-xyz 或 fix/player-crash")
    add.add_argument("--base", default=BASE_BRANCH, help=f"基线分支（默认 {BASE_BRANCH}）")
    add.add_argument(
        "--share",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="共享主工作树的依赖与本地配置（默认开启）",
    )
    add.add_argument(
        "--build",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="创建工作树后预构建课程包（默认开启）",
    )
    add.set_defaults(func=cmd_add)

    listing = sub.add_parser("list", help="列出工作树与共享状态")
    listing.set_defaults(func=cmd_list)

    link = sub.add_parser("link", help="补齐/修复工作树的共享依赖（刷新复制类共享）")
    link.add_argument("name", nargs="?", help="工作树名字或分支名（默认当前工作树）")
    link.add_argument("--all", action="store_true", help="处理所有工作树")
    link.set_defaults(func=cmd_link)

    remove = sub.add_parser("remove", help="删除工作树（默认保留分支；有未提交改动会拒绝）")
    remove.add_argument("name", help="工作树目录名（如 feat-x）、分支名（feat/x）或路径")
    remove.add_argument("--delete-branch", action="store_true", help="同时删除已合并的分支")
    remove.add_argument(
        "--force",
        action="store_true",
        help="丢弃工作树里未提交的改动，强制删除",
    )
    remove.set_defaults(func=cmd_remove)

    merge = sub.add_parser("merge", help="验证并合并回集成分支（需要分支有工作树）")
    merge.add_argument("branch", help="要合并的工作分支")
    merge.add_argument("--base", default=BASE_BRANCH, help=f"集成分支（默认 {BASE_BRANCH}）")
    merge.add_argument(
        "--verify",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="合并前在工作树里跑 pytest 与 ruff（默认开启）",
    )
    merge.add_argument(
        "--remove",
        action="store_true",
        help="合并成功后删除工作树与分支",
    )
    merge.add_argument(
        "--merge",
        action="store_true",
        help="允许在无法快进时生成合并提交（默认只允许快进）",
    )
    merge.set_defaults(func=cmd_merge)
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        repo = discover_repo()
        return int(args.func(repo, args))
    except WorktreeError as exc:
        print(f"错误: {exc}", file=sys.stderr, flush=True)
        return 1
    except KeyboardInterrupt:
        print("已中断", file=sys.stderr, flush=True)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
