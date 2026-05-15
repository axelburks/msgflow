from pathlib import Path
from types import SimpleNamespace

import pytest

from msgflow.service import runtime
from msgflow.service.runtime import CoreRuntime, _notify_enabled, _sms_enabled, _source_display_name


class FakeHistory:
    def __init__(self):
        self.cursor_rows = []
        self.set_calls = []
        self.deleted_runs = []
        self.cleanup_by_count_calls = []
        self.cleanup_by_days_calls = []

    def get_cursor_map(self, kind=None):
        self.cursor_rows.append(kind)
        return [{"kind": kind or "sms", "destination": "dest1", "cursor_value": 5.0}]

    def set_cursor_map(self, kind, cursor_map):
        self.set_calls.append((kind, cursor_map))

    def delete_run(self, run_id):
        self.deleted_runs.append(run_id)
        return True

    def cleanup_by_count(self, kind, keep_count, low_water_count=None):
        self.cleanup_by_count_calls.append((kind, keep_count, low_water_count))
        return 2

    def cleanup_by_days(self, kind, keep_days):
        self.cleanup_by_days_calls.append((kind, keep_days))
        return 3


def _runtime_with_config(built_cfg):
    obj = object.__new__(CoreRuntime)
    obj.cfg = SimpleNamespace(built_cfg=built_cfg)
    obj.history = FakeHistory()
    obj.flows = []
    obj.status = "running"
    obj.error = None
    obj.retention = dict(built_cfg.get("app", {}).get("retention") or {})
    obj.insert_since_last_cleanup = 0
    obj.last_cleanup_at = 0.0
    obj._loop_thread_id = None
    return obj


def test_enabled_flags_reflect_configured_rules(monkeypatch):
    monkeypatch.setattr(
        runtime.config,
        "cfg",
        SimpleNamespace(built_cfg={"sms": {"rules": [1]}, "notify": {"rules": []}}),
    )

    assert _sms_enabled() is True
    assert _notify_enabled() is False


def test_source_display_name_has_known_labels_and_fallback():
    assert _source_display_name("sms") == "SMS"
    assert _source_display_name("notify") == "Notify"
    assert _source_display_name("other") == "other"


def test_validate_kind_normalizes_and_rejects_unknown_kind():
    obj = _runtime_with_config({})

    assert obj._validate_kind(" SMS ") == "sms"
    with pytest.raises(ValueError, match="kind must be one of"):
        obj._validate_kind("email")


def test_configured_destinations_for_kind_deduplicates_and_ignores_invalid_names():
    obj = _runtime_with_config(
        {
            "sms": {
                "rules": [
                    {"destinations": [{"name_mark": "dest1"}, {"name_mark": ""}, {"name_mark": "dest1"}]},
                    {"destinations": [{"name_mark": "dest2"}]},
                ]
            }
        }
    )

    assert obj._configured_destinations_for_kind("sms") == ["dest1", "dest2"]


def test_get_cursor_state_delegates_to_history_with_optional_kind():
    obj = _runtime_with_config({})

    assert obj.get_cursor_state(None) == {"items": [{"kind": "sms", "destination": "dest1", "cursor_value": 5.0}]}
    assert obj.get_cursor_state("sms") == {"items": [{"kind": "sms", "destination": "dest1", "cursor_value": 5.0}]}
    assert obj.history.cursor_rows == [None, "sms"]


def test_update_cursor_state_validates_destination_and_updates_live_flow():
    obj = _runtime_with_config({"sms": {"rules": [{"destinations": [{"name_mark": "dest1"}]}]}})
    obj.flows = [SimpleNamespace(KIND="sms", cursor={"dest1": 0.0}, min_cursor=0.0)]

    result = obj.update_cursor_state("sms", {"dest1": 12})

    assert result["items"][0]["destination"] == "dest1"
    assert obj.history.set_calls == [("sms", {"dest1": 12.0})]
    assert obj.flows[0].cursor["dest1"] == 12.0
    assert obj.flows[0].min_cursor == 12.0


@pytest.mark.parametrize(
    "cursor_map, message",
    [
        pytest.param({}, "non-empty object", id="空 map"),
        pytest.param({"unknown": 1}, "unknown destination", id="未知目标"),
        pytest.param({"dest1": True}, "must be numeric", id="bool 不是游标"),
        pytest.param({"": 1}, "destination name cannot be empty", id="空目标名"),
    ],
)
def test_update_cursor_state_rejects_invalid_payloads(cursor_map, message):
    obj = _runtime_with_config({"sms": {"rules": [{"destinations": [{"name_mark": "dest1"}]}]}})

    with pytest.raises(ValueError, match=message):
        obj.update_cursor_state("sms", cursor_map)


def test_permission_issue_mentions_authorization_target(monkeypatch):
    obj = _runtime_with_config({})
    monkeypatch.setattr(
        runtime,
        "resolve_full_disk_access_target",
        lambda: {"kind": "msgflow_app", "name": "msgflow.app"},
    )

    issue = obj._permission_issue("sms", Path("/private/chat.db"), PermissionError("denied"))

    assert issue["kind"] == "sms"
    assert issue["requires_authorization"] is True
    assert "Grant Full Disk Access to msgflow.app" in issue["message"]


def test_collect_runtime_issues_probes_enabled_sources(monkeypatch):
    obj = _runtime_with_config({})
    monkeypatch.setattr(obj, "_enabled_source_checks", lambda: [("sms", Path("/tmp/chat.db"))])
    monkeypatch.setattr(runtime.LiteDB, "probe_read_access", lambda path: (_ for _ in ()).throw(PermissionError(path)))
    monkeypatch.setattr(
        obj,
        "_permission_issue",
        lambda kind, db_path, error: {"kind": kind, "path": str(db_path), "detail": str(error)},
    )

    assert obj._collect_runtime_issues() == [{"kind": "sms", "path": "/tmp/chat.db", "detail": "/tmp/chat.db"}]


def test_apply_pending_command_invokes_start_or_pause(monkeypatch):
    obj = _runtime_with_config({})
    commands = []
    monkeypatch.setattr(obj, "pop_pending_command", lambda: "pause")
    monkeypatch.setattr(obj, "pause_listener", lambda: commands.append("pause"))

    assert obj.apply_pending_command() == "pause"
    assert commands == ["pause"]


def test_maybe_cleanup_history_applies_count_and_days_retention(monkeypatch):
    obj = _runtime_with_config(
        {
            "app": {
                "retention": {
                    "sms": {"mode": "count", "value": 1000},
                    "notify": {"mode": "days", "value": 7},
                }
            }
        }
    )
    obj.insert_since_last_cleanup = obj.CLEANUP_COUNT_INTERVAL
    monkeypatch.setattr(runtime.time, "time", lambda: obj.CLEANUP_DAYS_INTERVAL_SECONDS + 10)

    deleted = obj.maybe_cleanup_history()

    assert deleted == 5
    assert obj.history.cleanup_by_count_calls == [("sms", 1000, 500)]
    assert obj.history.cleanup_by_days_calls == [("notify", 7)]
    assert obj.insert_since_last_cleanup == 0
