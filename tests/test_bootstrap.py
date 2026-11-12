from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from scripts import bootstrap, launcher, sync_runtime, worktree


def _venv(root: Path) -> Path:
    target = bootstrap.venv_python(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("", encoding="utf-8")
    return target


def _runtime_assets(root: Path) -> None:
    vendor = root / "runtime" / "vendor"
    vendor.mkdir(parents=True, exist_ok=True)
    for name in bootstrap.PLAYER_FILES:
        (vendor / name).write_text("", encoding="utf-8")
    (root / "runtime" / "VERSION.json").write_text("{}\n", encoding="utf-8")


def _dist(root: Path) -> None:
    (root / "dist" / "courses").mkdir(parents=True, exist_ok=True)
    (root / "dist" / "build.json").write_text("{}\n", encoding="utf-8")


def _tools(root: Path) -> None:
    hyperframes = root / "tools" / "node_modules" / "hyperframes" / "dist"
    hyperframes.mkdir(parents=True)
    for name in bootstrap.PLAYER_FILES:
        (hyperframes / name).write_text("", encoding="utf-8")
    gsap = root / "tools" / "node_modules" / "gsap" / "dist"
    gsap.mkdir(parents=True)
    (gsap / "gsap.min.js").write_text("", encoding="utf-8")


class Runner:
    """Stands in for ``bootstrap._run``: records commands and fakes side effects."""

    def __init__(
        self,
        root: Path,
        *,
        modules_ok: bool = True,
        interpreter_ok: bool = True,
        build_ok: bool = True,
    ) -> None:
        self.root = root
        self.calls: list[list[str]] = []
        self.modules_ok = modules_ok
        self.interpreter_ok = interpreter_ok
        self.build_ok = build_ok

    def __call__(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        timeout: float | None = None,
    ) -> bootstrap.CommandResult:
        text = [str(part) for part in command]
        joined = " ".join(text)
        self.calls.append(text)
        if "-c" in text and "sys.version_info" in joined:
            if not self.interpreter_ok:
                return bootstrap.CommandResult(1)
            return bootstrap.CommandResult(0, "3 11\n")
        if "-c" in text and "import " in joined:
            return bootstrap.CommandResult(0 if self.modules_ok else 1)
        if " -m venv " in f" {joined} ":
            _venv(self.root)
            return bootstrap.CommandResult(0)
        if "sync_runtime.py" in joined:
            _runtime_assets(self.root)
            return bootstrap.CommandResult(0)
        if "build_courses.py" in joined:
            if not self.build_ok:
                return bootstrap.CommandResult(1, "构建失败：课程清单不合法")
            _dist(self.root)
            return bootstrap.CommandResult(0)
        return bootstrap.CommandResult(0)

    def calls_matching(self, needle: str) -> list[list[str]]:
        return [call for call in self.calls if needle in " ".join(call)]


def _patch_node(
    monkeypatch: pytest.MonkeyPatch,
    *,
    node: str | None = "node.exe",
    npm: str | None = "npm.cmd",
    major: int = 22,
) -> None:
    monkeypatch.setattr(bootstrap, "_node_executable", lambda: node)
    monkeypatch.setattr(bootstrap, "_npm_executable", lambda _node: npm)
    monkeypatch.setattr(bootstrap, "_node_major", lambda _node: major)


def test_ready_environment_only_applies_migrations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _venv(tmp_path)
    _runtime_assets(tmp_path)
    _dist(tmp_path)
    runner = Runner(tmp_path)
    monkeypatch.setattr(bootstrap, "_run", runner)

    assert bootstrap.ensure(tmp_path) == []
    assert len(runner.calls_matching("alembic upgrade head")) == 1
    assert runner.calls_matching("pip install") == []
    assert runner.calls_matching("npm install") == []
    assert runner.calls_matching("build_courses.py") == []


def test_first_run_creates_venv_installs_and_builds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = Runner(tmp_path, modules_ok=False)
    monkeypatch.setattr(bootstrap, "_run", runner)
    _patch_node(monkeypatch)

    assert bootstrap.ensure(tmp_path) == ["dependencies", "runtime", "courses"]

    assert bootstrap.venv_python(tmp_path).is_file()
    pip = runner.calls_matching("pip install")
    assert pip, "dependencies must be installed"
    assert "-e" in pip[0]
    assert bootstrap.INSTALL_TARGET in pip[0]

    npm = runner.calls_matching("npm.cmd")
    assert npm, "player assets need npm install on a fresh checkout"
    assert "install" in npm[0]
    sync = runner.calls_matching("sync_runtime.py")[0]
    assert sync[-1] == "--skip-fonts"
    assert "--all" in runner.calls_matching("build_courses.py")[0]
    assert runner.calls_matching("alembic upgrade head")


def test_syncs_vendor_without_npm_when_packages_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _venv(tmp_path)
    _dist(tmp_path)
    _tools(tmp_path)
    runner = Runner(tmp_path)
    monkeypatch.setattr(bootstrap, "_run", runner)
    # A machine that already has tools/node_modules does not need Node.js on PATH.
    monkeypatch.setattr(bootstrap, "_node_executable", lambda: None)

    assert bootstrap.ensure(tmp_path) == ["runtime"]
    assert runner.calls_matching("npm install") == []
    assert runner.calls_matching("sync_runtime.py")


def test_rebuilds_course_pages_when_dist_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _venv(tmp_path)
    _runtime_assets(tmp_path)
    runner = Runner(tmp_path)
    monkeypatch.setattr(bootstrap, "_run", runner)

    assert bootstrap.ensure(tmp_path) == ["courses"]
    assert "--all" in runner.calls_matching("build_courses.py")[0]


def test_missing_node_explains_where_to_download_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _venv(tmp_path)
    runner = Runner(tmp_path)
    monkeypatch.setattr(bootstrap, "_run", runner)
    _patch_node(monkeypatch, node=None)

    with pytest.raises(bootstrap.SetupError) as caught:
        bootstrap.ensure(tmp_path)

    assert "nodejs.org" in caught.value.hint
    assert runner.calls_matching("npm install") == []


def test_old_node_is_reported_with_the_required_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _venv(tmp_path)
    monkeypatch.setattr(bootstrap, "_run", Runner(tmp_path))
    _patch_node(monkeypatch, major=18)

    with pytest.raises(bootstrap.SetupError) as caught:
        bootstrap.ensure(tmp_path)

    assert "22" in caught.value.message


def test_broken_venv_python_gets_recovery_advice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _venv(tmp_path)
    runner = Runner(tmp_path, interpreter_ok=False)
    monkeypatch.setattr(bootstrap, "_run", runner)

    with pytest.raises(bootstrap.SetupError) as caught:
        bootstrap.ensure(tmp_path)

    assert ".venv" in caught.value.hint


def test_build_failure_shows_the_last_output_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _venv(tmp_path)
    _runtime_assets(tmp_path)
    runner = Runner(tmp_path, build_ok=False)
    monkeypatch.setattr(bootstrap, "_run", runner)

    with pytest.raises(bootstrap.SetupError) as caught:
        bootstrap.ensure(tmp_path)

    assert "课程清单不合法" in caught.value.details


def test_skip_fonts_keeps_hashes_of_fonts_that_still_exist(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "VERSION.json").write_text(
        json.dumps(
            {
                "fonts": {
                    "app/static/fonts/NotoSansSC-VF.woff2": "abc",
                    "courses/gone/fonts/NotoSansSC-VF.woff2": "def",
                }
            }
        ),
        encoding="utf-8",
    )
    font = tmp_path / "app" / "static" / "fonts" / "NotoSansSC-VF.woff2"
    font.parent.mkdir(parents=True)
    font.write_text("", encoding="utf-8")

    assert sync_runtime.previous_fonts(tmp_path) == {"app/static/fonts/NotoSansSC-VF.woff2": "abc"}


def test_skip_fonts_tolerates_missing_or_broken_version_file(tmp_path: Path) -> None:
    assert sync_runtime.previous_fonts(tmp_path) == {}


def _link_shared_venv(root: Path, target: Path) -> None:
    """Simulate a worktree's shared ``.venv`` (junction / symlink to main)."""

    python = target / "Scripts" / "python.exe" if os.name == "nt" else target / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    worktree.create_dir_link(target, root / ".venv")


def test_shared_venv_link_is_reused_without_creating_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _link_shared_venv(tmp_path, tmp_path / "shared-venv")
    runner = Runner(tmp_path, modules_ok=False)
    monkeypatch.setattr(bootstrap, "_run", runner)

    target = bootstrap.ensure_venv(bootstrap._Reporter(False), tmp_path)

    assert target == bootstrap.venv_python(tmp_path)
    assert runner.calls == [], "共享的 .venv 不能被重新创建或校验重建"


def test_shared_venv_refuses_to_run_pip_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _link_shared_venv(tmp_path, tmp_path / "shared-venv")
    runner = Runner(tmp_path, modules_ok=False)
    monkeypatch.setattr(bootstrap, "_run", runner)

    with pytest.raises(bootstrap.SetupError) as caught:
        bootstrap.ensure_dependencies(bootstrap._Reporter(False), tmp_path)

    assert "主工作树" in caught.value.message
    assert "主工作树" in caught.value.hint
    assert runner.calls_matching("pip install") == []


def test_dangling_shared_venv_gets_actionable_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shared = tmp_path / "shared-venv"
    _link_shared_venv(tmp_path, shared)
    shutil.rmtree(shared)
    monkeypatch.setattr(bootstrap, "_run", Runner(tmp_path))

    with pytest.raises(bootstrap.SetupError) as caught:
        bootstrap.ensure_venv(bootstrap._Reporter(False), tmp_path)

    assert "worktree.py link" in caught.value.hint

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "VERSION.json").write_text("not json", encoding="utf-8")

    assert sync_runtime.previous_fonts(tmp_path) == {}


def test_star_cmd_prepares_environment_before_starting() -> None:
    star = (bootstrap.ROOT / "star.cmd").read_bytes().decode("gbk")
    assert "scripts\\env.cmd" in star
    assert "scripts\\launcher.py" in star
    assert 'set "APP_PORT=' in star
    assert 'set "APP_HOST=' in star

    env = (bootstrap.ROOT / "scripts" / "env.cmd").read_bytes().decode("gbk")
    assert "bootstrap.py" in env
    assert "--quiet" in env
    for candidate in ("py -3.13", "py -3.12", "py -3.11", "python3"):
        assert candidate in env
    assert "没有找到 Python" in env

    endpoint = launcher.endpoint_from_config(bootstrap.ROOT / "star.cmd")
    assert 1 <= endpoint.port <= 65535


def test_restart_cmd_shares_environment_preparation() -> None:
    restart = (bootstrap.ROOT / "restart.cmd").read_bytes().decode("gbk")
    assert "scripts\\env.cmd" in restart
    assert "scripts\\launcher.py" in restart


def test_stop_cmd_handles_a_machine_that_was_never_prepared() -> None:
    stop = (bootstrap.ROOT / "stop.cmd").read_bytes().decode("gbk")
    assert ":not_initialized" in stop
    assert "服务没有在运行" in stop
    assert "star.cmd" in stop
