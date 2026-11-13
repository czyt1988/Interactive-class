from __future__ import annotations

import sys
from pathlib import Path

import pytest

from scripts import bootstrap, build


def _venv(root: Path) -> None:
    target = bootstrap.venv_python(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("", encoding="utf-8")


def _start_cmd(root: Path, port: int) -> None:
    (root / "start.cmd").write_bytes(
        f'REM 中文注释\r\nset "APP_PORT={port}"\r\nset "APP_HOST=0.0.0.0"\r\n'.encode("gbk")
    )


def _commands(plan: list[build.Step]) -> list[str]:
    return [" ".join(step.command) for step in plan]


def test_plan_order_and_site_url_follow_start_cmd(tmp_path: Path) -> None:
    _start_cmd(tmp_path, 9090)

    plan = build.build_plan(tmp_path)

    commands = _commands(plan)
    assert len(commands) == 4
    assert "import app.main" in commands[0]
    assert "sync_runtime.py" in commands[1]
    assert "alembic upgrade head" in commands[2]
    assert "build_courses.py --all" in commands[3]
    assert "--site-url http://127.0.0.1:9090" in commands[3]
    # Font subsets must be regenerated, not reused from the last sync: edited
    # copy needs the new glyphs.
    assert "--skip-fonts" not in commands[1]


def test_explicit_site_url_and_course_selection_win(tmp_path: Path) -> None:
    _start_cmd(tmp_path, 9090)

    plan = build.build_plan(
        tmp_path,
        site_url_override="https://learn.example.com/",
        courses=["alpha", "beta"],
    )

    courses = _commands(plan)[3]
    assert "https://learn.example.com" in courses
    assert " --course alpha" in courses
    assert " --course beta" in courses
    assert "--all" not in courses


def test_missing_venv_explains_to_prepare_with_start_cmd(tmp_path: Path) -> None:
    with pytest.raises(build.BuildError) as caught:
        build.build(tmp_path, runner=lambda _step: None)

    assert "start.cmd" in caught.value.hint
    assert ".venv" in caught.value.message


def test_every_step_runs_in_order(tmp_path: Path) -> None:
    _venv(tmp_path)
    ran: list[str] = []

    plan = build.build(tmp_path, runner=lambda step: ran.append(step.title))

    assert ran == [step.title for step in plan]
    assert len(ran) == 4


def test_a_failed_step_stops_the_build(tmp_path: Path) -> None:
    _venv(tmp_path)
    ran: list[str] = []

    def runner(step: build.Step) -> None:
        ran.append(step.title)
        raise build.BuildError("同步播放器失败。", "检查 tools/node_modules 后重试。")

    with pytest.raises(build.BuildError):
        build.build(tmp_path, runner=runner)

    assert ran == [build.build_plan(tmp_path)[0].title]


def test_failed_command_reports_its_exit_code(tmp_path: Path) -> None:
    step = build.Step("测试步骤", [sys.executable, "-c", "raise SystemExit(3)"])

    with pytest.raises(build.BuildError) as caught:
        build.run_step(step, root=tmp_path)

    assert "测试步骤失败" in caught.value.message
    assert "3" in caught.value.message


def test_build_cmd_wraps_the_build_module() -> None:
    wrapper = (build.ROOT / "build.cmd").read_bytes().decode("gbk")

    assert "scripts\\env.cmd" in wrapper
    assert "scripts\\build.py" in wrapper
    assert "start.cmd" in wrapper
    assert "restart.cmd" in wrapper


def test_readme_documents_the_build_entry_point() -> None:
    readme = (build.ROOT / "README.md").read_text(encoding="utf-8")
    assert "build.cmd" in readme
