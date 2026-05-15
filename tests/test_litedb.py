import sqlite3

import pytest

from msgflow.service import litedb
from msgflow.service.litedb import LiteDB


def test_litedb_rejects_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(LiteDB, "__del__", lambda self: None)

    with pytest.raises(FileNotFoundError, match="db not found"):
        LiteDB(str(tmp_path / "missing.db"))


def test_select_reads_rows_as_dicts_from_read_only_connection(tmp_path):
    db_path = tmp_path / "sample.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO items (name) VALUES ('alpha')")
    conn.commit()
    conn.close()

    db = LiteDB(str(db_path))

    assert db.select("SELECT id, name FROM items") == [{"id": 1, "name": "alpha"}]
    with pytest.raises(sqlite3.OperationalError):
        db.select("INSERT INTO items (name) VALUES (?)", ("beta",))


def test_select_retries_once_after_sqlite_error(monkeypatch, tmp_path):
    db_path = tmp_path / "sample.db"
    sqlite3.connect(db_path).close()
    db = LiteDB(str(db_path))
    calls = []

    class FakeRow(dict):
        pass

    class FakeCursor:
        def fetchall(self):
            return [FakeRow(id=1, name="ok")]

    class FakeConn:
        row_factory = None

        def __init__(self, fail=False):
            self.fail = fail
            self.closed = False

        def execute(self, *args, **kwargs):
            if self.fail:
                raise sqlite3.OperationalError("transient")
            return FakeCursor()

        def close(self):
            self.closed = True

    def fake_connect(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeConn(fail=len(calls) == 1)

    monkeypatch.setattr(litedb.sqlite3, "connect", fake_connect)

    assert db.select("SELECT id, name FROM items") == [{"id": 1, "name": "ok"}]
    assert len(calls) == 2


def test_probe_read_access_closes_database(monkeypatch, tmp_path):
    db_path = tmp_path / "sample.db"
    sqlite3.connect(db_path).close()
    closed = []

    monkeypatch.setattr(LiteDB, "select", lambda self, sql: None)
    monkeypatch.setattr(LiteDB, "close", lambda self: closed.append(self.db_file))

    LiteDB.probe_read_access(str(db_path))

    assert closed
    assert all(path == str(db_path) for path in closed)
