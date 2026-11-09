"""Tests for toolchain discovery and the render command line.

Rendering itself is covered by the manager tests with a fake runner; these
tests make sure discovery reports missing tools and that the command matches the
pinned HyperFrames CLI contract.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from app.config import Settings
from app.videos import renderer as renderer_module
from app.videos import toolchain as toolchain_module
from app.videos.models import RenderRequest
from app.videos.renderer import RenderUnavailable, SubprocessRenderer
from app.videos.toolchain import EnvCheck, Toolchain, discover_toolchain


def _write_file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    return path


def test_discovers_explicit_node_cli_and_ffmpeg(settings: Settings, tmp_path: Path) -> None:
    node = _write_file(tmp_path / "bin" / "node")
    cli = _write_file(tmp_path / "bin" / "hyperframes.mjs")
    ffmpeg_dir = tmp_path / "ffmpeg-bin"
    _write_file(ffmpeg_dir / "ffmpeg")
    _write_file(ffmpeg_dir / "ffprobe")

    settings.video_node_bin = str(node)
    settings.video_hyperframes_cli = cli
    settings.video_ffmpeg_dir = ffmpeg_dir

    toolchain = discover_toolchain(settings)
    assert toolchain.ready is True
    assert toolchain.cli == (str(node), str(cli))
    assert toolchain.ffmpeg is not None and toolchain.ffmpeg.endswith("ffmpeg")
    assert toolchain.ffprobe is not None and toolchain.ffprobe.endswith("ffprobe")
    assert all(check.ok for check in toolchain.checks)
    assert str(ffmpeg_dir) in toolchain.path_prefix


def test_missing_ffmpeg_makes_environment_unready(
    settings: Settings, tmp_path: Path, monkeypatch
) -> None:
    node = _write_file(tmp_path / "bin" / "node")
    cli = _write_file(tmp_path / "bin" / "hyperframes.mjs")
    settings.video_node_bin = str(node)
    settings.video_hyperframes_cli = cli
    settings.video_ffmpeg_dir = tmp_path / "no-ffmpeg-here"

    real_which = toolchain_module.shutil.which
    monkeypatch.setattr(toolchain_module, "BASE_DIR", tmp_path)
    monkeypatch.setattr(
        toolchain_module.shutil,
        "which",
        lambda name: None if name in {"ffmpeg", "ffprobe"} else real_which(name),
    )

    toolchain = discover_toolchain(settings)
    assert toolchain.ready is False
    missing = {check.key for check in toolchain.checks if not check.ok}
    assert missing == {"ffmpeg", "ffprobe"}


def test_child_environment_prepends_ffmpeg_directory(
    settings: Settings, tmp_path: Path
) -> None:
    ffmpeg_dir = tmp_path / "ffmpeg-bin"
    _write_file(ffmpeg_dir / "ffmpeg")
    _write_file(ffmpeg_dir / "ffprobe")
    settings.video_ffmpeg_dir = ffmpeg_dir
    settings.video_node_bin = str(_write_file(tmp_path / "node"))
    settings.video_hyperframes_cli = _write_file(tmp_path / "hyperframes.mjs")

    toolchain = discover_toolchain(settings)
    child_path = toolchain.child_environment()["PATH"]
    first = child_path.split(os.pathsep)[0]
    assert Path(first) == ffmpeg_dir


def test_render_command_matches_the_cli_contract(tmp_path: Path, settings: Settings) -> None:
    toolchain = Toolchain(
        node="node",
        cli=("node", "/opt/hyperframes/bin/hyperframes.mjs"),
        cli_label="test",
        ffmpeg="ffmpeg",
        ffprobe="ffprobe",
        path_prefix=(),
        checks=(EnvCheck("node", "Node.js", True, "已找到"),),
    )
    request = RenderRequest(
        slug="demo",
        project_dir=tmp_path / "project",
        output_path=tmp_path / "demo.mp4",
        log_path=tmp_path / "render.log",
        quality="looks",
        timeout_seconds=60,
    )
    command = SubprocessRenderer(settings).command(toolchain, request)
    assert command == [
        "node",
        "/opt/hyperframes/bin/hyperframes.mjs",
        "render",
        str(tmp_path / "project"),
        "--output",
        str(tmp_path / "demo.mp4"),
        "--quality",
        "looks",
        "--no-wait",
    ]


def test_renderer_refuses_when_toolchain_is_missing(
    settings: Settings, tmp_path: Path, monkeypatch
) -> None:
    unavailable = Toolchain(
        node=None,
        cli=None,
        cli_label="未找到",
        ffmpeg=None,
        ffprobe=None,
        path_prefix=(),
        checks=(EnvCheck("hyperframes", "HyperFrames", False, "未找到"),),
    )
    monkeypatch.setattr(renderer_module, "discover_toolchain", lambda _settings: unavailable)
    request = RenderRequest(
        slug="demo",
        project_dir=tmp_path,
        output_path=tmp_path / "demo.mp4",
        log_path=tmp_path / "render.log",
        quality="looks",
        timeout_seconds=60,
    )
    with pytest.raises(RenderUnavailable):
        SubprocessRenderer(settings).run(
            request, lambda _line: None, threading.Event()
        )
