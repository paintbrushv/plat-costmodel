"""Tests for SQLite connection + migrations bootstrap."""
import sqlite3

from plat_costmodel.store.db import connect, current_migration_version


def test_connect_creates_db_file(tmp_path):
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))
    assert db_path.exists()
    conn.close()


def test_migrations_run_on_first_connect(tmp_path):
    conn = connect(str(tmp_path / "test.db"))
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    names = {r[0] for r in cur.fetchall()}
    expected = {
        "_meta", "properties", "floor_plans", "pricing_snapshots",
        "scope_requests", "scope_estimates", "actual_outcomes",
    }
    assert expected.issubset(names)
    conn.close()


def test_current_migration_version_after_bootstrap(tmp_path):
    conn = connect(str(tmp_path / "test.db"))
    assert current_migration_version(conn) == 3  # updated: migration 003 landed
    conn.close()


def test_reconnect_does_not_re_run_migrations(tmp_path):
    db = str(tmp_path / "test.db")
    c1 = connect(db)
    c1.execute("INSERT INTO properties (property_id, total_units, created_at) VALUES ('p1', 5, '2026-04-26T00:00:00Z')")
    c1.commit()
    c1.close()
    c2 = connect(db)
    # Migrations must NOT re-run: version stays at 3, data persists.
    assert current_migration_version(c2) == 3  # updated: migration 003 landed
    cur = c2.execute("SELECT property_id FROM properties")
    assert cur.fetchone()[0] == "p1"
    c2.close()


def test_foreign_keys_enabled(tmp_path):
    conn = connect(str(tmp_path / "test.db"))
    val = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert val == 1
    conn.close()
