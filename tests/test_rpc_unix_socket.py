import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from msgflow.common.run_models import RunQueryFilters
from msgflow.rpc import app_rpc, core_client, transport
from msgflow.rpc.core_rpc import CoreRPCServer
from msgflow.rpc.ui_rpc import UIRPCServer


def _short_config_dir(name: str) -> tempfile.TemporaryDirectory[str]:
    # Keep the config dir short enough for macOS AF_UNIX path limits while
    # still exercising the production config-dir based socket path.
    return tempfile.TemporaryDirectory(prefix=f"mf-cfg-{name}-", dir="/tmp")


class FakeCoreRuntime:
    def __init__(self):
        self.commands = []
        self.last_filters = None
        self.cursor_updates = []

    def get_status(self):
        return {"status": "running"}

    def request_start_listener(self):
        self.commands.append("start")

    def request_pause_listener(self):
        self.commands.append("pause")

    def get_built_config(self):
        return {"app": {"name": "msgflow"}}

    def get_cursor_state(self, kind=None):
        return {"kind": kind}

    def update_cursor_state(self, kind, cursor_map):
        self.cursor_updates.append((kind, cursor_map))
        return {"items": [{"kind": kind, "cursor_map": cursor_map}]}

    def list_runs(self, filters: RunQueryFilters):
        self.last_filters = filters
        return {"items": [{"id": 1}], "total": 1}

    def get_message_detail(self, message_id):
        return {"id": message_id}

    def get_run(self, run_id):
        return {"id": run_id}

    def delete_run(self, run_id):
        return run_id == 1


def test_rpc_runtime_dir_uses_config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MSGFLOW_CONFIG_DIR", str(tmp_path))

    assert transport.rpc_runtime_dir() == tmp_path / "run"
    assert transport.core_socket_path() == tmp_path / "run" / "core.sock"
    assert transport.app_socket_path() == tmp_path / "run" / "app.sock"


def test_core_rpc_uses_unix_socket_transport(monkeypatch):
    runtime = FakeCoreRuntime()
    with _short_config_dir("core") as config_dir:
        monkeypatch.setenv("MSGFLOW_CONFIG_DIR", config_dir)
        socket_path = transport.core_socket_path()
        assert socket_path == Path(config_dir) / "run" / "core.sock"
        server = CoreRPCServer(runtime)

        server.start()
        try:
            assert core_client.get_status() == {"status": "running"}
            assert core_client.start_listener() == {"status": "accepted"}
            assert core_client.get_cursor_state("sms") == {"kind": "sms"}
            assert core_client.update_cursor_state("notify", {"dest": 3.5})["items"][0]["cursor_map"] == {"dest": 3.5}
            assert core_client.list_runs(RunQueryFilters(limit=5, offset=2, kind="sms"))["total"] == 1
        finally:
            server.stop()

    assert runtime.commands == ["start"]
    assert runtime.cursor_updates == [("notify", {"dest": 3.5})]
    assert runtime.last_filters.limit == 5
    assert runtime.last_filters.offset == 2
    assert runtime.last_filters.kind == "sms"
    assert not socket_path.exists()


def test_core_client_raises_for_rpc_errors(monkeypatch):
    runtime = FakeCoreRuntime()
    with _short_config_dir("core-error") as config_dir:
        monkeypatch.setenv("MSGFLOW_CONFIG_DIR", config_dir)
        server = CoreRPCServer(runtime)

        server.start()
        try:
            with pytest.raises(Exception, match="not found"):
                core_client._request("GET", "/missing")
        finally:
            server.stop()


def test_app_rpc_uses_unix_socket_transport(monkeypatch):
    calls = []
    controller = SimpleNamespace(
        show_notification=lambda title, body: calls.append(("notification", title, body)),
        show_floating=lambda title, body, input_text: calls.append(("floating", title, body, input_text)),
    )
    with _short_config_dir("app") as config_dir:
        monkeypatch.setenv("MSGFLOW_CONFIG_DIR", config_dir)
        socket_path = transport.app_socket_path()
        assert socket_path == Path(config_dir) / "run" / "app.sock"
        server = UIRPCServer(controller)

        server.start()
        try:
            ok, text = app_rpc.show_notification("Title", "Body")
            assert ok is True
            assert text == '{"status":"ok"}'
            ok, text = app_rpc.show_floating("Title", "Body", "123456")
            assert ok is True
            assert text == '{"status":"ok"}'
        finally:
            server.stop()

    assert calls == [
        ("notification", "Title", "Body"),
        ("floating", "Title", "Body", "123456"),
    ]
    assert not socket_path.exists()
