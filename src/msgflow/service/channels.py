import logging, json, html, subprocess
from typing import Any, Callable
import requests, pyperclip
from ..rpc.app_rpc import show_notification as app_show_notification, show_floating as app_show_floating

logger = logging.getLogger(__name__)


def channel(name: str) -> Callable:
    # Decorator that tags a method as the notifier for a specific channel name.
    # `build_channel_notifiers_for_cls` later collects every tagged method
    # into the CHANNEL_NOTIFIERS registry.
    def decorator(fn: Callable) -> Callable:
        fn._msgflow_channel = name  # type: ignore[attr-defined]
        return fn
    return decorator


def build_channel_notifiers_for_cls(cls: type) -> dict[str, Callable]:
    # Scan `cls` for every method decorated with @channel(...) and return
    # a {channel_name: method} mapping. Duplicate names are a hard error so
    # misconfigurations surface at import time.
    channel_notifiers: dict[str, Callable] = {}
    for attr in dir(cls):
        fn = getattr(cls, attr, None)
        if not callable(fn):
            continue
        channel_name = getattr(fn, "_msgflow_channel", None)
        if not channel_name:
            continue
        if channel_name in channel_notifiers:
            raise Exception(f"duplicate channel notifier for '{channel_name}'")
        channel_notifiers[channel_name] = fn
    return channel_notifiers


class Channels(object):
    """Channel dispatcher: hosts every @channel-registered notifier.
    Used as a mixin for MsgFlow."""

    def _format_http_response_text(self, res: requests.Response) -> str:
        # Prefer JSON (with UTF-8 preserved) when the response body parses; fall
        # back to raw text. Used purely for logging/error reporting.
        try:
            data = res.json()
            return json.dumps(data, ensure_ascii=False)
        except Exception:
            return res.text

    def _match_success_json(self, expected: Any, actual: Any) -> bool:
        # Structural "subset" match: `actual` is a success iff every key/index
        # required by `expected` exists and matches. Used by channels like Lark
        # that return 200 OK even on logical errors and must be disambiguated
        # via a JSON body check (e.g. {"code": 0}).
        if isinstance(expected, dict):
            if not isinstance(actual, dict):
                return False
            for k, v in expected.items():
                if k not in actual:
                    return False
                if not self._match_success_json(v, actual[k]):
                    return False
            return True
        if isinstance(expected, list):
            if not isinstance(actual, list):
                return False
            if len(expected) != len(actual):
                return False
            return all(self._match_success_json(e, a) for e, a in zip(expected, actual))
        return expected == actual

    @channel('webhook')
    def notify_to_webhook(self, dest: dict[str, Any]) -> tuple[bool, str]:
        # Generic HTTP webhook notifier. Other HTTP-based channels delegate to
        # this method so transport-level behavior (timeouts, logging, success
        # criteria) is shared.
        logmarker = dest.get("logmarker")
        dest_mark = f'{logmarker} {dest.get("name_mark")}({dest.get("channel")})'
        try:
            logger.info(f"{dest_mark}")
            method = dest.get("method").upper()
            url = dest.get("url")
            params = dest.get("params")
            headers = dest.get("headers")
            payload = dest.get("payload")
            timeout = dest.get("timeout")
            # Only forward kwargs that are actually provided so `requests`
            # applies its own defaults for the rest.
            req_kwargs: dict[str, Any] = {}
            if params is not None:
                req_kwargs["params"] = params
            if headers is not None:
                req_kwargs["headers"] = headers
            if payload is not None:
                req_kwargs["json"] = payload
            if timeout is not None:
                req_kwargs["timeout"] = timeout

            logger.debug(f"{dest_mark} request: {method} {url} {json.dumps(req_kwargs, ensure_ascii=False, default=str)}")
            res = requests.request(method, url, **req_kwargs)
            formatted_res_text = self._format_http_response_text(res)
            logger.debug(f"{dest_mark} response: {res.status_code} {formatted_res_text}")

            success_json = dest.get("success_json")
            if success_json is None:
                # No custom success criterion: 200 OK is success.
                if res.status_code != 200:
                    return False, f"{dest_mark} error: {formatted_res_text}"
                return True, formatted_res_text
            # Custom success criterion: response must be JSON AND match the
            # declared success_json shape (subset match).
            try:
                res_json = res.json()
            except Exception:
                return False, f"{dest_mark} error: invalid json response: {formatted_res_text}"
            if not self._match_success_json(success_json, res_json):
                return False, f"{dest_mark} error: {formatted_res_text}"
            return True, formatted_res_text
        except Exception as e:
            return False, f"{dest_mark} error: {e}"

    @channel('bark')
    def notify_to_bark(self, dest: dict[str, Any]) -> tuple[bool, str]:
        # Bark uses a plain POST to the configured URL; delegate to webhook.
        return self.notify_to_webhook(dest)

    @channel('pushgo')
    def notify_to_pushgo(self, dest: dict[str, Any]) -> tuple[bool, str]:
        # PushGo is also a plain HTTP POST webhook under the hood.
        return self.notify_to_webhook(dest)

    @channel('tgbot')
    def notify_to_tgbot(self, dest: dict[str, Any]) -> tuple[bool, str]:
        # Telegram Bot API. When parse_mode is HTML, we must escape the text
        # body (special chars like < > & would otherwise break the message).
        # If a verification code was extracted, wrap it in <code> tags so
        # Telegram renders it monospaced and tap-to-copy.
        try:
            payload = dest.get("payload")
            if (
                isinstance(payload, dict)
                and 'text' in payload
                and str(payload.get("parse_mode") or '').upper() == 'HTML'
            ):
                escaped_text = html.escape(payload.get("text"))
                code = dest.get("code")
                if code:
                    escaped_text = escaped_text.replace(code, f"<code>{code}</code>")
                payload["text"] = escaped_text
                dest["payload"] = payload
            return self.notify_to_webhook(dest)
        except Exception as e:
            logmarker = dest.get("logmarker")
            dest_mark = f'{logmarker} {dest.get("name_mark")}({dest.get("channel")})'
            return False, f"{dest_mark} error: {e}"

    @channel('lark')
    def notify_to_lark(self, dest: dict[str, Any]) -> tuple[bool, str]:
        # Lark uses webhook transport with a custom success_json check
        # ({"code": 0}) that's handled generically in notify_to_webhook.
        return self.notify_to_webhook(dest)

    @channel('notification')
    def notify_to_notification(self, dest: dict[str, Any]) -> tuple[bool, str]:
        # App-backed local notification. Kept as a local-only channel so the
        # current machine owns presentation while the forwarding pipeline still
        # uses the same destination abstraction as remote channels.
        logmarker = dest.get("logmarker")
        dest_mark = f'{logmarker} {dest.get("name_mark")}({dest.get("channel")})'
        logger.info(f"{dest_mark}")
        payload = dest.get("payload") or {}
        title = payload.get("title")
        body = payload.get("body")
        if not title or not body:
            return False, f"{dest_mark} error: title or body is empty in payload"
        cur_status, cur_res = app_show_notification(str(title), str(body))
        if not cur_status:
            fallback_status, fallback_res = self._osascript_notification(str(title), str(body))
            if fallback_status:
                logger.warning(f"{dest_mark} app rpc unavailable, using osascript fallback")
                cur_status, cur_res = True, f"{cur_res}; fallback: {fallback_res}"
        if cur_status and payload.get("autoCopy") == 1 and payload.get("copy"):
            self.save_to_clipboard(payload.get("copy"))
        if not cur_status:
            return False, f"{dest_mark} error: {cur_res}"
        return True, cur_res

    @channel('floating')
    def notify_to_floating(self, dest: dict[str, Any]) -> tuple[bool, str]:
        # Floating panel is also presented by the local app process. It shows
        # message content near the cursor and provides fixed Type/Paste actions.
        logmarker = dest.get("logmarker")
        dest_mark = f'{logmarker} {dest.get("name_mark")}({dest.get("channel")})'
        logger.info(f"{dest_mark}")
        payload = dest.get("payload") or {}
        title = payload.get("title")
        body = payload.get("body")
        input_text = payload.get("input")
        if not title or not body or input_text is None or input_text == '':
            return False, f"{dest_mark} error: title/body/input is empty in payload"
        cur_status, cur_res = app_show_floating(str(title), str(body), str(input_text))
        if not cur_status:
            return False, f"{dest_mark} error: {cur_res}"
        return True, cur_res

    def send_notification(self, title: str, body: str = "") -> None:
        # Send a notification to the local system without complex destination.
        if not title:
            logger.error("❌ notification title is empty")
        dest = {
            "channel": "notification",
            "payload": {
                "title": title,
                "body": body,
            },
        }
        status, result = self.notify_to_notification(dest)
        if not status:
            logger.error(f"❌ notification error: {result}")
    
    def _osascript_notification(self, title: str, body: str, subtitle: str = "") -> tuple[bool, str]:
        # Fallback used only for local notifications when the macOS app process
        # is not running. Floating panels intentionally do not downgrade.
        script = [
            "on run argv",
            "set notifTitle to item 1 of argv",
            "set notifBody to item 2 of argv",
            "if (count of argv) >= 3 then",
            "set notifSubtitle to item 3 of argv",
            'if notifSubtitle is not "" then',
            "display notification notifBody with title notifTitle subtitle notifSubtitle",
            'return "ok"',
            "end if",
            "end if",
            "display notification notifBody with title notifTitle",
            'return "ok"',
            "end run",
        ]
        try:
            command = ["osascript"]
            for line in script:
                command.extend(["-e", line])
            command.extend([title, body, subtitle])
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            if result.returncode != 0:
                error_text = (result.stderr or result.stdout).strip()
                return False, f"osascript error: {error_text or 'unknown error'}"
            return True, "osascript notification sent"
        except Exception as e:
            return False, f"osascript error: {e}"

    def save_to_clipboard(self, code: Any) -> None:
        # Thin wrapper so tests/other notifiers can stub out clipboard writes.
        pyperclip.copy(str(code))


# Channel registry discovered at import time via decorator tags.
CHANNEL_NOTIFIERS = build_channel_notifiers_for_cls(Channels)
# Tuple of all registered channel names (used by the config schema).
AVAILABLE_CHANNELS = tuple(CHANNEL_NOTIFIERS.keys())
# Local-only channels don't go out over the network; their cursors are reset
# on every startup (see MsgFlow.init_cursor).
LOCAL_CHANNELS = ("notification", "floating")
# Remote/HTTP channels: everything not in LOCAL_CHANNELS.
REQ_CHANNELS = tuple(c for c in AVAILABLE_CHANNELS if c not in LOCAL_CHANNELS)
