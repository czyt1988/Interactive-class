"""Which video toolchain is available on this machine.

The site has no opinion about how a server installs Node, HyperFrames, Chrome or
FFmpeg. It discovers them in a fixed order and reports every check to the admin
page, so a missing dependency turns into an actionable sentence instead of a
failed render with a stack trace.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.config import BASE_DIR, Settings


@dataclass(frozen=True)
class EnvCheck:
    key: str
    label: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class Toolchain:
    node: str | None
    cli: tuple[str, ...] | None
    cli_label: str
    ffmpeg: str | None
    ffprobe: str | None
    path_prefix: tuple[str, ...]
    checks: tuple[EnvCheck, ...]

    @property
    def ready(self) -> bool:
        return bool(self.checks) and all(check.ok for check in self.checks)

    def child_environment(self) -> dict[str, str]:
        """Environment for the render subprocess, with ffmpeg on ``PATH``."""

        environment = os.environ.copy()
        if not self.path_prefix:
            return environment
        current = environment.get("PATH", "")
        environment["PATH"] = os.pathsep.join(
            [*self.path_prefix, current] if current else list(self.path_prefix)
        )
        return environment


@dataclass(frozen=True)
class _CliDiscovery:
    command: tuple[str, ...] | None
    label: str
    requires_node: bool


def _executable(candidate: str | Path | None) -> str | None:
    if candidate is None:
        return None
    text = str(candidate).strip()
    if not text:
        return None
    path = Path(text)
    if path.is_file():
        return str(path)
    return shutil.which(text)


def _find_in_directories(directories: list[Path | None], name: str) -> str | None:
    suffixes = (".exe", "") if os.name == "nt" else ("", ".exe")
    for directory in directories:
        if directory is None:
            continue
        for suffix in suffixes:
            candidate = directory / f"{name}{suffix}"
            if candidate.is_file():
                return str(candidate)
    return shutil.which(name)


def _discover_cli(settings: Settings, node: str | None) -> _CliDiscovery:
    explicit = settings.video_hyperframes_cli
    if explicit is not None:
        if explicit.is_file():
            if explicit.suffix.lower() in {".mjs", ".js", ".cjs"}:
                if node:
                    return _CliDiscovery((node, str(explicit)), "使用指定的 HyperFrames CLI", True)
                return _CliDiscovery(None, "找到指定的 HyperFrames CLI，但缺少 Node.js", True)
            return _CliDiscovery((str(explicit),), "使用指定的 HyperFrames CLI", False)
        return _CliDiscovery(None, "指定的 HyperFrames CLI 不存在", False)

    bundled = BASE_DIR / "tools" / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs"
    if bundled.is_file() and node:
        return _CliDiscovery((node, str(bundled)), "使用仓库内固定版本的 HyperFrames", True)

    system = shutil.which("hyperframes")
    if system:
        return _CliDiscovery((system,), "使用系统安装的 HyperFrames", False)

    npx = _executable(settings.video_npx_bin)
    if npx and node:
        version = settings.video_hyperframes_version
        return _CliDiscovery(
            (npx, "--yes", f"hyperframes@{version}"),
            f"使用 npx 调用 hyperframes@{version}（首次需要网络）",
            True,
        )
    return _CliDiscovery(None, "未找到 HyperFrames CLI", bool(node))


def discover_toolchain(settings: Settings) -> Toolchain:
    node = _executable(settings.video_node_bin)
    cli = _discover_cli(settings, node)

    ffmpeg_dirs: list[Path | None] = [settings.video_ffmpeg_dir, BASE_DIR / "tools" / "ffmpeg" / "bin"]
    ffmpeg = _find_in_directories(ffmpeg_dirs, "ffmpeg")
    ffprobe = _find_in_directories(ffmpeg_dirs, "ffprobe")

    path_prefix: list[str] = []
    for executable in (ffmpeg, ffprobe):
        if executable is None:
            continue
        directory = str(Path(executable).parent)
        if directory not in path_prefix:
            path_prefix.append(directory)

    checks: list[EnvCheck] = []
    needs_node = cli.requires_node or cli.command is None
    if needs_node:
        checks.append(
            EnvCheck(
                key="node",
                label="Node.js",
                ok=node is not None,
                detail="已找到" if node else "未找到：安装 Node.js 22 或更新版本",
            )
        )
    checks.append(
        EnvCheck(
            key="hyperframes",
            label="HyperFrames",
            ok=cli.command is not None,
            detail=cli.label
            if cli.command is not None
            else "未找到：在 tools/ 里 npm install，或安装 hyperframes，或设置 VIDEO_HYPERFRAMES_CLI",
        )
    )
    checks.append(
        EnvCheck(
            key="ffmpeg",
            label="FFmpeg",
            ok=ffmpeg is not None,
            detail="已找到" if ffmpeg else "未找到：安装 FFmpeg 并加入 PATH，或设置 VIDEO_FFMPEG_DIR",
        )
    )
    checks.append(
        EnvCheck(
            key="ffprobe",
            label="FFprobe",
            ok=ffprobe is not None,
            detail="已找到" if ffprobe else "未找到：FFprobe 通常随 FFmpeg 一起安装",
        )
    )

    return Toolchain(
        node=node,
        cli=cli.command,
        cli_label=cli.label,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        path_prefix=tuple(path_prefix),
        checks=tuple(checks),
    )
