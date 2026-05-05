import os, sqlite3
from typing import Any


class LiteDB(object):
    """
    Read-only SQLite accessor.

    System databases (iMessage chat.db / usernoted db) are opened with the
    `mode=ro` URI flag so we never acquire a write lock and can safely read
    concurrently with the system process that owns WAL writes.

    Important: do NOT use `immutable=1`. It makes SQLite ignore the `-wal`
    file and we would miss any row that hasn't been checkpointed yet.

    The db file is checked at construction time: callers instantiate LiteDB
    only when they actually need that data source, so a missing file is
    considered a configuration/environment error and surfaced early.
    """

    def __init__(self, db_file: str) -> None:
        if not os.path.exists(db_file):
            raise FileNotFoundError(f"db not found: {db_file}")
        self.db_file = db_file

    def _connect(self) -> sqlite3.Connection:
        # Open a fresh read-only connection per call. Row factory is set to
        # sqlite3.Row so rows can be converted to plain dicts cheaply.
        uri = f"file:{self.db_file}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def select(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        # Execute a parameterized SELECT and return rows as a list of dicts.
        # Connection is opened/closed per call on purpose: short-lived
        # connections avoid holding resources and play nicely with the
        # system process doing concurrent WAL writes.
        conn = self._connect()
        try:
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
        return [dict(row) for row in rows]
