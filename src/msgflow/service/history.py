import json
import os
import re
import sqlite3
import threading
import time
from typing import Any, Optional

from ..common.record_query import build_query_sql
from ..common.utils import format_ts


def _sqlite_regexp(pattern: Any, value: Any) -> int:
    if value is None:
        return 0
    try:
        return 1 if re.search(str(pattern), str(value)) else 0
    except re.error:
        return 0


class HistoryStore(object):
    """SQLite-backed storage for message snapshots and processing runs."""

    def __init__(self, db_path: str) -> None:
        self.db_path = os.path.expanduser(db_path)
        parent_dir = os.path.dirname(self.db_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.create_function("REGEXP", 2, _sqlite_regexp, deterministic=True)
        self._conn = conn
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            conn = self._connect()
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS message_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    cursor_value REAL,
                    timestamp REAL,
                    time_str TEXT,
                    sender TEXT,
                    receiver TEXT,
                    text TEXT,
                    title TEXT,
                    subtitle TEXT,
                    body TEXT,
                    msg TEXT NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS run_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER NOT NULL,
                    code TEXT,
                    trigger_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    matched_rule_count INTEGER NOT NULL,
                    sent_dest_count INTEGER NOT NULL,
                    success_dest_count INTEGER NOT NULL,
                    failed_dest_count INTEGER NOT NULL,
                    trace TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(message_id) REFERENCES message_records(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS cursor_state (
                    kind TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    cursor_value REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (kind, destination)
                );

                CREATE INDEX IF NOT EXISTS idx_message_records_created_at
                ON message_records(created_at DESC, id DESC);

                CREATE INDEX IF NOT EXISTS idx_run_records_message_id
                ON run_records(message_id, created_at DESC, id DESC);

                CREATE INDEX IF NOT EXISTS idx_run_records_created_at
                ON run_records(created_at DESC, id DESC);
                """
            )
            conn.commit()

    def _json_dumps(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)

    def _json_loads(self, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        return json.loads(value)

    def get_cursor_map(self, kind: Optional[str] = None) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            if kind is None:
                rows = conn.execute(
                    """
                    SELECT kind, destination, cursor_value
                    FROM cursor_state
                    ORDER BY kind, destination
                    """
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT kind, destination, cursor_value
                    FROM cursor_state
                    WHERE kind = ?
                    ORDER BY destination
                    """,
                    (kind,),
                ).fetchall()
        return [dict(row) for row in rows]

    def set_cursor_map(self, kind: str, cursor_map: dict[str, float]) -> None:
        if not cursor_map:
            return
        now = time.time()
        rows = [
            (kind, destination, float(cursor_value), now)
            for destination, cursor_value in cursor_map.items()
        ]
        with self._lock:
            conn = self._connect()
            conn.executemany(
                """
                INSERT INTO cursor_state (kind, destination, cursor_value, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(kind, destination) DO UPDATE SET
                    cursor_value = excluded.cursor_value,
                    updated_at = excluded.updated_at
                """,
                rows,
            )
            conn.commit()

    def insert_message(self, kind: str, cursor_field: str, message: dict[str, Any]) -> int:
        now = time.time()
        with self._lock:
            conn = self._connect()
            cursor = conn.execute(
                """
                INSERT INTO message_records (
                    kind, cursor_value, timestamp, time_str, sender, receiver, text,
                    title, subtitle, body, msg, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    kind,
                    message.get(cursor_field),
                    message.get("timestamp"),
                    message.get("time_str"),
                    message.get("sender"),
                    message.get("receiver"),
                    message.get("text"),
                    message.get("title"),
                    message.get("subtitle"),
                    message.get("body"),
                    self._json_dumps(message),
                    now,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def insert_run(
        self,
        message_id: int,
        code: Optional[str],
        trigger_type: str,
        status: str,
        matched_rule_count: int,
        sent_dest_count: int,
        success_dest_count: int,
        failed_dest_count: int,
        trace: dict[str, Any],
    ) -> int:
        now = time.time()
        with self._lock:
            conn = self._connect()
            cursor = conn.execute(
                """
                INSERT INTO run_records (
                    message_id, code, trigger_type, status, matched_rule_count, sent_dest_count,
                    success_dest_count, failed_dest_count, trace, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    code,
                    trigger_type,
                    status,
                    matched_rule_count,
                    sent_dest_count,
                    success_dest_count,
                    failed_dest_count,
                    self._json_dumps(trace),
                    now,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def list_runs(
        self,
        limit: int,
        offset: int,
        kind: Optional[str] = None,
        trigger_type: Optional[str] = None,
        status: Optional[str] = None,
        query: Optional[str] = None,
    ) -> dict[str, Any]:
        where_clauses: list[str] = []
        params: list[Any] = []
        if kind:
            where_clauses.append("mr.kind = ?")
            params.append(kind)
        if trigger_type:
            where_clauses.append("rr.trigger_type = ?")
            params.append(trigger_type)
        if status:
            where_clauses.append("rr.status = ?")
            params.append(status)
        query_where, query_params = build_query_sql(query)
        if query_where:
            where_clauses.append(query_where)
            params.extend(query_params)
        filter_sql = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        with self._lock:
            conn = self._connect()
            total_row = conn.execute(
                f"""
                SELECT COUNT(*) AS cnt
                FROM run_records AS rr
                JOIN message_records AS mr ON mr.id = rr.message_id
                {filter_sql}
                """,
                tuple(params),
            ).fetchone()
            rows = conn.execute(
                f"""
                SELECT
                    rr.id AS run_id,
                    rr.message_id,
                    rr.code,
                    rr.created_at,
                    rr.trigger_type,
                    rr.status,
                    rr.matched_rule_count,
                    rr.success_dest_count,
                    rr.failed_dest_count,
                    mr.kind,
                    mr.sender,
                    mr.receiver,
                    mr.text,
                    mr.title,
                    mr.time_str,
                    mr.cursor_value,
                    rr.trace
                FROM run_records AS rr
                JOIN message_records AS mr ON mr.id = rr.message_id
                {filter_sql}
                ORDER BY rr.created_at DESC, rr.id DESC
                LIMIT ? OFFSET ?
                """,
                tuple(params + [limit, offset]),
            ).fetchall()
        total = int(total_row["cnt"]) if total_row else 0
        items = []
        for row in rows:
            text_preview = row["text"] or row["title"] or ""
            items.append(
                {
                    "run_id": row["run_id"],
                    "message_id": row["message_id"],
                    "created_at": row["created_at"],
                    "created_at_str": format_ts(int(row["created_at"])),
                    "trigger_type": row["trigger_type"],
                    "status": row["status"],
                    "kind": row["kind"],
                    "cursor_value": row["cursor_value"],
                    "sender": row["sender"],
                    "receiver": row["receiver"],
                    "text_preview": text_preview[:120],
                    "time_str": row["time_str"] or "",
                    "code": row["code"],
                    "matched_rule_count": row["matched_rule_count"],
                    "success_dest_count": row["success_dest_count"],
                    "failed_dest_count": row["failed_dest_count"],
                }
            )
        return {
            "total": total,
            "items": items,
        }

    def get_message(self, message_id: int) -> Optional[dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            row = conn.execute(
                "SELECT * FROM message_records WHERE id = ?",
                (message_id,),
            ).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["msg"] = self._json_loads(data["msg"])
        return data

    def get_run(self, run_id: int) -> Optional[dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            row = conn.execute(
                "SELECT * FROM run_records WHERE id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["trace"] = self._json_loads(data["trace"])
        return data

    def get_message_detail(self, message_id: int) -> Optional[dict[str, Any]]:
        message = self.get_message(message_id)
        if message is None:
            return None
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                """
                SELECT * FROM run_records
                WHERE message_id = ?
                ORDER BY created_at DESC, id DESC
                """,
                (message_id,),
            ).fetchall()
        runs = []
        for row in rows:
            run = dict(row)
            run["trace"] = self._json_loads(run["trace"])
            runs.append(run)
        return {
            "message": message,
            "runs": runs,
        }

    def delete_run(self, run_id: int) -> bool:
        with self._lock:
            conn = self._connect()
            cursor = conn.execute(
                "DELETE FROM run_records WHERE id = ?",
                (run_id,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def cleanup_by_count(self, kind: str, keep_count: int, low_water_count: Optional[int] = None) -> int:
        # Count-based retention for one kind only.
        # If the current row count is above `keep_count`, delete the oldest rows
        # of that kind and keep only the newest `low_water_count` rows
        # (or `keep_count` when low_water_count is omitted).
        if keep_count <= 0:
            return 0
        target_count = keep_count if low_water_count is None else max(1, low_water_count)
        with self._lock:
            conn = self._connect()
            total_row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM message_records WHERE kind = ?",
                (kind,),
            ).fetchone()
            total = int(total_row["cnt"]) if total_row else 0
        if total <= keep_count:
            return 0
        with self._lock:
            ids = conn.execute(
                """
                SELECT id
                FROM message_records
                WHERE kind = ?
                ORDER BY created_at DESC, id DESC
                LIMIT -1 OFFSET ?
                """,
                (kind, target_count),
            ).fetchall()
        delete_ids = [int(row["id"]) for row in ids]
        if not delete_ids:
            return 0
        with self._lock:
            conn.executemany(
                "DELETE FROM message_records WHERE id = ?",
                [(message_id,) for message_id in delete_ids],
            )
            conn.commit()
        return len(delete_ids)

    def cleanup_by_days(self, kind: str, keep_days: int) -> int:
        # Age-based retention for one kind only.
        # Delete rows of the given kind whose `created_at` is older than the
        # rolling cutoff: now - keep_days.
        if keep_days <= 0:
            return 0
        cutoff = time.time() - keep_days * 24 * 60 * 60
        with self._lock:
            conn = self._connect()
            cursor = conn.execute(
                "DELETE FROM message_records WHERE kind = ? AND created_at < ?",
                (kind, cutoff),
            )
            conn.commit()
            return cursor.rowcount

    def close(self) -> None:
        with self._lock:
            if self._conn is None:
                return
            try:
                self._conn.close()
            finally:
                self._conn = None

    def __del__(self) -> None:
        try:
            self.close()
        finally:
            pass
