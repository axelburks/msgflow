from typing import Any, Optional
from urllib.parse import urlencode

from ..common.run_models import RunQueryFilters
from .transport import RPCError, core_socket_path, request


CORE_RPC_TIMEOUT = 5
CORE_STATUS_TIMEOUT = 0.5


def _request(
    method: str,
    path: str,
    payload: Optional[dict[str, Any]] = None,
    *,
    timeout: float = CORE_RPC_TIMEOUT,
    allow_error_field: bool = False,
) -> dict[str, Any]:
    try:
        data = request(
            core_socket_path(),
            {
                "method": method,
                "path": path,
                "payload": payload or {},
            },
            timeout=timeout,
        )
    except RPCError as e:
        if allow_error_field:
            return e.payload
        raise
    if data.get("error") and not allow_error_field:
        raise ValueError(str(data["error"]))
    return data


def get_status(timeout: float = CORE_STATUS_TIMEOUT) -> dict[str, Any]:
    return _request("GET", "/runtime/status", timeout=timeout, allow_error_field=True)


def start_listener() -> dict[str, Any]:
    return _request("POST", "/runtime/start")


def pause_listener() -> dict[str, Any]:
    return _request("POST", "/runtime/pause")


def get_built_config() -> dict[str, Any]:
    return _request("GET", "/config/built")


def get_cursor_state(kind: Optional[str] = None) -> dict[str, Any]:
    if kind is None or not str(kind).strip():
        return _request("GET", "/runtime/cursor")
    return _request("GET", f"/runtime/cursor?{urlencode({'kind': kind})}")


def update_cursor_state(kind: str, cursor_map: dict[str, float]) -> dict[str, Any]:
    return _request(
        "POST",
        "/runtime/cursor",
        {
            "kind": kind,
            "cursor_map": cursor_map,
        },
    )


def list_runs(filters: RunQueryFilters) -> dict[str, Any]:
    params: dict[str, Any] = {
        "limit": filters.limit,
        "offset": filters.offset,
    }
    if filters.kind is not None:
        params["kind"] = filters.kind
    if filters.trigger_type is not None:
        params["trigger_type"] = filters.trigger_type
    if filters.status is not None:
        params["status"] = filters.status
    if filters.query:
        params["query"] = filters.query
    return _request("GET", f"/records/runs?{urlencode(params)}")


def get_message_detail(message_id: int) -> dict[str, Any]:
    return _request("GET", f"/records/messages/{message_id}")


def get_run(run_id: int) -> dict[str, Any]:
    return _request("GET", f"/records/runs/{run_id}")


def delete_run(run_id: int) -> dict[str, Any]:
    return _request("POST", f"/records/runs/{run_id}/delete")


def rematch_and_send(message_id: int) -> dict[str, Any]:
    return _request("POST", f"/records/messages/{message_id}/rematch")


def resend_destination(message_id: int, rule_name: str, dest_name: str) -> dict[str, Any]:
    return _request(
        "POST",
        f"/records/messages/{message_id}/resend",
        {
            "rule_name": rule_name,
            "dest_name": dest_name,
        },
    )
