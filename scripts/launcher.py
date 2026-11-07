"""Start, stop and restart the local AI Learning site.

The Windows entry points (``star.cmd``, ``restart.cmd`` and ``stop.cmd``) are
double-click wrappers around this module. The port and bind address are
declared at the top of ``star.cmd`` because that is the file a user opens to
start the site. The running process is recorded in ``.run/service.json`` so
restart and stop can find it even after the original console window is gone.

The ``.cmd`` wrappers are stored as GBK, the default console code page on
Chinese Windows. This module is ordinary UTF-8 Python and lets the Python
runtime write Chinese through the console API, so its output is not affected by
the batch file encoding.
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import importlib.util
import json
import locale
import os
import re
import signal
import socket
import subprocess
import sys
import time
import traceback
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
LAUNCHER_FILE = "star.cmd"
RUN_DIR = ".run"
STATE_FILE = "service.json"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8081

EXIT_OK = 0
EXIT_STOP_FAILED = 1
EXIT_UNEXPECTED = 2
EXIT_START_FAILED = 3
EXIT_ALREADY_RUNNING = 4

REQUIRED_MODULES = ("uvicorn", "fastapi", "jinja2", "pydantic_settings", "sqlalchemy")

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259
ERROR_ACCESS_DENIED = 5

_SETTING_LINE = re.compile(
    r'^\s*set\s+"?(APP_PORT|APP_HOST)\s*=\s*([^"\r\n]*)"?\s*$',
    re.IGNORECASE | re.MULTILINE,
)
_SITE_URL_LINE = re.compile(r"^\s*SITE_URL\s*=", re.IGNORECASE | re.MULTILINE)

_KERNEL32: Any = None


class LauncherError(Exception):
    """A problem that should be shown to the user without a traceback."""


@dataclass(frozen=True)
class Endpoint:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT

    @property
    def display_host(self) -> str:
        if self.host in {"0.0.0.0", "::", "[::]"}:
            return "127.0.0.1"
        return self.host

    @property
    def local_url(self) -> str:
        host = self.display_host
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"http://{host}:{self.port}"

    @property
    def bind_label(self) -> str:
        host = self.host
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"{host}:{self.port}"


@dataclass
class ServiceState:
    pid: int
    host: str
    port: int
    status: str
    started_at: str
    python: str
    created_at: int = 0

    @classmethod
    def new(cls, endpoint: Endpoint, status: str = "starting") -> ServiceState:
        return cls(
            pid=os.getpid(),
            host=endpoint.host,
            port=endpoint.port,
            status=status,
            started_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            python=os.path.realpath(sys.executable),
            created_at=process_creation_time(os.getpid()) or 0,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ServiceState:
        return cls(
            pid=int(data["pid"]),
            host=str(data["host"]),
            port=int(data["port"]),
            status=str(data.get("status", "running")),
            started_at=str(data.get("started_at", "")),
            python=str(data.get("python", "")),
            created_at=int(data.get("created_at", 0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Reading APP_PORT / APP_HOST from the batch file


def _read_launcher_text(path: Path) -> str:
    raw = path.read_bytes()
    with contextlib.suppress(UnicodeDecodeError):
        return raw.decode("utf-8-sig")
    return raw.decode("gbk", errors="replace")


def _launcher_settings(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for match in _SETTING_LINE.finditer(_read_launcher_text(path)):
        values[match.group(1).upper()] = match.group(2).strip()
    return values


def _parse_port(raw: object, source: Path) -> int:
    name = source.name or LAUNCHER_FILE
    text = str(raw).strip()
    if not text.isdigit():
        raise LauncherError(
            f"端口配置不是数字：{text or '（空）'}。请检查 {name} 开头的 APP_PORT。"
        )
    port = int(text)
    if not 1 <= port <= 65535:
        raise LauncherError(
            f"端口必须在 1-65535 之间，当前是 {port}。请检查 {name} 开头的 APP_PORT。"
        )
    return port


def _parse_host(raw: object, source: Path) -> str:
    name = source.name or LAUNCHER_FILE
    text = str(raw).strip()
    if len(text) >= 2 and text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    if not text or any(char.isspace() for char in text):
        raise LauncherError(f"绑定地址不合法：{text or '（空）'}。请检查 {name} 开头的 APP_HOST。")
    return text


def endpoint_from_config(
    path: Path,
    *,
    port_override: str | int | None = None,
    host_override: str | None = None,
) -> Endpoint:
    values = _launcher_settings(path)
    raw_port = port_override if port_override is not None else values.get("APP_PORT", DEFAULT_PORT)
    raw_host = host_override if host_override is not None else values.get("APP_HOST", DEFAULT_HOST)
    return Endpoint(host=_parse_host(raw_host, path), port=_parse_port(raw_port, path))


# ---------------------------------------------------------------------------
# Runtime state


def run_dir(root: Path) -> Path:
    return root / RUN_DIR


def state_file(root: Path) -> Path:
    return run_dir(root) / STATE_FILE


def read_state(path: Path) -> ServiceState | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return ServiceState.from_dict(payload)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def create_state(path: Path, state: ServiceState) -> bool:
    """Create the state file exclusively; return False when one already exists."""

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return False
    except OSError as exc:
        raise LauncherError(f"无法写入运行记录 {path}：{exc}") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(state.to_dict(), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except OSError as exc:
        with contextlib.suppress(OSError):
            path.unlink()
        raise LauncherError(f"无法写入运行记录 {path}：{exc}") from exc
    return True


def update_state(path: Path, state: ServiceState) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(state.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def remove_state(path: Path, *, pid: int | None = None) -> bool:
    if pid is not None:
        current = read_state(path)
        if current is None or current.pid != pid:
            return False
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    except OSError:
        return False
    return True


# ---------------------------------------------------------------------------
# Process helpers (Windows first; the launcher is only shipped as .cmd)


def _kernel32() -> Any:
    global _KERNEL32
    if _KERNEL32 is None:
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.GetProcessTimes.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        ]
        kernel32.GetProcessTimes.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        _KERNEL32 = kernel32
    return _KERNEL32


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    from ctypes import wintypes

    kernel32 = _kernel32()
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ctypes.get_last_error() == ERROR_ACCESS_DENIED
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def process_image(pid: int) -> str | None:
    if pid <= 0:
        return None
    if os.name != "nt":
        try:
            return os.readlink(f"/proc/{pid}/exe")
        except OSError:
            return None

    from ctypes import wintypes

    kernel32 = _kernel32()
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return None
        return buffer.value or None
    finally:
        kernel32.CloseHandle(handle)


def process_creation_time(pid: int) -> int | None:
    """Return a stable process identity: its creation time.

    A PID can be reused after a crash, so the PID alone is not enough to decide
    whether ``service.json`` still points at our server. The creation timestamp
    survives that reuse and needs no extra dependency.
    """

    if pid <= 0:
        return None
    if os.name != "nt":
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii", errors="replace")
        except OSError:
            return None
        # Field 22 (starttime); after the command name there are fields 3..n.
        fields = stat.rpartition(")")[2].split()
        try:
            return int(fields[19])
        except (IndexError, ValueError):
            return None

    from ctypes import wintypes

    kernel32 = _kernel32()
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        creation = wintypes.FILETIME()
        exit_time = wintypes.FILETIME()
        kernel_time = wintypes.FILETIME()
        user_time = wintypes.FILETIME()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            return None
        return (creation.dwHighDateTime << 32) | creation.dwLowDateTime
    finally:
        kernel32.CloseHandle(handle)


def _same_path(left: str, right: str) -> bool:
    return os.path.normcase(os.path.realpath(left)) == os.path.normcase(os.path.realpath(right))


def process_matches(state: ServiceState) -> bool:
    if not pid_alive(state.pid):
        return False
    if state.created_at:
        actual = process_creation_time(state.pid)
        if actual is not None:
            return actual == state.created_at
    # Older state files have no creation time: fall back to the interpreter
    # path, then to the listening port.
    if state.python:
        image = process_image(state.pid)
        if image is not None and _same_path(image, state.python):
            return True
    return bool(state.port) and state.pid in listener_pids(state.port)


def _decode_command_output(raw: bytes) -> str:
    if os.name == "nt":
        # Native tools such as taskkill print in the OEM code page.
        encoding = f"cp{ctypes.windll.kernel32.GetOEMCP()}"
    else:
        encoding = locale.getpreferredencoding(False) or "utf-8"
    try:
        text = raw.decode(encoding, errors="replace")
    except LookupError:
        text = raw.decode("utf-8", errors="replace")
    return text.strip()


def kill_process_tree(pid: int) -> None:
    if os.name != "nt":
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        return
    try:
        completed = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise LauncherError(f"无法执行 taskkill：{exc}") from exc
    if completed.returncode == 0 or not pid_alive(pid):
        return
    detail = _decode_command_output(completed.stderr or completed.stdout)
    raise LauncherError(f"结束进程 {pid} 失败：{detail or f'退出码 {completed.returncode}'}")


def wait_pid_gone(pid: int, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.1)
    return not pid_alive(pid)


# ---------------------------------------------------------------------------
# Listening ports


def _listening_pids() -> dict[int, set[int]]:
    if os.name != "nt":
        return {}
    try:
        completed = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return {}

    result: dict[int, set[int]] = {}
    # netstat output is OEM encoded; the fields used here are plain ASCII.
    for line in completed.stdout.decode("ascii", errors="ignore").splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        try:
            local_port = int(parts[1].rsplit(":", 1)[1])
            remote_port = int(parts[2].rsplit(":", 1)[1])
            pid = int(parts[4])
        except (IndexError, ValueError):
            continue
        if remote_port != 0:
            continue
        result.setdefault(local_port, set()).add(pid)
    return result


def listener_pids(port: int) -> set[int]:
    return set(_listening_pids().get(port, ()))


def port_in_use(port: int) -> bool:
    if os.name == "nt":
        return bool(listener_pids(port))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.25)
        return probe.connect_ex(("127.0.0.1", port)) == 0


# ---------------------------------------------------------------------------
# Presentation


def _configure_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(ValueError):
                reconfigure(errors="replace")


def _network_address() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            address = probe.getsockname()[0]
    except OSError:
        return None
    if not address or address.startswith("127.") or address == "0.0.0.0":
        return None
    return address


def _print_addresses(endpoint: Endpoint) -> None:
    print(f"  本机访问  {endpoint.local_url}")
    if endpoint.host == "0.0.0.0":
        address = _network_address()
        if address:
            print(f"  局域网    http://{address}:{endpoint.port}")


def print_banner(root: Path, endpoint: Endpoint, action: str) -> None:
    print()
    print("=" * 60)
    print(f"  AI Learning - {action}")
    print("=" * 60)
    print(f"  项目目录  {root}")
    print(f"  监听地址  {endpoint.bind_label}")
    _print_addresses(endpoint)
    if action.startswith("启动") or action.startswith("重启"):
        print("  停止服务  Ctrl+C，或双击 stop.cmd")
    print("-" * 60)


def print_ready(endpoint: Endpoint) -> None:
    print()
    print("-" * 60)
    print("服务已启动。")
    _print_addresses(endpoint)
    print("停止服务：Ctrl+C，或双击 stop.cmd。")
    print("-" * 60)
    print()


def _endpoint_of(state: ServiceState) -> Endpoint:
    return Endpoint(host=state.host, port=state.port)


def _print_port_conflict(endpoint: Endpoint, pids: set[int]) -> None:
    if pids:
        shown = ", ".join(str(pid) for pid in sorted(pids))
        print(f"端口 {endpoint.port} 已被占用（PID：{shown}）。")
        for pid in sorted(pids):
            image = process_image(pid)
            if image:
                print(f"  PID {pid}  {image}")
    else:
        print(f"端口 {endpoint.port} 已被占用。")
    print()
    print(f"请关闭占用端口的程序，或修改 star.cmd 开头的 APP_PORT（当前 {endpoint.port}）后重试。")


def _missing_modules() -> list[str]:
    return [name for name in REQUIRED_MODULES if importlib.util.find_spec(name) is None]


# ---------------------------------------------------------------------------
# Commands


def stop_state(state: ServiceState, path: Path) -> int:
    print(f"正在停止服务：PID {state.pid}，监听 {state.host}:{state.port} ...")
    try:
        kill_process_tree(state.pid)
    except LauncherError as exc:
        print(str(exc))
        return EXIT_STOP_FAILED

    if not wait_pid_gone(state.pid):
        print(f"结束进程超时，请手动执行：taskkill /PID {state.pid} /T /F")
        return EXIT_STOP_FAILED

    remove_state(path)
    remaining = listener_pids(state.port)
    if remaining:
        pids = ", ".join(str(pid) for pid in sorted(remaining))
        print(f"进程已结束，但端口 {state.port} 仍被占用（PID：{pids}）。")
        return EXIT_OK
    print("服务已停止。")
    return EXIT_OK


def command_start(root: Path, endpoint: Endpoint, *, banner: bool = True) -> int:
    if banner:
        print_banner(root, endpoint, "启动本地服务")

    path = state_file(root)
    state = read_state(path)
    if state is not None:
        if process_matches(state):
            running = _endpoint_of(state)
            print(f"服务已经在运行：{running.local_url}")
            print(f"  PID      {state.pid}")
            print(f"  监听     {running.bind_label}")
            if state.started_at:
                print(f"  启动时间 {state.started_at}")
            if (state.host, state.port) != (endpoint.host, endpoint.port):
                print()
                print(f"注意：star.cmd 现在的配置是 {endpoint.bind_label}。")
                print("      双击 restart.cmd 可以按新配置重启。")
            return EXIT_ALREADY_RUNNING
        print("清理上次异常退出留下的运行记录。")
        remove_state(path)

    occupied = listener_pids(endpoint.port)
    if occupied:
        _print_port_conflict(endpoint, occupied)
        return EXIT_START_FAILED

    if os.name != "nt" and port_in_use(endpoint.port):
        _print_port_conflict(endpoint, set())
        return EXIT_START_FAILED

    missing = _missing_modules()
    if missing:
        print(f"缺少运行依赖：{'、'.join(missing)}")
        print()
        print("请先安装依赖：")
        print(f'  "{sys.executable}" -m pip install -e ".[dev]"')
        return EXIT_START_FAILED

    if not (root / "dist" / "courses").is_dir():
        print("提示：dist\\courses 不存在，首页暂时不会有课程。")
        print("      先运行：python scripts\\build_courses.py --all")
        print()

    state = ServiceState.new(endpoint)
    if not create_state(path, state):
        print("另一个启动或重启操作正在进行，请稍候再试。")
        return EXIT_ALREADY_RUNNING

    try:
        return run_server(root, endpoint, state, path)
    finally:
        remove_state(path, pid=os.getpid())


def _apply_site_url_default(root: Path, endpoint: Endpoint) -> None:
    """Keep canonical URLs on the port the launcher actually binds."""

    if os.environ.get("SITE_URL"):
        return
    env_file = root / ".env"
    if env_file.is_file():
        with contextlib.suppress(OSError):
            if _SITE_URL_LINE.search(env_file.read_text(encoding="utf-8-sig", errors="replace")):
                return
    os.environ["SITE_URL"] = endpoint.local_url


def run_server(root: Path, endpoint: Endpoint, state: ServiceState, path: Path) -> int:
    try:
        import uvicorn
    except Exception as exc:  # surface the reason to a double-click user
        print(f"无法导入 uvicorn：{exc}")
        return EXIT_START_FAILED

    os.chdir(root)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    _apply_site_url_default(root, endpoint)

    class LauncherServer(uvicorn.Server):
        async def startup(self, sockets: list[socket.socket] | None = None) -> None:
            await super().startup(sockets=sockets)
            if not self.started:
                return
            state.status = "running"
            try:
                update_state(path, state)
            except OSError as exc:
                print(f"警告：写入运行记录失败：{exc}")
            print_ready(endpoint)

    config = uvicorn.Config(
        "app.main:app",
        host=endpoint.host,
        port=endpoint.port,
        log_level="info",
        access_log=True,
        timeout_graceful_shutdown=5,
    )
    server = LauncherServer(config)

    try:
        server.run()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else EXIT_UNEXPECTED
        if code != 0:
            print()
            print("服务未能启动，请检查上面的错误信息后重试。")
        return code
    except KeyboardInterrupt:
        return EXIT_OK
    except Exception:  # keep the double-click window informative
        print()
        print("服务异常退出：")
        traceback.print_exc()
        return EXIT_UNEXPECTED

    print()
    print("服务已停止。")
    return EXIT_OK


def command_stop(root: Path, endpoint: Endpoint) -> int:
    print_banner(root, endpoint, "停止本地服务")

    path = state_file(root)
    state = read_state(path)
    if state is not None:
        if process_matches(state):
            print()
            return stop_state(state, path)
        print("运行记录里的进程已经不存在，清理过期记录。")
        remove_state(path)
        print()

    pids = listener_pids(endpoint.port)
    if pids:
        _print_port_conflict(endpoint, pids)
        print("这不是 star.cmd 启动的实例，为避免误杀，stop.cmd 没有结束它。")
        print(f"如确认需要结束，请手动执行：taskkill /PID {sorted(pids)[0]} /T /F")
        return EXIT_STOP_FAILED

    if os.name != "nt" and port_in_use(endpoint.port):
        print(f"端口 {endpoint.port} 正在被其他程序使用，但没有可识别的运行记录。")
        return EXIT_STOP_FAILED

    print("当前没有正在运行的服务。")
    return EXIT_OK


def command_restart(root: Path, endpoint: Endpoint) -> int:
    print_banner(root, endpoint, "重启本地服务")

    path = state_file(root)
    state = read_state(path)
    if state is not None and process_matches(state):
        print(f"检测到运行中的服务：PID {state.pid}，监听 {state.host}:{state.port}。")
        if (state.host, state.port) != (endpoint.host, endpoint.port):
            print(f"star.cmd 的配置是 {endpoint.bind_label}，将按新配置启动。")
        print()
        code = stop_state(state, path)
        if code != EXIT_OK:
            return code
        print()
    elif state is not None:
        print("清理上次异常退出留下的运行记录。")
        remove_state(path)
        print()
    else:
        print("没有发现运行中的服务，直接启动。")
        print()

    return command_start(root, endpoint, banner=False)


# ---------------------------------------------------------------------------
# CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI Learning 本地服务控制")
    parser.add_argument("command", choices=("start", "stop", "restart"))
    parser.add_argument("--port", help="临时覆盖 star.cmd 里的 APP_PORT")
    parser.add_argument("--host", help="临时覆盖 star.cmd 里的 APP_HOST")
    parser.add_argument("--config", type=Path, help="启动脚本路径（默认 star.cmd）")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_output()
    args = build_parser().parse_args(argv)
    root = args.root.resolve()
    config_path = (args.config or (root / LAUNCHER_FILE)).resolve()

    try:
        endpoint = endpoint_from_config(
            config_path,
            port_override=args.port,
            host_override=args.host,
        )
    except LauncherError as exc:
        if args.command != "stop":
            print(f"[错误] {exc}")
            return EXIT_START_FAILED
        print(f"提示：读取启动脚本配置失败（{exc}），停止操作只依据运行记录。")
        endpoint = Endpoint()

    try:
        if args.command == "start":
            return command_start(root, endpoint)
        if args.command == "restart":
            return command_restart(root, endpoint)
        return command_stop(root, endpoint)
    except LauncherError as exc:
        print(f"[错误] {exc}")
        return EXIT_STOP_FAILED if args.command == "stop" else EXIT_START_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
