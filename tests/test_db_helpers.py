from __future__ import annotations

import ast
from pathlib import Path

import pytest

from webmail_summary.index import db as dbmod
from webmail_summary.index.db import DB_FILENAME, app_db_path, init_db, open_db

SRC = Path(__file__).resolve().parents[1] / "src" / "webmail_summary"


def test_app_db_path_defaults_to_app_data_dir(tmp_path):
    # conftest points the app data dir at tmp_path/WebmailSummary
    assert app_db_path() == tmp_path / "WebmailSummary" / "db.sqlite3"
    assert app_db_path(tmp_path / "x") == tmp_path / "x" / "db.sqlite3"


def test_db_file_name_is_only_spelled_in_index_db():
    offenders = []
    for path in SRC.rglob("*.py"):
        if path == SRC / "index" / "db.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and node.value == DB_FILENAME:
                offenders.append(f"{path.relative_to(SRC)}:{node.lineno}")
    assert offenders == []


class _TrackingConn:
    def __init__(self, real):
        self._real = real
        self.closed = False

    def __getattr__(self, name):
        return getattr(self._real, name)

    def close(self):
        self.closed = True
        self._real.close()


def _track(monkeypatch):
    opened: list[_TrackingConn] = []
    real_connect = dbmod._connect

    def _connect(path):
        conn = _TrackingConn(real_connect(path))
        opened.append(conn)
        return conn

    monkeypatch.setattr(dbmod, "_connect", _connect)
    return opened


def test_open_db_closes_on_success_and_on_error(tmp_path, monkeypatch):
    path = tmp_path / "db.sqlite3"
    init_db(path)
    opened = _track(monkeypatch)

    with open_db(path) as conn:
        assert conn.execute("SELECT 1").fetchone()[0] == 1
    assert opened[-1].closed

    with pytest.raises(RuntimeError, match="boom"):
        with open_db(path) as conn:
            raise RuntimeError("boom")
    assert opened[-1].closed
    assert len(opened) == 2


def test_open_db_does_not_commit_for_the_caller(tmp_path):
    path = tmp_path / "db.sqlite3"
    init_db(path)

    with open_db(path) as conn:
        conn.execute("INSERT INTO settings(key, value) VALUES ('a', '1')")
    with open_db(path) as conn:
        conn.execute("INSERT INTO settings(key, value) VALUES ('b', '2')")
        conn.commit()
    with open_db(path) as conn:
        keys = [r[0] for r in conn.execute("SELECT key FROM settings ORDER BY key")]
    assert keys == ["b"]
