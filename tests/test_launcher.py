from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts import launcher


def _write_config(path: Path, text: str, encoding: str = "gbk") -> None:
    path.write_bytes(text.encode(encoding))


def test_config_defaults_when_launcher_missing(tmp_path: Path) -> None:
    endpoint = launcher.endpoint_from_config(tmp_path / "star.cmd")
    assert endpoint == launcher.Endpoint(host="0.0.0.0", port=8081)


def test_config_reads_gbk_launcher(tmp_path: Path) -> None:
    path = tmp_path / "star.cmd"
    _write_config(
        path,
        'REM 中文注释\r\nset "APP_PORT=9091"\r\nset "APP_HOST=127.0.0.1"\r\n',
    )

    assert launcher.endpoint_from_config(path) == launcher.Endpoint("127.0.0.1", 9091)


def test_config_reads_utf8_launcher_after_editor_save(tmp_path: Path) -> None:
    path = tmp_path / "star.cmd"
    _write_config(
        path,
        "REM 编辑器另存为 UTF-8\r\nset APP_PORT=9092\r\nset APP_HOST=0.0.0.0\r\n",
        encoding="utf-8",
    )

    assert launcher.endpoint_from_config(path) == launcher.Endpoint("0.0.0.0", 9092)


def test_command_line_override_wins(tmp_path: Path) -> None:
    path = tmp_path / "star.cmd"
    _write_config(path, 'set "APP_PORT=8081"\r\nset "APP_HOST=0.0.0.0"\r\n')

    endpoint = launcher.endpoint_from_config(
        path,
        port_override="9000",
        host_override="127.0.0.1",
    )

    assert endpoint == launcher.Endpoint("127.0.0.1", 9000)


@pytest.mark.parametrize("port", ["", "abc", "0", "65536", "80.5"])
def test_invalid_port_is_rejected(tmp_path: Path, port: str) -> None:
    path = tmp_path / "star.cmd"
    _write_config(path, f'set "APP_PORT={port}"\r\n')

    with pytest.raises(launcher.LauncherError):
        launcher.endpoint_from_config(path)


def test_ipv6_host_keeps_url_readable(tmp_path: Path) -> None:
    path = tmp_path / "star.cmd"
    _write_config(path, 'set "APP_PORT=8081"\r\nset "APP_HOST=[::]"\r\n')

    endpoint = launcher.endpoint_from_config(path)

    assert endpoint.host == "::"
    assert endpoint.local_url == "http://127.0.0.1:8081"


def test_state_file_is_created_exclusively_and_can_be_updated(tmp_path: Path) -> None:
    path = tmp_path / ".run" / "service.json"
    state = launcher.ServiceState(
        pid=4321,
        host="0.0.0.0",
        port=8081,
        status="starting",
        started_at="2026-01-01T10:00:00+08:00",
        python=str(tmp_path / "python.exe"),
    )

    assert launcher.create_state(path, state) is True
    assert launcher.create_state(path, state) is False
    assert launcher.read_state(path) == state

    state.status = "running"
    launcher.update_state(path, state)
    assert launcher.read_state(path) == state

    assert launcher.remove_state(path) is True
    assert launcher.read_state(path) is None
    assert launcher.remove_state(path) is False


def test_process_identity_uses_creation_time() -> None:
    created = launcher.process_creation_time(os.getpid())
    if not created:
        pytest.skip("process creation time is unavailable on this platform")

    state = launcher.ServiceState(
        pid=os.getpid(),
        host="0.0.0.0",
        port=8081,
        status="running",
        started_at="",
        python="",
        created_at=created,
    )
    assert launcher.process_matches(state)

    state.created_at = created + 1
    assert not launcher.process_matches(state)
