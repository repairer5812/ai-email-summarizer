from __future__ import annotations

import sqlite3

from webmail_summary.index.settings import load_settings, set_setting


def _mk_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    return conn


def test_load_settings_defaults_cloud_multimodal_off():
    conn = _mk_conn()
    try:
        s = load_settings(conn)
        assert s.cloud_multimodal_enabled is False
    finally:
        conn.close()


def test_load_settings_reads_cloud_multimodal_enabled():
    conn = _mk_conn()
    try:
        set_setting(conn, "cloud_multimodal_enabled", "1")
        conn.commit()
        s = load_settings(conn)
        assert s.cloud_multimodal_enabled is True
    finally:
        conn.close()
