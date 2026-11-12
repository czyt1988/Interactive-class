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


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, **GIT_IDENTITY},
    )
    return completed.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "symbolic-ref", "HEAD", "refs/heads/main")
    (root / "README.md").write_text("# demo\n", encoding="utf-8")
    (root / ".gitignore").write_text(".worktree/\n", encoding="utf-8")
    _git(root, "add", "README.md", ".gitignore")
    _git(root, "commit", "-m", "init")
    monkeypatch.chdir(root)
    for name, value in GIT_IDENTITY.items():
        monkeypatch.setenv(name, value)
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


def test_remove_refuses_plain_directory(repo, capsys) -> None:
    manual = repo / ".worktree" / "manual"
    manual.mkdir(parents=True)
    (manual / "keep.txt").write_text("keep\n", encoding="utf-8")

    code, _, err = _call(capsys, "remove", "manual")
    assert code == 1
    assert "不是 git 注册的工作树" in err
    assert (manual / "keep.txt").is_file()


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
