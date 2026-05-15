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
        self._conn: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        # Reuse one read-only connection per LiteDB instance. Flow creation and
        # polling are constrained to the core main loop thread, so this cached
        # handle is not shared across threads.
        if self._conn is not None:
            return self._conn
        uri = f"file:{self.db_file}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        self._conn = conn
        return conn

    @classmethod
    def probe_read_access(cls, db_file: str) -> None:
        db = cls(db_file)
        try:
            db.select("SELECT 1")
        finally:
            db.close()

    def _disconnect(self) -> None:
        if self._conn is None:
            return
        try:
            self._conn.close()
        finally:
            self._conn = None

    def select(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        try:
            conn = self._connect()
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.Error:
            # Retry once with a brand-new handle so transient read errors (for
            # example while the system rotates the DB/WAL state) do not fail
            # the whole polling tick.
            self._disconnect()
            conn = self._connect()
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        self._disconnect()

    def __del__(self) -> None:
        try:
            self.close()
        finally:
            pass
