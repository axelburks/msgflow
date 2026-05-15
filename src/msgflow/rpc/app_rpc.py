from typing import Any

import requests


APP_RPC_BASE_URL = "http://127.0.0.1:39402"
APP_RPC_TIMEOUT = 3


def _post(path: str, payload: dict[str, Any]) -> tuple[bool, str]:
    try:
        response = requests.post(
            f"{APP_RPC_BASE_URL}{path}",
            json=payload,
            timeout=APP_RPC_TIMEOUT,
        )
        if response.status_code != 200:
            return False, f"app rpc error: {response.status_code} {response.text}"
        return True, response.text
    except Exception as e:
        return False, f"app rpc error: {e}"


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
