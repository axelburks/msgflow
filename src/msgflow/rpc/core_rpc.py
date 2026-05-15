from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from ..common.run_models import MESSAGE_KINDS, RunQueryFilters, RUN_STATUSES, RUN_TRIGGER_TYPES
from ..service.replay import rematch_and_send, resend_destination
from ..service.runtime import CoreRuntime
from .transport import UnixRPCServer, core_socket_path


class _CoreRPCDispatcher(object):
    def __init__(self, runtime: CoreRuntime) -> None:
        self.runtime = runtime

    def _parse_optional_enum_value(self, raw: str, allowed_values: tuple[str, ...], field_name: str) -> str | None:
        normalized = str(raw or "").strip().lower()
        if not normalized:
            return None
        if normalized not in allowed_values:
            raise ValueError(f"invalid {field_name}: {normalized}")
        return normalized

    def _parse_run_filters(self, params: dict[str, list[str]]) -> RunQueryFilters:
        limit = int((params.get("limit") or ["50"])[0])
        offset = int((params.get("offset") or ["0"])[0])
        if limit <= 0:
            raise ValueError("limit must be positive")
        if offset < 0:
            raise ValueError("offset must be non-negative")
        return RunQueryFilters(
            limit=limit,
            offset=offset,
            kind=self._parse_optional_enum_value((params.get("kind") or [""])[0], MESSAGE_KINDS, "kind"),
            trigger_type=self._parse_optional_enum_value(
                (params.get("trigger_type") or [""])[0],
                RUN_TRIGGER_TYPES,
                "trigger_type",
            ),
            status=self._parse_optional_enum_value((params.get("status") or [""])[0], RUN_STATUSES, "status"),
            query=(params.get("query") or [""])[0] or None,
        )

    def dispatch(self, request: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        try:
            method = str(request.get("method") or "").upper()
            parsed = urlparse(str(request.get("path") or ""))
            path = parsed.path
            query = parse_qs(parsed.query)
            body = request.get("payload") or {}
            if not isinstance(body, dict):
                raise ValueError("json body must be an object")
            if method == "GET":
                return self._handle_get(path, query)
            if method == "POST":
                return self._handle_post(path, body)
            return 405, {"error": "method not allowed"}
        except Exception as e:
            return 400, {"error": str(e)}

    def _handle_get(self, path: str, query: dict[str, list[str]]) -> tuple[int, dict[str, Any]]:
        if path == "/runtime/status":
            return 200, self.runtime.get_status()
        if path == "/runtime/cursor":
            kind_raw = (query.get("kind") or [""])[0].strip().lower()
            return 200, self.runtime.get_cursor_state(kind_raw or None)
        if path == "/config/built":
            return 200, self.runtime.get_built_config()
        if path == "/records/runs":
            return 200, self.runtime.list_runs(self._parse_run_filters(query))
        if path.startswith("/records/messages/"):
            message_id = self._parse_tail_id(path, prefix="/records/messages/")
            detail = self.runtime.get_message_detail(message_id)
            if detail is None:
                return 404, {"error": "message not found"}
            return 200, detail
        if path.startswith("/records/runs/"):
            run_id = self._parse_tail_id(path, prefix="/records/runs/")
            run = self.runtime.get_run(run_id)
            if run is None:
                return 404, {"error": "run not found"}
            return 200, run
        return 404, {"error": "not found"}

    def _handle_post(self, path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if path == "/runtime/start":
            self.runtime.request_start_listener()
            return 200, {"status": "accepted"}
        if path == "/runtime/pause":
            self.runtime.request_pause_listener()
            return 200, {"status": "accepted"}
        if path == "/runtime/cursor":
            kind = str(body.get("kind") or "").strip().lower()
            cursor_map = body.get("cursor_map")
            return 200, self.runtime.update_cursor_state(kind, cursor_map)
        if path.startswith("/records/runs/") and path.endswith("/delete"):
            run_id = self._parse_nested_id(path, prefix="/records/runs/", suffix="/delete")
            deleted = self.runtime.delete_run(run_id)
            return 200, {"deleted": deleted}
        if path.startswith("/records/messages/") and path.endswith("/rematch"):
            message_id = self._parse_nested_id(path, prefix="/records/messages/", suffix="/rematch")
            result = rematch_and_send(self.runtime, message_id)
            return 200, {
                "run_id": result.get("run_id"),
                "status": result.get("status"),
            }
        if path.startswith("/records/messages/") and path.endswith("/resend"):
            message_id = self._parse_nested_id(path, prefix="/records/messages/", suffix="/resend")
            rule_name = body.get("rule_name")
            dest_name = body.get("dest_name")
            if not rule_name or not dest_name:
                raise ValueError("rule_name and dest_name are required")
            result = resend_destination(self.runtime, message_id, rule_name, dest_name)
            return 200, {
                "run_id": result.get("run_id"),
                "status": result.get("status"),
            }
        return 404, {"error": "not found"}

    def _parse_tail_id(self, path: str, prefix: str) -> int:
        raw = path[len(prefix):].strip("/")
        if not raw:
            raise ValueError("missing id")
        return int(raw)

    def _parse_nested_id(self, path: str, prefix: str, suffix: str) -> int:
        raw = path[len(prefix):-len(suffix)].strip("/")
        if not raw:
            raise ValueError("missing id")
        return int(raw)


class CoreRPCServer(object):
    def __init__(self, runtime: CoreRuntime, socket_path: Optional[Path] = None) -> None:
        self.runtime = runtime
        self.socket_path = socket_path or core_socket_path()
        self._dispatcher = _CoreRPCDispatcher(runtime)
        self._server = UnixRPCServer(self.socket_path, self._dispatcher.dispatch)

    def start(self) -> None:
        self._server.start()

    def stop(self) -> None:
        self._server.stop()
