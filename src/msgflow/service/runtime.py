import threading
import time
import logging
import os
from pathlib import Path
from typing import Any, Optional

from .. import config
from ..common.authorization import resolve_full_disk_access_target
from ..common.paths import ipn_remote_path, notify_db_path, sms_db_path
from ..common.run_models import MESSAGE_KINDS, RunQueryFilters
from .history import HistoryStore
from .flows.notify import NotifyFlow
from .flows.ipn import IPNFlow
from .flows.sms import SMSFlow
from .litedb import LiteDB

logger = logging.getLogger(__name__)


def _sms_enabled() -> bool:
    return bool(config.cfg and config.cfg.built_cfg.get("sms", {}).get("rules"))


def _notify_enabled() -> bool:
    return bool(config.cfg and config.cfg.built_cfg.get("notify", {}).get("rules"))


def _ipn_enabled() -> bool:
    return bool(config.cfg and config.cfg.built_cfg.get("ipn", {}).get("rules"))


def _source_display_name(kind: str) -> str:
    if kind == "sms":
        return "SMS"
    if kind == "notify":
        return "Notify"
    if kind == "ipn":
        return "IPN"
    return kind


class CoreRuntime(object):
    """Long-lived runtime state shared by listeners, replay actions and UI RPC."""

    CLEANUP_COUNT_INTERVAL = 100
    CLEANUP_DAYS_INTERVAL_SECONDS = 24 * 60 * 60

    def __init__(self) -> None:
        if config.cfg is None:
            raise ValueError("config.cfg is not initialized")
        self.cfg = config.cfg
        self.check_interval = self.cfg.built_cfg.get("check_interval")
        self.status = "running"
        self.error: dict[str, Any] | None = None
        self.history = HistoryStore(self.cfg.history_file_path)
        self.retention = dict(self.cfg.built_cfg.get("app", {}).get("retention") or {})
        self.insert_since_last_cleanup = 0
        self.last_cleanup_at = 0.0
        self.flows: list[Any] = []
        self._loop_thread_id: int | None = None
        self._control_lock = threading.Lock()
        self._control_event = threading.Event()
        self._pending_command: str | None = None
        self._pending_source_checks: set[str] = set()
        self.refresh_runtime_health(build_flows=True)

    def bind_loop_thread(self) -> None:
        self._loop_thread_id = threading.get_ident()

    def _is_loop_thread(self) -> bool:
        return self._loop_thread_id is None or self._loop_thread_id == threading.get_ident()

    def _set_pending_command(self, command: str) -> None:
        with self._control_lock:
            self._pending_command = command
            self._control_event.set()

    def request_start_listener(self) -> None:
        self._set_pending_command("start")

    def request_pause_listener(self) -> None:
        self._set_pending_command("pause")

    def pop_pending_command(self) -> str | None:
        with self._control_lock:
            command = self._pending_command
            self._pending_command = None
            self._control_event.clear()
            return command

    def wait_for_control_signal(self, timeout: float) -> bool:
        return self._control_event.wait(timeout=max(0.0, timeout))

    def request_source_check(self, kind: str) -> None:
        with self._control_lock:
            self._pending_source_checks.add(kind)
            self._control_event.set()

    def pop_pending_source_checks(self) -> set[str]:
        with self._control_lock:
            checks = set(self._pending_source_checks)
            self._pending_source_checks.clear()
            if self._pending_command is None:
                self._control_event.clear()
            return checks

    def _enabled_source_checks(self) -> list[tuple[str, Path]]:
        checks: list[tuple[str, Path]] = []
        if _sms_enabled():
            checks.append(("sms", sms_db_path()))
        if _notify_enabled():
            checks.append(("notify", notify_db_path()))
        if _ipn_enabled():
            checks.append(("ipn", ipn_remote_path()))
        return checks

    def _probe_source_access(self, kind: str, path: Path) -> None:
        if kind in ("sms", "notify"):
            LiteDB.probe_read_access(str(path))
            return
        if kind == "ipn":
            if not path.exists():
                raise FileNotFoundError(path)
            library_path = path / "Library.plist"
            if library_path.exists():
                with open(library_path, "rb"):
                    pass
            else:
                with os.scandir(path):
                    pass
            return
        raise ValueError(f"unknown source kind: {kind}")

    def _permission_issue(self, kind: str, db_path: Path, error: Exception) -> dict[str, Any]:
        authorization_target = resolve_full_disk_access_target()
        source_name = _source_display_name(kind)
        authorization_target_kind = authorization_target["kind"]
        authorization_target_name = authorization_target["name"]
        if authorization_target_kind == "msgflow_app":
            authorization_message = (
                f"Grant Full Disk Access to {authorization_target_name} and retry."
            )
        else:
            authorization_message = (
                "Grant Full Disk Access to the terminal app that launched this command "
                "(for example, Terminal.app or iTerm.app) and retry."
            )
        return {
            "kind": kind,
            "code": "db_access_denied",
            "requires_authorization": True,
            "path": str(db_path),
            "source_name": source_name,
            "authorization_target_kind": authorization_target_kind,
            "authorization_target_name": authorization_target_name,
            "message": (
                f"{source_name} is enabled, but msgflow-core cannot access {db_path}. "
                f"{authorization_message}"
            ),
            "detail": str(error),
        }

    def _collect_runtime_issues(self) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        for kind, db_path in self._enabled_source_checks():
            try:
                self._probe_source_access(kind, db_path)
            except Exception as e:
                issues.append(self._permission_issue(kind, db_path, e))
        return issues

    def _set_runtime_error(self, code: str, message: str, issues: list[dict[str, Any]] | None = None) -> None:
        self.close_flows()
        self.flows = []
        self.status = "error"
        self.error = {
            "code": code,
            "message": message,
            "issues": list(issues or []),
        }

    def refresh_runtime_health(self, build_flows: bool = True) -> bool:
        issues = self._collect_runtime_issues()
        if issues:
            if len(issues) == 1:
                message = issues[0]["message"]
            else:
                joined_sources = ", ".join(issue["source_name"] for issue in issues)
                authorization_target_kind = issues[0]["authorization_target_kind"]
                if authorization_target_kind == "msgflow_app":
                    message = (
                        f"{joined_sources} are enabled, but msgflow-core cannot access the required databases. "
                        "Grant Full Disk Access to msgflow-app and retry."
                    )
                else:
                    message = (
                        f"{joined_sources} are enabled, but msgflow-core cannot access the required databases. "
                        "Grant Full Disk Access to the terminal app that launched this and retry."
                    )
            self._set_runtime_error("permission_denied", message, issues=issues)
            return False
        try:
            if build_flows:
                self.build_flows()
            else:
                self.flows = []
        except Exception as e:
            self._set_runtime_error("flow_init_failed", str(e))
            return False
        if not self.flows and build_flows:
            self._set_runtime_error("no_enabled_flows", "No SMS, Notify or iPhone rules are configured, nothing to monitor.")
            return False
        if self.status == "error":
            self.status = "running"
        self.error = None
        return True

    def get_built_config(self) -> dict[str, Any]:
        return {
            "built_cfg": self.cfg.built_cfg,
            "config_file_path": self.cfg.config_file_path,
            "debug_mode": self.cfg.debug_mode,
        }

    def build_flows(self) -> None:
        self.close_flows()
        self.flows = []
        if _sms_enabled():
            self.flows.append(SMSFlow(runtime=self))
        if _notify_enabled():
            self.flows.append(NotifyFlow(runtime=self))
        if _ipn_enabled():
            self.flows.append(IPNFlow(runtime=self))

    def ensure_flows_built(self) -> None:
        if not self.flows:
            if not self._is_loop_thread():
                raise RuntimeError("runtime flows are not ready yet")
            if not self.refresh_runtime_health(build_flows=True):
                raise RuntimeError(self.error["message"] if self.error else "runtime is not ready")

    def close_flows(self) -> None:
        for flow in self.flows:
            close = getattr(flow, "close", None)
            if not callable(close):
                continue
            try:
                close()
            except Exception as e:
                logger.warning("failed to close flow %s: %s", getattr(flow, "KIND", type(flow).__name__), e)

    def start_listener(self) -> None:
        if self.refresh_runtime_health(build_flows=True):
            self.status = "running"
            logger.info("listener started")
            return
        if self.error:
            logger.error("listener failed to start: %s", self.error.get("message") or "unknown error")

    def pause_listener(self) -> None:
        self.status = "paused"
        logger.info("listener paused")

    def apply_pending_command(self) -> str | None:
        command = self.pop_pending_command()
        if command == "start":
            self.start_listener()
        elif command == "pause":
            self.pause_listener()
        return command

    def get_status(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "source": self.cfg.built_cfg.get("source"),
            "retention": self.retention,
            "error": self.error,
            "pending_command": self._pending_command,
        }

    def get_flow_by_kind(self, kind: str) -> Any:
        self.ensure_flows_built()
        for flow in self.flows:
            if flow.KIND == kind:
                return flow
        raise ValueError(f"flow for kind '{kind}' is not enabled")

    def _validate_kind(self, kind: str) -> str:
        selected_kind = str(kind or "").strip().lower()
        if selected_kind not in MESSAGE_KINDS:
            raise ValueError(f"kind must be one of: {', '.join(MESSAGE_KINDS)}")
        return selected_kind

    def _configured_destinations_for_kind(self, kind: str) -> list[str]:
        rules = self.cfg.built_cfg.get(kind, {}).get("rules") or []
        destinations: list[str] = []
        seen: set[str] = set()
        for rule in rules:
            for dest in rule.get("destinations") or []:
                dest_name = dest.get("name_mark")
                if not isinstance(dest_name, str) or not dest_name or dest_name in seen:
                    continue
                seen.add(dest_name)
                destinations.append(dest_name)
        return destinations

    def get_cursor_state(self, kind: Optional[str]) -> dict[str, Any]:
        selected_kind = self._validate_kind(kind) if kind else None
        return {"items": self.history.get_cursor_map(selected_kind)}

    def update_cursor_state(self, kind: str, cursor_map: dict[str, Any]) -> dict[str, Any]:
        selected_kind = self._validate_kind(kind)
        if not isinstance(cursor_map, dict) or not cursor_map:
            raise ValueError("cursor_map must be a non-empty object")
        allowed_destinations = set(self._configured_destinations_for_kind(selected_kind))
        if not allowed_destinations:
            raise ValueError(f"no configured destinations found for '{selected_kind}'")
        normalized_map: dict[str, float] = {}
        for destination, cursor_value in cursor_map.items():
            dest_name = str(destination or "").strip()
            if not dest_name:
                raise ValueError("destination name cannot be empty")
            if dest_name not in allowed_destinations:
                raise ValueError(f"unknown destination '{dest_name}' for '{selected_kind}'")
            if not isinstance(cursor_value, (int, float)) or isinstance(cursor_value, bool):
                raise ValueError(f"cursor for '{dest_name}' must be numeric")
            normalized_map[dest_name] = float(cursor_value)
        if not normalized_map:
            raise ValueError("no valid cursor values provided")
        self.history.set_cursor_map(selected_kind, normalized_map)
        for flow in self.flows:
            if flow.KIND != selected_kind:
                continue
            for dest_name, cursor_value in normalized_map.items():
                flow.cursor[dest_name] = cursor_value
            flow.min_cursor = min(flow.cursor.values()) if flow.cursor else 0.0
            break
        return self.get_cursor_state(selected_kind)

    def list_runs(self, filters: RunQueryFilters) -> dict[str, Any]:
        return self.history.list_runs(
            limit=filters.limit,
            offset=filters.offset,
            kind=filters.kind,
            trigger_type=filters.trigger_type,
            status=filters.status,
            query=filters.query,
        )

    def get_message_detail(self, message_id: int) -> dict[str, Any] | None:
        return self.history.get_message_detail(message_id)

    def get_run(self, run_id: int) -> dict[str, Any] | None:
        return self.history.get_run(run_id)

    def delete_run(self, run_id: int) -> bool:
        return self.history.delete_run(run_id)

    def history_inserted(self) -> None:
        self.insert_since_last_cleanup += 1

    def maybe_cleanup_history(self, force: bool = False) -> int:
        # Retention is evaluated per kind (`sms` / `notify`) so each stream can
        # choose its own cleanup mode and threshold.
        #
        # `count` mode:
        # - Triggered lazily after every 100 inserted messages, unless `force`.
        # - If a kind exceeds `value`, old rows of that kind are deleted.
        # - Deletion is batched down to a low-water mark instead of stopping at
        #   exactly `value`, reducing cleanup frequency. Example: keep=5000
        #   deletes down to 4500.
        #
        # `days` mode:
        # - Triggered at most once per day, unless `force`.
        # - Deletes rows of that kind whose `created_at` is older than
        #   `value` days.
        # - Unlike `count` mode, there is no low-water mark. A daily cleanup is
        #   already coarse enough, so deleting exactly by age keeps the rule
        #   intuitive: retain the most recent `value` days of data.
        now = time.time()
        deleted = 0
        has_count_mode = any(
            isinstance(self.retention.get(kind), dict) and self.retention.get(kind, {}).get("mode") == "count"
            for kind in MESSAGE_KINDS
        )
        has_days_mode = any(
            isinstance(self.retention.get(kind), dict) and self.retention.get(kind, {}).get("mode") == "days"
            for kind in MESSAGE_KINDS
        )
        if has_count_mode:
            if not force and self.insert_since_last_cleanup < self.CLEANUP_COUNT_INTERVAL:
                has_count_mode = False
            else:
                self.insert_since_last_cleanup = 0
                for kind in MESSAGE_KINDS:
                    retention = self.retention.get(kind)
                    if not isinstance(retention, dict) or retention.get("mode") != "count":
                        continue
                    value = retention.get("value")
                    if not isinstance(value, int) or value <= 0:
                        continue
                    low_water = max(1, value - max(500, value // 10))
                    deleted += self.history.cleanup_by_count(kind, value, low_water_count=low_water)
        if has_days_mode:
            if not force and (now - self.last_cleanup_at) < self.CLEANUP_DAYS_INTERVAL_SECONDS:
                has_days_mode = False
            else:
                self.last_cleanup_at = now
                for kind in MESSAGE_KINDS:
                    retention = self.retention.get(kind)
                    if not isinstance(retention, dict) or retention.get("mode") != "days":
                        continue
                    value = retention.get("value")
                    if not isinstance(value, int) or value <= 0:
                        continue
                    deleted += self.history.cleanup_by_days(kind, value)
        if has_count_mode or has_days_mode:
            return deleted
        return 0
