import json
import sqlite3
import time

import pytest

from msgflow.service.history import HistoryStore, _sqlite_regexp


def _insert_sample_run(store: HistoryStore, *, kind="sms", text="验证码 123456", status="success") -> tuple[int, int]:
    message_id = store.insert_message(
        kind,
        "rowid",
        {
            "rowid": 10,
            "timestamp": 1000,
            "time_str": "2026-01-01 00:00:00",
            "sender": "alice",
            "receiver": "bob",
            "text": text,
            "code": "123456",
        },
    )
    run_id = store.insert_run(
        message_id,
        "123456",
        "auto",
        status,
        matched_rule_count=1,
        sent_dest_count=1,
        success_dest_count=1 if status == "success" else 0,
        failed_dest_count=0 if status == "success" else 1,
        trace={"rules": [{"name_mark": "code"}]},
    )
    return message_id, run_id


def test_sqlite_regexp_matches_invalid_patterns_safely():
    assert _sqlite_regexp(r"\d+", "abc123") == 1
    assert _sqlite_regexp(r"\d+", None) == 0
    assert _sqlite_regexp("[", "abc") == 0


def test_history_store_inserts_and_loads_message_and_run(tmp_path):
    store = HistoryStore(str(tmp_path / "history.db"))
    message_id, run_id = _insert_sample_run(store)

    message = store.get_message(message_id)
    run = store.get_run(run_id)

    assert message is not None
    assert message["msg"]["text"] == "验证码 123456"
    assert run is not None
    assert run["trace"] == {"rules": [{"name_mark": "code"}]}


def test_history_json_is_compact_for_regex_matching(tmp_path):
    db_path = tmp_path / "history.db"
    store = HistoryStore(str(db_path))
    message_id = store.insert_message("sms", "rowid", {"rowid": 1, "text": "hello", "nested": {"a": 1}})

    conn = sqlite3.connect(db_path)
    raw = conn.execute("SELECT msg FROM message_records WHERE id = ?", (message_id,)).fetchone()[0]
    conn.close()

    assert raw == '{"rowid":1,"text":"hello","nested":{"a":1}}'


def test_cursor_map_upserts_and_filters_by_kind(tmp_path):
    store = HistoryStore(str(tmp_path / "history.db"))

    store.set_cursor_map("sms", {"dest1": 1, "dest2": 2})
    store.set_cursor_map("sms", {"dest1": 5})
    store.set_cursor_map("notify", {"dest3": 9})

    assert store.get_cursor_map("sms") == [
        {"kind": "sms", "destination": "dest1", "cursor_value": 5.0},
        {"kind": "sms", "destination": "dest2", "cursor_value": 2.0},
    ]
    assert [item["destination"] for item in store.get_cursor_map()] == ["dest3", "dest1", "dest2"]


def test_list_runs_applies_structured_filters_and_query(tmp_path, monkeypatch):
    store = HistoryStore(str(tmp_path / "history.db"))
    monkeypatch.setattr("msgflow.service.history.format_ts", lambda ts: f"ts:{ts}")
    _insert_sample_run(store, kind="sms", text="验证码 123456", status="success")
    _insert_sample_run(store, kind="notify", text="普通通知", status="failed")

    result = store.list_runs(limit=20, offset=0, kind="sms", status="success", query="text:~验证码")

    assert result["total"] == 1
    assert result["items"][0]["kind"] == "sms"
    assert result["items"][0]["text_preview"] == "验证码 123456"
    assert result["items"][0]["created_at_str"].startswith("ts:")


def test_get_message_detail_returns_message_with_runs(tmp_path):
    store = HistoryStore(str(tmp_path / "history.db"))
    message_id, run_id = _insert_sample_run(store)

    detail = store.get_message_detail(message_id)

    assert detail is not None
    assert detail["message"]["id"] == message_id
    assert detail["runs"][0]["id"] == run_id
    assert detail["runs"][0]["trace"] == {"rules": [{"name_mark": "code"}]}


def test_delete_run_returns_whether_row_existed(tmp_path):
    store = HistoryStore(str(tmp_path / "history.db"))
    _message_id, run_id = _insert_sample_run(store)

    assert store.delete_run(run_id) is True
    assert store.delete_run(run_id) is False


def test_cleanup_by_count_keeps_newest_rows_per_kind(tmp_path):
    store = HistoryStore(str(tmp_path / "history.db"))
    for idx in range(5):
        store.insert_message("sms", "rowid", {"rowid": idx, "text": f"msg {idx}"})
        time.sleep(0.001)
    store.insert_message("notify", "rec_id", {"rec_id": 1, "text": "keep-other-kind"})

    deleted = store.cleanup_by_count("sms", keep_count=3, low_water_count=2)

    remaining_sms = store._connect().execute("SELECT msg FROM message_records WHERE kind = 'sms' ORDER BY id").fetchall()
    assert deleted == 3
    assert [json.loads(row["msg"])["rowid"] for row in remaining_sms] == [3, 4]
    assert store._connect().execute("SELECT COUNT(*) FROM message_records WHERE kind = 'notify'").fetchone()[0] == 1


def test_cleanup_by_days_deletes_only_old_rows_for_kind(tmp_path, monkeypatch):
    store = HistoryStore(str(tmp_path / "history.db"))
    now = 2_000_000.0
    monkeypatch.setattr(time, "time", lambda: now - 10 * 24 * 60 * 60)
    store.insert_message("sms", "rowid", {"rowid": 1, "text": "old"})
    monkeypatch.setattr(time, "time", lambda: now)
    store.insert_message("sms", "rowid", {"rowid": 2, "text": "new"})
    store.insert_message("notify", "rec_id", {"rec_id": 1, "text": "old-other-kind"})

    deleted = store.cleanup_by_days("sms", keep_days=3)

    rows = store._connect().execute("SELECT kind, msg FROM message_records ORDER BY id").fetchall()
    assert deleted == 1
    assert [(row["kind"], json.loads(row["msg"]).get("text")) for row in rows] == [
        ("sms", "new"),
        ("notify", "old-other-kind"),
    ]
