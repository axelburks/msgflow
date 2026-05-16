from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "msgflow"
DEFAULT_CONFIG_DIR = "~/.config/msgflow"
DEBUG_CONFIG_SUBDIR = "debug"
CONFIG_FILE_NAME = "config.yaml"
HISTORY_FILE_NAME = "history/history.db"
LOGS_DIR_NAME = "logs"
LOG_FILE_NAME = f"{APP_NAME}.log"
BREW_SERVICE_LOG_FILE_NAME = f"{APP_NAME}-service.log"
MANAGED_CORE_EXECUTABLE_NAME = "msgflow-core"
SMS_DB_PATH = "~/Library/Messages/chat.db"
NOTIFY_DB_PATH = "~/Library/Group Containers/group.com.apple.usernoted/db2/db"
IPN_REMOTE_PATH = "~/Library/Group Containers/group.com.apple.UserNotifications/Library/UserNotifications/Remote/default"


def common_dir() -> Path:
    return Path(__file__).resolve().parent


def package_dir() -> Path:
    return common_dir().parent


def project_root_dir() -> Path:
    return package_dir().parent.parent


def src_root_dir() -> Path:
    return package_dir().parent


def assets_dir() -> Path:
    return package_dir() / "resources" / "assets"


def asset_path(*parts: str) -> Path:
    return assets_dir().joinpath(*parts)


def tests_dir() -> Path:
    return project_root_dir() / "tests"


def test_fixture_path(*parts: str) -> Path:
    return tests_dir().joinpath("fixtures", *parts)


def config_root_dir() -> Path:
    custom_dir = os.environ.get("MSGFLOW_CONFIG_DIR")
    if custom_dir:
        return Path(os.path.expanduser(custom_dir))
    return Path(os.path.expanduser(DEFAULT_CONFIG_DIR))


def runtime_config_dir(debug: bool = False) -> Path:
    base_dir = config_root_dir()
    if debug:
        return base_dir / DEBUG_CONFIG_SUBDIR
    return base_dir


def config_file_path(debug: bool = False) -> Path:
    return runtime_config_dir(debug) / CONFIG_FILE_NAME


def history_file_path(debug: bool = False) -> Path:
    return runtime_config_dir(debug) / HISTORY_FILE_NAME


def logs_dir(debug: bool = False) -> Path:
    return runtime_config_dir(debug) / LOGS_DIR_NAME


def app_log_path() -> Path:
    return logs_dir(False) / LOG_FILE_NAME


def managed_core_log_path() -> Path:
    return logs_dir(False) / LOG_FILE_NAME


def brew_service_log_path() -> Path:
    return logs_dir(False) / BREW_SERVICE_LOG_FILE_NAME


def sms_db_path() -> Path:
    return Path(os.path.expanduser(SMS_DB_PATH))


def notify_db_path() -> Path:
    return Path(os.path.expanduser(NOTIFY_DB_PATH))


def ipn_remote_path() -> Path:
    return Path(os.path.expanduser(IPN_REMOTE_PATH))


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def ui_launch_command() -> list[str]:
    if is_frozen():
        return [str(Path(sys.executable).resolve())]
    return [sys.executable, str(project_root_dir() / "app.py")]


def _with_src_pythonpath(env: dict[str, str]) -> dict[str, str]:
    src_root = str(src_root_dir())
    existing = env.get("PYTHONPATH")
    if not existing:
        env["PYTHONPATH"] = src_root
        return env
    parts = existing.split(os.pathsep)
    if src_root not in parts:
        env["PYTHONPATH"] = os.pathsep.join([src_root, existing])
    return env


def ui_launch_environment() -> dict[str, str]:
    env = dict(os.environ)
    if is_frozen():
        return env
    return _with_src_pythonpath(env)


def managed_core_command(debug: bool = False) -> list[str]:
    custom_core = os.environ.get("MSGFLOW_CORE_EXECUTABLE")
    if custom_core:
        command = [os.path.expanduser(custom_core)]
    elif is_frozen():
        bundled_core = Path(sys.executable).resolve().with_name(MANAGED_CORE_EXECUTABLE_NAME)
        command = [str(bundled_core)]
    else:
        command = [sys.executable, str(project_root_dir() / "core.py")]
    if debug:
        command.append("-d")
    return command


def managed_core_environment() -> dict[str, str]:
    env = dict(os.environ)
    if is_frozen():
        return env
    return _with_src_pythonpath(env)
