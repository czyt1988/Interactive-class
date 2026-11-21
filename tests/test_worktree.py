"""Tests for ``scripts/worktree.py``: create, share, list, remove and merge.

The worktree helper is what keeps parallel sessions off the main checkout, so its
safety rules are worth pinning down: shared dependencies must never be deleted
with the worktree, the main worktree must be untouchable, and merging must refuse
a dirty tree.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts import worktree

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="需要 git")

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "AI Learning Tests",
    "GIT_AUTHOR_EMAIL": "tests@example.invalid",
    "GIT_COMMITTER_NAME": "AI Learning Tests",
    "GIT_COMMITTER_EMAIL": "tests@example.invalid",
}

# 隔离本机 git 全局配置：签名、hook、默认分支等设置不能让测试时好时坏。
GIT_ISOLATION = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
}


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, **GIT_IDENTITY, **GIT_ISOLATION},
    )
    return completed.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    for name, value in {**GIT_ISOLATION, **GIT_IDENTITY}.items():
        monkeypatch.setenv(name, value)
    _git(root, "init")
    _git(root, "symbolic-ref", "HEAD", "refs/heads/main")
    (root / "README.md").write_text("# demo\n", encoding="utf-8")
    (root / ".gitignore").write_text(
        ".worktree/\n.venv/\n.env\nruntime/vendor/\ntools/node_modules/\ntools/ffmpeg/\ncourses/\n",
        encoding="utf-8",
    )
    _git(root, "add", "README.md", ".gitignore")
    _git(root, "commit", "-m", "init")
    monkeypatch.chdir(root)
    return root


def _call(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = worktree.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _local_dependencies(repo: Path) -> None:
    """Untracked, machine-local directories that a worktree must share."""

    player = repo / "tools" / "node_modules" / "hyperframes" / "dist"
    player.mkdir(parents=True)
    (player / "hyperframes-player.global.js").write_text("// player\n", encoding="utf-8")
    ffmpeg = repo / "tools" / "ffmpeg"
    ffmpeg.mkdir(parents=True)
    (ffmpeg / "ffmpeg.exe").write_text("stub\n", encoding="utf-8")
    venv = repo / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    venv.mkdir(parents=True)
    (repo / ".env").write_text("APP_PORT=8082\n", encoding="utf-8")
    vendor = repo / "runtime" / "vendor"
    vendor.mkdir(parents=True)
    (vendor / "hyperframes-player.global.js").write_text("// v1\n", encoding="utf-8")
    cache = repo / "courses" / "demo" / "narration" / "cache"
    cache.mkdir(parents=True)
    (cache / "abc.ogg").write_text("ogg\n", encoding="utf-8")


def test_add_creates_worktree_and_shares_dependencies(repo, capsys) -> None:
    _local_dependencies(repo)

    code, out, err = _call(capsys, "add", "feat/demo")
    assert code == 0, err

    worktree_dir = repo / ".worktree" / "feat-demo"
    assert (worktree_dir / ".git").is_file()
    assert _git(worktree_dir, "branch", "--show-current") == "feat/demo"
    assert (worktree_dir / "README.md").read_text(encoding="utf-8") == "# demo\n"

    # 依赖是目录联接/软链接，内容立刻可用，但没有重新下载或复制。
    assert worktree.is_link(worktree_dir / ".venv")
    assert worktree.is_link(worktree_dir / "tools" / "node_modules")
    assert worktree.is_link(worktree_dir / "tools" / "ffmpeg")
    assert worktree.is_link(worktree_dir / "courses" / "demo" / "narration" / "cache")
    assert (worktree_dir / "tools" / "node_modules" / "hyperframes" / "dist").is_dir()
    # 本地配置是复制，各工作树一份。
    assert not worktree.is_link(worktree_dir / ".env")
    assert (worktree_dir / ".env").read_text(encoding="utf-8") == "APP_PORT=8082\n"

    code, out, _ = _call(capsys, "list")
    assert code == 0
    assert "feat/demo" in out


def test_shared_links_do_not_make_the_worktree_dirty(repo, capsys) -> None:
    """A generated dependency link is not a user change, on any platform.

    ``.gitignore`` 里的 ``.venv/`` 只匹配目录；POSIX 上共享的是符号链接，
    git 会把它报成未跟踪，``remove`` 就会误判成“有未提交改动”。共享路径必须
    写进 ``info/exclude``（本地、不进版本库、所有工作树共享）。
    """

    _local_dependencies(repo)
    assert _call(capsys, "add", "feat/demo", "--no-build")[0] == 0
    worktree_dir = repo / ".worktree" / "feat-demo"

    exclude = (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    for relative in (".venv", "tools/node_modules", "tools/ffmpeg"):
        assert f"/{relative}" in exclude
    assert _git(worktree_dir, "status", "--porcelain") == ""


def test_remove_keeps_main_dependency_targets(repo, capsys) -> None:
    _local_dependencies(repo)
    assert _call(capsys, "add", "feat/demo", "--no-build")[0] == 0
    worktree_dir = repo / ".worktree" / "feat-demo"

    code, out, err = _call(capsys, "remove", "feat-demo")
    assert code == 0, err
    assert not worktree_dir.exists()
    # 关键安全线：拆联接绝不能清空主工作树的目标目录。
    assert not worktree.is_link(repo / ".venv")
    assert (repo / ".venv").is_dir()
    assert (repo / "tools" / "node_modules" / "hyperframes" / "dist").is_dir()
    assert "feat/demo" in _git(repo, "branch", "--list", "feat/demo")
    assert _git(repo, "worktree", "list", "--porcelain").count("worktree ") == 1


def test_remove_refuses_main_worktree(repo, capsys) -> None:
    code, _, err = _call(capsys, "remove", str(repo))
    assert code == 1
    assert "主工作树" in err
    assert repo.is_dir()


def test_remove_refuses_directory_outside_worktree_root(repo, capsys) -> None:
    outside = repo / "manual"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep\n", encoding="utf-8")

    code, _, err = _call(capsys, "remove", str(outside))
    assert code == 1
    assert "不在" in err
    assert (outside / "keep.txt").is_file()


def test_add_existing_branch_checks_it_out(repo, capsys) -> None:
    _git(repo, "branch", "feat/existing")

    code, _, err = _call(capsys, "add", "feat/existing", "--no-share", "--no-build")
    assert code == 0, err
    worktree_dir = repo / ".worktree" / "feat-existing"
    assert _git(worktree_dir, "branch", "--show-current") == "feat/existing"
    assert not (worktree_dir / ".venv").exists()


def test_link_is_idempotent(repo, capsys) -> None:
    _local_dependencies(repo)
    assert _call(capsys, "add", "feat/demo", "--no-build")[0] == 0
    assert _call(capsys, "link", "feat-demo")[0] == 0
    assert _call(capsys, "link", "feat-demo")[0] == 0
    worktree_dir = repo / ".worktree" / "feat-demo"
    assert worktree.is_link(worktree_dir / ".venv")
    assert (repo / ".venv").is_dir()


def test_merge_fast_forwards_and_cleans_up(repo, capsys) -> None:
    assert _call(capsys, "add", "feat/demo", "--no-build")[0] == 0
    worktree_dir = repo / ".worktree" / "feat-demo"
    (worktree_dir / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(worktree_dir, "add", "feature.txt")
    _git(worktree_dir, "commit", "-m", "feat: add feature")

    code, _, err = _call(capsys, "merge", "feat/demo", "--no-verify", "--remove")
    assert code == 0, err
    assert (repo / "feature.txt").is_file()
    assert not worktree_dir.exists()
    assert "feat/demo" not in _git(repo, "branch", "--list", "feat/demo")
    assert _git(repo, "branch", "--show-current") == "main"


def test_merge_refuses_dirty_branch_worktree(repo, capsys) -> None:
    assert _call(capsys, "add", "feat/demo", "--no-build")[0] == 0
    worktree_dir = repo / ".worktree" / "feat-demo"
    (worktree_dir / "README.md").write_text("# dirty\n", encoding="utf-8")

    code, _, err = _call(capsys, "merge", "feat/demo", "--no-verify")
    assert code == 1
    assert "未提交" in err
    assert (repo / "README.md").read_text(encoding="utf-8") == "# demo\n"


def test_merge_refuses_dirty_base_worktree(repo, capsys) -> None:
    assert _call(capsys, "add", "feat/demo", "--no-build")[0] == 0
    worktree_dir = repo / ".worktree" / "feat-demo"
    (worktree_dir / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(worktree_dir, "add", "feature.txt")
    _git(worktree_dir, "commit", "-m", "feat: add feature")
    (repo / "README.md").write_text("# dirty main\n", encoding="utf-8")

    code, _, err = _call(capsys, "merge", "feat/demo", "--no-verify")
    assert code == 1
    assert "未提交" in err
    assert not (repo / "feature.txt").exists()


def test_merge_requires_ff_unless_merge_is_allowed(repo, capsys) -> None:
    assert _call(capsys, "add", "feat/demo", "--no-build")[0] == 0
    worktree_dir = repo / ".worktree" / "feat-demo"
    (worktree_dir / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(worktree_dir, "add", "feature.txt")
    _git(worktree_dir, "commit", "-m", "feat: add feature")

    (repo / "main-only.txt").write_text("main\n", encoding="utf-8")
    _git(repo, "add", "main-only.txt")
    _git(repo, "commit", "-m", "chore: main moves on")

    code, _, err = _call(capsys, "merge", "feat/demo", "--no-verify")
    assert code == 1
    assert "无法快进" in err

    code, _, err = _call(capsys, "merge", "feat/demo", "--no-verify", "--merge")
    assert code == 0, err
    assert (repo / "feature.txt").is_file()
    assert (repo / "main-only.txt").is_file()
    assert len(_git(repo, "rev-list", "--parents", "-1", "HEAD").split()) == 3


def test_merge_verify_runs_tests_and_merges(repo, capsys) -> None:
    assert _call(capsys, "add", "feat/demo", "--no-share", "--no-build")[0] == 0
    worktree_dir = repo / ".worktree" / "feat-demo"
    tests_dir = worktree_dir / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    _git(worktree_dir, "add", "tests/test_ok.py")
    _git(worktree_dir, "commit", "-m", "test: add smoke test")

    code, out, err = _call(capsys, "merge", "feat/demo")
    assert code == 0, err
    assert "通过" in out
    assert (repo / "tests" / "test_ok.py").is_file()


def test_merge_verify_blocks_failing_worktree(repo, capsys) -> None:
    assert _call(capsys, "add", "feat/demo", "--no-share", "--no-build")[0] == 0
    worktree_dir = repo / ".worktree" / "feat-demo"
    tests_dir = worktree_dir / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_fail.py").write_text(
        "def test_fail():\n    assert False\n", encoding="utf-8"
    )
    _git(worktree_dir, "add", "tests/test_fail.py")
    _git(worktree_dir, "commit", "-m", "test: add failing test")

    code, _, err = _call(capsys, "merge", "feat/demo")
    assert code == 1
    assert "合并前验证未通过" in err
    assert not (repo / "tests").exists()


def test_app_and_scripts_import_from_this_checkout() -> None:
    """共享 .venv 的 editable install 指向主工作树；本检出的导入不能被它劫持。"""

    import app
    import scripts

    root = Path(__file__).resolve().parent.parent
    assert Path(app.__file__).resolve().is_relative_to(root)
    assert Path(scripts.__file__).resolve().is_relative_to(root)


def test_console_pytest_imports_current_checkout() -> None:
    """pytest.exe 的 sys.path 里没有 cwd；仓库根 conftest.py 必须把它补上。"""

    root = Path(__file__).resolve().parent.parent
    if os.name == "nt":
        console = root / ".venv" / "Scripts" / "pytest.exe"
    else:
        console = root / ".venv" / "bin" / "pytest"
    if not console.is_file():
        pytest.skip("没有仓库 .venv 里的 pytest 控制台脚本")

    completed = subprocess.run(
        [str(console), "--collect-only", "-q", "tests/e2e/test_standalone.py"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_remove_refuses_dirty_worktree_unless_forced(repo, capsys) -> None:
    assert _call(capsys, "add", "feat/demo", "--no-share", "--no-build")[0] == 0
    worktree_dir = repo / ".worktree" / "feat-demo"
    (worktree_dir / "wip.txt").write_text("work in progress\n", encoding="utf-8")

    code, _, err = _call(capsys, "remove", "feat-demo")
    assert code == 1
    assert "未提交" in err
    assert (worktree_dir / "wip.txt").is_file()

    code, _, err = _call(capsys, "remove", "feat-demo", "--force")
    assert code == 0, err
    assert not worktree_dir.exists()


def test_remove_cleans_unregistered_leftover_directory(repo, capsys) -> None:
    leftover = repo / ".worktree" / "feat-gone"
    leftover.mkdir(parents=True)
    (leftover / "keep.txt").write_text("leftover\n", encoding="utf-8")

    code, _, err = _call(capsys, "remove", "feat-gone")
    assert code == 0, err
    assert not leftover.exists()

    code, out, _ = _call(capsys, "list")
    assert code == 0
    assert "[残留]" not in out


def test_remove_cleans_dangling_shares_then_directory(repo, capsys) -> None:
    _local_dependencies(repo)
    assert _call(capsys, "add", "feat/demo", "--no-build")[0] == 0
    worktree_dir = repo / ".worktree" / "feat-demo"
    (repo / ".venv").rename(repo / ".venv-moved")  # 目标消失，工作树里的联接悬空

    code, out, _ = _call(capsys, "list")
    assert code == 0
    assert "共享缺失" in out

    code, _, err = _call(capsys, "remove", "feat-demo", "--force")
    assert code == 0, err
    assert not worktree_dir.exists()
    assert not worktree.is_link(repo / ".venv")
    assert (repo / "tools" / "node_modules" / "hyperframes" / "dist").is_dir()


def test_add_dir_name_collision_mentions_existing_branch(repo, capsys) -> None:
    assert _call(capsys, "add", "feat/a-b", "--no-share", "--no-build")[0] == 0

    code, _, err = _call(capsys, "add", "feat/a/b", "--no-share", "--no-build")
    assert code == 1
    assert "feat/a-b" in err


def test_link_refreshes_copied_shares(repo, capsys) -> None:
    _local_dependencies(repo)
    assert _call(capsys, "add", "feat/demo", "--no-build")[0] == 0
    worktree_dir = repo / ".worktree" / "feat-demo"
    assert (worktree_dir / "runtime" / "vendor" / "hyperframes-player.global.js").read_text(
        encoding="utf-8"
    ) == "// v1\n"

    (repo / "runtime" / "vendor" / "hyperframes-player.global.js").write_text(
        "// v2\n", encoding="utf-8"
    )
    (repo / ".env").write_text("APP_PORT=9999\n", encoding="utf-8")

    code, out, err = _call(capsys, "link", "feat-demo")
    assert code == 0, err
    assert "刷新" in out
    assert (worktree_dir / "runtime" / "vendor" / "hyperframes-player.global.js").read_text(
        encoding="utf-8"
    ) == "// v2\n"
    assert (worktree_dir / ".env").read_text(encoding="utf-8") == "APP_PORT=9999\n"


def test_link_repairs_dangling_share(repo, capsys) -> None:
    _local_dependencies(repo)
    assert _call(capsys, "add", "feat/demo", "--no-build")[0] == 0
    worktree_dir = repo / ".worktree" / "feat-demo"
    (repo / ".venv").rename(repo / ".venv-moved")

    code, _, err = _call(capsys, "link", "feat-demo")
    assert code == 1
    assert "失效" in err
    assert not worktree.is_link(worktree_dir / ".venv")

    (repo / ".venv-moved").rename(repo / ".venv")
    code, _, err = _call(capsys, "link", "feat-demo")
    assert code == 0, err
    assert worktree.is_link(worktree_dir / ".venv")


def test_link_reports_share_conflict_with_nonzero_exit(repo, capsys) -> None:
    _local_dependencies(repo)
    assert _call(capsys, "add", "feat/demo", "--no-share", "--no-build")[0] == 0
    worktree_dir = repo / ".worktree" / "feat-demo"
    conflict = worktree_dir / "tools" / "node_modules"
    conflict.mkdir(parents=True)
    (conflict / "mine.txt").write_text("keep\n", encoding="utf-8")

    code, _, err = _call(capsys, "link", "feat-demo")
    assert code == 1
    assert "已存在真实目录" in err
    assert (conflict / "mine.txt").is_file()


def test_merge_conflict_aborts_and_keeps_main_clean(repo, capsys) -> None:
    assert _call(capsys, "add", "feat/demo", "--no-share", "--no-build")[0] == 0
    worktree_dir = repo / ".worktree" / "feat-demo"
    (worktree_dir / "README.md").write_text("feature\n", encoding="utf-8")
    _git(worktree_dir, "add", "README.md")
    _git(worktree_dir, "commit", "-m", "feat: change readme")
    (repo / "README.md").write_text("main\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "chore: change readme on main")

    code, _, err = _call(capsys, "merge", "feat/demo", "--no-verify", "--merge")
    assert code == 1
    assert "回滚" in err
    assert _git(repo, "status", "--porcelain") == ""
    assert (repo / "README.md").read_text(encoding="utf-8") == "main\n"
    assert not (repo / ".git" / "MERGE_HEAD").exists()
    assert _git(worktree_dir, "status", "--porcelain") == ""


def test_merge_verify_requires_a_worktree(repo, capsys) -> None:
    assert _call(capsys, "add", "feat/demo", "--no-share", "--no-build")[0] == 0
    worktree_dir = repo / ".worktree" / "feat-demo"
    (worktree_dir / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(worktree_dir, "add", "feature.txt")
    _git(worktree_dir, "commit", "-m", "feat: add feature")
    assert _call(capsys, "remove", "feat-demo")[0] == 0

    code, _, err = _call(capsys, "merge", "feat/demo")
    assert code == 1
    assert "无法执行默认的合并前验证" in err
    assert not (repo / "feature.txt").exists()

    code, _, err = _call(capsys, "merge", "feat/demo", "--no-verify")
    assert code == 0, err
    assert (repo / "feature.txt").is_file()


def test_merge_remove_refuses_branch_checked_out_in_main_worktree(
    repo, monkeypatch, capsys
) -> None:
    assert _call(capsys, "add", "feat/demo", "--no-share", "--no-build")[0] == 0
    worktree_dir = repo / ".worktree" / "feat-demo"
    (worktree_dir / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(worktree_dir, "add", "feature.txt")
    _git(worktree_dir, "commit", "-m", "feat: add feature")
    assert _call(capsys, "remove", "feat-demo")[0] == 0
    _git(repo, "checkout", "feat/demo")
    main_before = _git(repo, "rev-parse", "refs/heads/main")

    assert _call(capsys, "add", "feat/helper", "--no-share", "--no-build")[0] == 0
    helper_dir = repo / ".worktree" / "feat-helper"
    monkeypatch.chdir(helper_dir)
    try:
        code, _, err = _call(capsys, "merge", "feat/demo", "--no-verify", "--remove")
    finally:
        monkeypatch.chdir(repo)
    assert code == 1
    assert "主工作树" in err
    assert _git(repo, "rev-parse", "refs/heads/main") == main_before
