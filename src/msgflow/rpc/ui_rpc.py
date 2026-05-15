import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional
from urllib.parse import urlparse


class _UIRPCHandler(BaseHTTPRequestHandler):
    app_controller: Any

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
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("json body must be an object")
        return data

    def do_POST(self) -> None:
        try:
            path = urlparse(self.path).path
            body = self._read_json_body()
            if path == "/ui/notification":
                self.app_controller.show_notification(body.get("title") or "", body.get("body") or "")
                self._send_json({"status": "ok"})
                return
            if path == "/ui/floating":
                self.app_controller.show_floating(
                    body.get("title") or "",
                    body.get("body") or "",
                    body.get("input") or "",
                )
                self._send_json({"status": "ok"})
                return
            self._send_json({"error": "not found"}, status=404)
        except Exception as e:
            self._send_json({"error": str(e)}, status=400)


class UIRPCServer(object):
    def __init__(self, app_controller: Any, host: str = "127.0.0.1", port: int = 39402) -> None:
        self.app_controller = app_controller
        self.host = host
        self.port = port
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._server is not None:
            return
        handler = type("UIRPCHandler", (_UIRPCHandler,), {"app_controller": self.app_controller})
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
