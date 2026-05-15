from __future__ import annotations

import json
import os
import socket
import socketserver
import struct
import threading
from pathlib import Path
from typing import Any, Callable, Optional

from ..common.paths import config_root_dir


MAX_FRAME_BYTES = 10 * 1024 * 1024
FRAME_HEADER_BYTES = 4
RPC_DIR_NAME = "run"
CORE_SOCKET_NAME = "core.sock"
APP_SOCKET_NAME = "app.sock"


class RPCError(RuntimeError):
    def __init__(self, status: int, payload: dict[str, Any]) -> None:
        self.status = status
        self.payload = payload
        super().__init__(str(payload.get("error") or f"rpc error: {status}"))


def rpc_runtime_dir() -> Path:
    return config_root_dir() / RPC_DIR_NAME


def core_socket_path() -> Path:
    return rpc_runtime_dir() / CORE_SOCKET_NAME


def app_socket_path() -> Path:
    return rpc_runtime_dir() / APP_SOCKET_NAME


def _prepare_socket_dir(socket_path: Path) -> None:
    socket_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(socket_path.parent, 0o700)
    except OSError:
        pass


def _remove_stale_socket(socket_path: Path) -> None:
    if not socket_path.exists():
        return
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.settimeout(0.1)
        probe.connect(str(socket_path))
    except OSError:
        socket_path.unlink(missing_ok=True)
        return
    finally:
        probe.close()
    raise OSError(f"unix socket already in use: {socket_path}")


def _read_exact(sock: socket.socket, byte_count: int) -> bytes:
    chunks: list[bytes] = []
    remaining = byte_count
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise EOFError("unexpected end of rpc frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_frame(sock: socket.socket) -> dict[str, Any]:
    header = _read_exact(sock, FRAME_HEADER_BYTES)
    (body_len,) = struct.unpack("!I", header)
    if body_len <= 0 or body_len > MAX_FRAME_BYTES:
        raise ValueError(f"invalid rpc frame length: {body_len}")
    body = _read_exact(sock, body_len)
    payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("rpc frame must contain a json object")
    return payload


def write_frame(sock: socket.socket, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_FRAME_BYTES:
        raise ValueError(f"rpc frame too large: {len(body)} bytes")
    sock.sendall(struct.pack("!I", len(body)) + body)


class _ThreadingUnixRPCServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: str,
        handler_class: type[socketserver.BaseRequestHandler],
        dispatcher: Callable[[dict[str, Any]], tuple[int, dict[str, Any]]],
    ) -> None:
        self.dispatcher = dispatcher
        super().__init__(server_address, handler_class)


class _UnixRPCRequestHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        try:
            request = read_frame(self.request)
            status, payload = self.server.dispatcher(request)  # type: ignore[attr-defined]
        except Exception as e:
            status, payload = 400, {"error": str(e)}
        write_frame(self.request, {"status": status, "payload": payload})


class UnixRPCServer(object):
    def __init__(
        self,
        socket_path: Path,
        dispatcher: Callable[[dict[str, Any]], tuple[int, dict[str, Any]]],
    ) -> None:
        self.socket_path = socket_path
        self.dispatcher = dispatcher
        self._server: Optional[_ThreadingUnixRPCServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._server is not None:
            return
        _prepare_socket_dir(self.socket_path)
        _remove_stale_socket(self.socket_path)
        self._server = _ThreadingUnixRPCServer(str(self.socket_path), _UnixRPCRequestHandler, self.dispatcher)
        os.chmod(self.socket_path, 0o600)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is None:
            return
        try:
            self._server.shutdown()
            self._server.server_close()
            self.socket_path.unlink(missing_ok=True)
        finally:
            self._server = None
            self._thread = None


def request(socket_path: Path, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect(str(socket_path))
        write_frame(sock, payload)
        response = read_frame(sock)
    status = int(response.get("status") or 0)
    body = response.get("payload")
    if not isinstance(body, dict):
        raise ValueError("rpc returned invalid json body")
    if status < 200 or status >= 300:
        raise RPCError(status, body)
    return body
