from __future__ import annotations

import ctypes
import errno
import os
import subprocess
from pathlib import Path

from .paths import notify_db_path, sms_db_path


FULL_DISK_ACCESS_SETTINGS_URLS = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles",
    "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension",
)

_PROC_PIDPATHINFO_MAXSIZE = 4096

try:
    _LIBPROC = ctypes.CDLL("/usr/lib/libproc.dylib")
    _LIBPROC.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    _LIBPROC.proc_pidpath.restype = ctypes.c_int
except OSError:
    _LIBPROC = None


def _process_parent_pid(pid: int) -> int | None:
    try:
        result = subprocess.run(
            ["ps", "-o", "ppid=", "-p", str(pid)],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    value = result.stdout.strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _process_executable_path(pid: int) -> Path | None:
    if _LIBPROC is None or pid <= 0:
        return None
    buffer = ctypes.create_string_buffer(_PROC_PIDPATHINFO_MAXSIZE)
    size = _LIBPROC.proc_pidpath(pid, buffer, ctypes.sizeof(buffer))
    if size <= 0:
        return None
    raw_path = os.fsdecode(buffer.value)
    if not raw_path:
        return None
    try:
        return Path(raw_path).resolve()
    except Exception:
        return Path(raw_path)


def _is_msgflow_app_executable_path(path: Path | None) -> bool:
    if path is None:
        return False
    parts = path.parts
    for index, part in enumerate(parts):
        if (
            part == "msgflow.app"
            and parts[index + 1 : index + 3] == ("Contents", "MacOS")
            and parts[index + 3 : index + 4] == ("msgflow-app",)
        ):
            return True
    return False


def resolve_full_disk_access_target(pid: int | None = None) -> dict[str, str]:
    current_pid = os.getpid() if pid is None else pid
    seen: set[int] = set()
    while current_pid > 0 and current_pid not in seen:
        seen.add(current_pid)
        executable_path = _process_executable_path(current_pid)
        if _is_msgflow_app_executable_path(executable_path):
            return {
                "kind": "msgflow_app",
                "name": "msgflow-app",
            }
        parent_pid = _process_parent_pid(current_pid)
        if parent_pid is None or parent_pid <= 0 or parent_pid == current_pid:
            break
        current_pid = parent_pid
    return {
        "kind": "terminal_app",
        "name": "terminal app",
    }


def _can_probe_protected_path(path: Path) -> bool | None:
    try:
        with path.open("rb"):
            return True
    except FileNotFoundError:
        return None
    except PermissionError:
        return False
    except OSError as e:
        if e.errno in (errno.EACCES, errno.EPERM):
            return False
        return None


def _can_probe_protected_dir(path: Path) -> bool | None:
    try:
        os.listdir(path)
        return True
    except FileNotFoundError:
        return None
    except PermissionError:
        return False
    except OSError as e:
        if e.errno in (errno.EACCES, errno.EPERM):
            return False
        return None


def full_disk_access_authorized() -> bool:
    for path in (sms_db_path(), notify_db_path()):
        result = _can_probe_protected_path(path)
        if result is not None:
            return result
        result = _can_probe_protected_dir(path.parent)
        if result is not None:
            return result
    return False
