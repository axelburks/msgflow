import json
from typing import Any

from .transport import APP_SOCKET_NAME, RPCError, app_socket_path, request


APP_RPC_TIMEOUT = 3


def _post(path: str, payload: dict[str, Any]) -> tuple[bool, str]:
    try:
        response = request(
            app_socket_path(),
            {
                "method": "POST",
                "path": path,
                "payload": payload,
            },
            timeout=APP_RPC_TIMEOUT,
        )
        return True, json.dumps(response, ensure_ascii=False, default=str, separators=(",", ":"))
    except RPCError as e:
        return False, f"{APP_SOCKET_NAME} rpc error: {e.status} {e.payload}"
    except Exception as e:
        return False, f"{APP_SOCKET_NAME} rpc error: {e}"


def show_notification(title: str, body: str) -> tuple[bool, str]:
    return _post(
        "/ui/notification",
        {
            "title": title,
            "body": body,
        },
    )


def show_floating(title: str, body: str, input_text: str) -> tuple[bool, str]:
    return _post(
        "/ui/floating",
        {
            "title": title,
            "body": body,
            "input": input_text,
        },
    )
