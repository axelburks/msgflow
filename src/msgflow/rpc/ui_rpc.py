from pathlib import Path
from typing import Any, Optional

from .transport import UnixRPCServer, app_socket_path


class _UIRPCDispatcher(object):
    def __init__(self, app_controller: Any) -> None:
        self.app_controller = app_controller

    def dispatch(self, request: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        try:
            method = str(request.get("method") or "").upper()
            path = str(request.get("path") or "")
            body = request.get("payload") or {}
            if method != "POST":
                return 405, {"error": "method not allowed"}
            if not isinstance(body, dict):
                raise ValueError("json body must be an object")
            if path == "/ui/notification":
                self.app_controller.show_notification(body.get("title") or "", body.get("body") or "")
                return 200, {"status": "ok"}
            if path == "/ui/floating":
                self.app_controller.show_floating(
                    body.get("title") or "",
                    body.get("body") or "",
                    body.get("input") or "",
                )
                return 200, {"status": "ok"}
            return 404, {"error": "not found"}
        except Exception as e:
            return 400, {"error": str(e)}


class UIRPCServer(object):
    def __init__(self, app_controller: Any, socket_path: Optional[Path] = None) -> None:
        self.app_controller = app_controller
        self.socket_path = socket_path or app_socket_path()
        self._dispatcher = _UIRPCDispatcher(app_controller)
        self._server = UnixRPCServer(self.socket_path, self._dispatcher.dispatch)

    def start(self) -> None:
        self._server.start()

    def stop(self) -> None:
        self._server.stop()
