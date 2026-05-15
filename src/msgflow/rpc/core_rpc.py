import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from ..common.run_models import MESSAGE_KINDS, RunQueryFilters, RUN_STATUSES, RUN_TRIGGER_TYPES
from ..service.replay import rematch_and_send, resend_destination
from ..service.runtime import CoreRuntime


class _CoreRPCHandler(BaseHTTPRequestHandler):
    runtime: CoreRuntime

    def log_message(self, _format: str, *unused_args: Any) -> None:
        return

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length") or 0)
        if content_length <= 0:
            return {}
        raw = self.rfile.read(content_length)
        if not raw:
            return {}
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("json body must be an object")
        return data

    def _handle_exception(self, e: Exception) -> None:
        self._send_json({"error": str(e)}, status=400)

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

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)
            if path == "/runtime/status":
                self._send_json(self.runtime.get_status())
                return
            if path == "/runtime/cursor":
                kind_raw = (query.get("kind") or [""])[0].strip().lower()
                self._send_json(self.runtime.get_cursor_state(kind_raw or None))
                return
            if path == "/config/built":
                self._send_json(self.runtime.get_built_config())
                return
            if path == "/records/runs":
                self._send_json(self.runtime.list_runs(self._parse_run_filters(query)))
                return
            if path.startswith("/records/messages/"):
                message_id = self._parse_tail_id(path, prefix="/records/messages/")
                detail = self.runtime.get_message_detail(message_id)
                if detail is None:
                    self._send_json({"error": "message not found"}, status=404)
                    return
                self._send_json(detail)
                return
            if path.startswith("/records/runs/"):
                run_id = self._parse_tail_id(path, prefix="/records/runs/")
                run = self.runtime.get_run(run_id)
                if run is None:
                    self._send_json({"error": "run not found"}, status=404)
                    return
                self._send_json(run)
                return
            self._send_json({"error": "not found"}, status=404)
        except Exception as e:
            self._handle_exception(e)

    def do_POST(self) -> None:
        try:
            path = urlparse(self.path).path
            if path == "/runtime/start":
                self.runtime.request_start_listener()
                self._send_json({"status": "accepted"})
                return
            if path == "/runtime/pause":
                self.runtime.request_pause_listener()
                self._send_json({"status": "accepted"})
                return
            if path == "/runtime/cursor":
                body = self._read_json_body()
                kind = str(body.get("kind") or "").strip().lower()
                cursor_map = body.get("cursor_map")
                self._send_json(self.runtime.update_cursor_state(kind, cursor_map))
                return
            if path.startswith("/records/runs/") and path.endswith("/delete"):
                run_id = self._parse_nested_id(path, prefix="/records/runs/", suffix="/delete")
                deleted = self.runtime.delete_run(run_id)
                self._send_json({"deleted": deleted})
                return
            if path.startswith("/records/messages/") and path.endswith("/rematch"):
                message_id = self._parse_nested_id(path, prefix="/records/messages/", suffix="/rematch")
                result = rematch_and_send(self.runtime, message_id)
                self._send_json(
                    {
                        "run_id": result.get("run_id"),
                        "status": result.get("status"),
                    }
                )
                return
            if path.startswith("/records/messages/") and path.endswith("/resend"):
                message_id = self._parse_nested_id(path, prefix="/records/messages/", suffix="/resend")
                body = self._read_json_body()
                rule_name = body.get("rule_name")
                dest_name = body.get("dest_name")
                if not rule_name or not dest_name:
                    raise ValueError("rule_name and dest_name are required")
                result = resend_destination(self.runtime, message_id, rule_name, dest_name)
                self._send_json(
                    {
                        "run_id": result.get("run_id"),
                        "status": result.get("status"),
                    }
                )
                return
            self._send_json({"error": "not found"}, status=404)
        except Exception as e:
            self._handle_exception(e)

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
    def __init__(self, runtime: CoreRuntime, host: str = "127.0.0.1", port: int = 39401) -> None:
        self.runtime = runtime
        self.host = host
        self.port = port
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._server is not None:
            return
        handler = type("CoreRPCHandler", (_CoreRPCHandler,), {"runtime": self.runtime})
        self._server = ThreadingHTTPServer((self.host, self.port), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is None:
            return
        try:
            self._server.shutdown()
            self._server.server_close()
        finally:
            self._server = None
            self._thread = None
