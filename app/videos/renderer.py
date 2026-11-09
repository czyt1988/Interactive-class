"""Render a built course composition to MP4 with the pinned HyperFrames CLI.

This module only runs one subprocess and returns a result; scheduling, file
placement and retry policy live in :mod:`app.videos.manager`.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.videos.models import RenderOutcome, RenderRequest
from app.videos.toolchain import Toolchain, discover_toolchain

_ON_WINDOWS = os.name == "nt"
_CREATE_NO_WINDOW = 0x08000000


class RenderError(RuntimeError):
    """A render failure with a sentence the admin page can show."""


class RenderUnavailable(RenderError):
    """The required toolchain is missing or unusable."""


class RenderFailed(RenderError):
    """The renderer ran but did not produce a usable MP4."""


class RenderTimeout(RenderError):
    """The render exceeded the configured timeout."""


class RenderCancelled(RenderError):
    """The server is shutting down and stopped the render."""


@dataclass(frozen=True)
class VideoProbe:
    duration_seconds: float
    width: int
    height: int


def _process_options() -> dict[str, object]:
    if _ON_WINDOWS:
        return {"creationflags": _CREATE_NO_WINDOW}
    # A new session lets a timeout kill the whole Node/Chrome tree, not just node.
    return {"start_new_session": True}


def _terminate_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if _ON_WINDOWS:
        with suppress(OSError, subprocess.SubprocessError):
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                timeout=20,
                creationflags=_CREATE_NO_WINDOW,
            )
    else:
        with suppress(OSError):
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=5)


def probe_video(ffprobe: str, path: Path) -> VideoProbe | None:
    """Read duration and dimensions from a rendered file.

    A file that ffprobe cannot parse is treated as an unusable render, so the
    page never offers a corrupt download.
    """

    if not ffprobe:
        return None
    command = [
        ffprobe,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            **_process_options(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout)
        duration = float(payload["format"]["duration"])
        streams = [
            stream
            for stream in payload.get("streams", [])
            if stream.get("codec_type") == "video"
        ]
        if not streams:
            return None
        return VideoProbe(
            duration_seconds=duration,
            width=int(streams[0]["width"]),
            height=int(streams[0]["height"]),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


class SubprocessRenderer:
    """Run ``hyperframes render`` against a copied composition."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def command(self, toolchain: Toolchain, request: RenderRequest) -> list[str]:
        if toolchain.cli is None:
            raise RenderUnavailable("生成环境里没有 HyperFrames CLI。")
        return [
            *toolchain.cli,
            "render",
            str(request.project_dir),
            "--output",
            str(request.output_path),
            "--quality",
            request.quality,
            "--no-wait",
        ]

    def run(
        self,
        request: RenderRequest,
        on_line: Callable[[str], None],
        stop_event: threading.Event,
    ) -> RenderOutcome:
        toolchain = discover_toolchain(self.settings)
        if not toolchain.ready:
            missing = [check.label for check in toolchain.checks if not check.ok]
            raise RenderUnavailable(f"生成环境未就绪：缺少 {'、'.join(missing)}。")

        command = self.command(toolchain, request)
        request.log_path.parent.mkdir(parents=True, exist_ok=True)
        tail: deque[str] = deque(maxlen=40)

        with request.log_path.open("w", encoding="utf-8", errors="replace") as log:
            try:
                process = subprocess.Popen(
                    command,
                    cwd=str(request.project_dir),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    env=toolchain.child_environment(),
                    **_process_options(),
                )
            except FileNotFoundError as exc:
                raise RenderUnavailable(f"无法启动渲染命令：{exc}") from exc
            except OSError as exc:
                raise RenderUnavailable(f"无法启动渲染命令：{exc}") from exc

            def pump() -> None:
                stream = process.stdout
                if stream is None:
                    return
                for raw in stream:
                    line = raw.rstrip()
                    if not line:
                        continue
                    tail.append(line)
                    try:
                        log.write(line + "\n")
                        log.flush()
                    except (OSError, ValueError):
                        pass
                    on_line(line)

            reader = threading.Thread(target=pump, name="video-render-log", daemon=True)
            reader.start()
            deadline = time.monotonic() + request.timeout_seconds
            try:
                while process.poll() is None:
                    if stop_event.is_set():
                        _terminate_tree(process)
                        raise RenderCancelled("生成已取消。")
                    if time.monotonic() >= deadline:
                        _terminate_tree(process)
                        raise RenderTimeout("生成超时。")
                    time.sleep(0.2)
            finally:
                reader.join(timeout=5)
                if process.poll() is None:
                    _terminate_tree(process)

        if process.returncode != 0:
            raise RenderFailed(f"渲染进程退出码 {process.returncode}。")

        output = request.output_path
        try:
            size = output.stat().st_size
        except OSError as exc:
            raise RenderFailed("渲染没有写出视频文件。") from exc
        if size <= 0:
            raise RenderFailed("渲染写出的视频文件是空的。")

        probe = probe_video(toolchain.ffprobe or "", output)
        if probe is None:
            raise RenderFailed("输出文件无法读取，渲染可能不完整。")
        return RenderOutcome(
            size_bytes=size,
            duration_seconds=probe.duration_seconds,
            width=probe.width,
            height=probe.height,
            log_tail=tuple(tail),
        )
