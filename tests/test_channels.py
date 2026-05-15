import subprocess
from types import SimpleNamespace

import pytest

from msgflow.service import channels
from msgflow.service.channels import Channels, build_channel_notifiers_for_cls, channel


def test_channel_registry_contains_decorated_methods():
    assert {"webhook", "bark", "pushgo", "tgbot", "lark", "notification", "floating"} <= set(
        channels.AVAILABLE_CHANNELS
    )
    assert "notification" not in channels.REQ_CHANNELS
    assert "floating" not in channels.REQ_CHANNELS


def test_build_channel_notifiers_rejects_duplicate_channel_names():
    class DuplicateChannels:
        @channel("same")
        def first(self):
            return None

        @channel("same")
        def second(self):
            return None

    with pytest.raises(Exception, match="duplicate channel notifier"):
        build_channel_notifiers_for_cls(DuplicateChannels)


@pytest.mark.parametrize(
    "expected, actual, matched",
    [
        pytest.param({"code": 0}, {"code": 0, "msg": "ok"}, True, id="字典子集匹配"),
        pytest.param({"data": [1, {"ok": True}]}, {"data": [1, {"ok": True}]}, True, id="列表递归匹配"),
        pytest.param({"data": [1]}, {"data": [1, 2]}, False, id="列表长度必须一致"),
        pytest.param({"code": 0}, {"code": 1}, False, id="值不匹配"),
    ],
)
def test_match_success_json(expected, actual, matched):
    assert Channels()._match_success_json(expected, actual) is matched


def test_notify_to_webhook_sends_only_configured_request_kwargs(monkeypatch):
    response = SimpleNamespace(status_code=200, text="ok", json=lambda: {"ok": True})
    request_calls = []

    def fake_request(method, url, **kwargs):
        request_calls.append((method, url, kwargs))
        return response

    monkeypatch.setattr(channels.requests, "request", fake_request)

    ok, text = Channels().notify_to_webhook(
        {
            "logmarker": "web",
            "name_mark": "target",
            "channel": "webhook",
            "method": "post",
            "url": "https://example.test/hook",
            "headers": {"X-Test": "1"},
            "payload": {"msg": "hello"},
            "success_json": {"ok": True},
        }
    )

    assert ok is True
    assert text == '{"ok": true}'
    assert request_calls == [
        (
            "POST",
            "https://example.test/hook",
            {"headers": {"X-Test": "1"}, "json": {"msg": "hello"}},
        )
    ]


def test_notify_to_webhook_reports_http_and_success_json_failures(monkeypatch):
    monkeypatch.setattr(
        channels.requests,
        "request",
        lambda *args, **kwargs: SimpleNamespace(status_code=500, text="bad", json=lambda: {"code": 1}),
    )

    ok, text = Channels().notify_to_webhook(
        {"logmarker": "web", "name_mark": "target", "channel": "webhook", "method": "POST", "url": "https://x"}
    )
    assert ok is False
    assert "error: {\"code\": 1}" in text

    ok, text = Channels().notify_to_webhook(
        {
            "logmarker": "web",
            "name_mark": "target",
            "channel": "lark",
            "method": "POST",
            "url": "https://x",
            "success_json": {"code": 0},
        }
    )
    assert ok is False
    assert "error: {\"code\": 1}" in text


def test_notify_to_tgbot_escapes_html_and_wraps_code(monkeypatch):
    captured = {}

    def fake_webhook(self, dest):
        captured.update(dest)
        return True, "sent"

    monkeypatch.setattr(Channels, "notify_to_webhook", fake_webhook)
    dest = {
        "logmarker": "tg",
        "name_mark": "bot",
        "channel": "tgbot",
        "payload": {"text": "<b>验证码 123456</b>", "parse_mode": "HTML"},
        "code": "123456",
    }

    ok, text = Channels().notify_to_tgbot(dest)

    assert ok is True
    assert text == "sent"
    assert captured["payload"]["text"] == "&lt;b&gt;验证码 <code>123456</code>&lt;/b&gt;"


def test_notify_to_notification_uses_rpc_then_copies_when_success(monkeypatch):
    copied = []
    monkeypatch.setattr(channels, "app_show_notification", lambda title, body: (True, f"{title}:{body}"))
    monkeypatch.setattr(Channels, "save_to_clipboard", lambda self, code: copied.append(code))

    ok, text = Channels().notify_to_notification(
        {
            "logmarker": "local",
            "name_mark": "mac",
            "channel": "notification",
            "payload": {"title": "T", "body": "B", "autoCopy": 1, "copy": "123456"},
        }
    )

    assert ok is True
    assert text == "T:B"
    assert copied == ["123456"]


def test_notify_to_notification_falls_back_to_osascript(monkeypatch):
    monkeypatch.setattr(channels, "app_show_notification", lambda title, body: (False, "rpc down"))
    monkeypatch.setattr(Channels, "_osascript_notification", lambda self, title, body: (True, "fallback ok"))

    ok, text = Channels().notify_to_notification(
        {
            "logmarker": "local",
            "name_mark": "mac",
            "channel": "notification",
            "payload": {"title": "T", "body": "B"},
        }
    )

    assert ok is True
    assert text == "rpc down; fallback: fallback ok"


def test_notify_to_floating_requires_title_body_and_input(monkeypatch):
    calls = []
    monkeypatch.setattr(channels, "app_show_floating", lambda title, body, input_text: calls.append(input_text) or (True, "ok"))

    ok, text = Channels().notify_to_floating(
        {
            "logmarker": "float",
            "name_mark": "panel",
            "channel": "floating",
            "payload": {"title": "T", "body": "B", "input": ""},
        }
    )

    assert ok is False
    assert "title/body/input is empty" in text
    assert calls == []


def test_osascript_notification_builds_command(monkeypatch):
    calls = []

    class FakeCompleted:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return FakeCompleted()

    monkeypatch.setattr(subprocess, "run", fake_run)

    ok, text = Channels()._osascript_notification("Title", "Body", "Sub")

    assert ok is True
    assert text == "osascript notification sent"
    assert calls[0][0][0] == "osascript"
    assert calls[0][0][-3:] == ["Title", "Body", "Sub"]
    assert calls[0][1]["timeout"] == 3
