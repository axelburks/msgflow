from __future__ import annotations

import os
import plistlib
import subprocess
from pathlib import Path

from ..common.paths import app_log_path, ui_launch_command, ui_launch_environment


APP_LAUNCH_AGENT_LABEL = "com.axel.msgflow.ui"


def launch_agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{APP_LAUNCH_AGENT_LABEL}.plist"


def is_app_launch_at_login_enabled() -> bool:
    plist_path = launch_agent_path()
    if not plist_path.exists():
        return False
    try:
        with plist_path.open("rb") as fp:
            payload = plistlib.load(fp)
    except Exception:
        return False
    return bool(payload.get("RunAtLoad")) and payload.get("Label") == APP_LAUNCH_AGENT_LABEL


def set_app_launch_at_login(enabled: bool) -> None:
    plist_path = launch_agent_path()
    if enabled:
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        app_log_path().parent.mkdir(parents=True, exist_ok=True)
        with plist_path.open("wb") as fp:
            plistlib.dump(_build_launch_agent_payload(), fp, sort_keys=True)
        _launchctl("bootout", ignore_failure=True)
        _launchctl("bootstrap")
        return
    _launchctl("bootout", ignore_failure=True)
    if plist_path.exists():
        plist_path.unlink()


def _build_launch_agent_payload() -> dict[str, object]:
    command = ui_launch_command()
    env = ui_launch_environment()
    payload: dict[str, object] = {
        "Label": APP_LAUNCH_AGENT_LABEL,
        "ProgramArguments": command,
        "RunAtLoad": True,
        "KeepAlive": False,
        "ProcessType": "Interactive",
        "WorkingDirectory": str(Path(command[0]).resolve().parent),
        "StandardOutPath": str(app_log_path()),
        "StandardErrorPath": str(app_log_path()),
    }
    if env:
        payload["EnvironmentVariables"] = env
    return payload


def _launchctl(action: str, ignore_failure: bool = False) -> None:
    plist_path = launch_agent_path()
    uid = os.getuid()
    command = ["launchctl", action, f"gui/{uid}", str(plist_path)]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode == 0 or ignore_failure:
        return
    error_text = (result.stderr or result.stdout).strip() or f"launchctl {action} failed"
    raise RuntimeError(error_text)
