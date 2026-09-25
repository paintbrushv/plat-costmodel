"""SQLite connection + migration bootstrap."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_DEFAULT_PATH = Path.home() / ".plat-costmodel" / "data.db"


def default_db_path() -> Path:
    """Resolve the configured DB path (env override → default)."""
    env = os.environ.get("PLAT_COSTMODEL_DB_PATH")
    return Path(env) if env else _DEFAULT_PATH


def connect(path: str | None = None) -> sqlite3.Connection:
    """Open a connection, ensuring parent dir + migrations are applied."""
    db_path = Path(path) if path else default_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _bootstrap(conn)
    return conn


def current_migration_version(conn: sqlite3.Connection) -> int:
    cur = conn.execute("SELECT value FROM _meta WHERE key = 'migration_version'")
    row = cur.fetchone()
    return int(row[0]) if row else 0


def _bootstrap(conn: sqlite3.Connection) -> None:
    # Ensure _meta exists before checking version.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS _meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    conn.commit()
    current = current_migration_version(conn)
    files = sorted(_MIGRATIONS_DIR.glob("*.sql"))
    for f in files:
        version = int(f.stem.split("_", 1)[0])
        if version <= current:
            continue
        # Wrap schema + version-stamp in one transaction so a crash between
        # the two leaves the DB in a re-runnable state (avoids "schema applied
        # but version not stamped" → 002 partially re-runs 001's data steps).
        sql = f.read_text()
        version_stmt = (
            f"INSERT OR REPLACE INTO _meta (key, value) "
            f"VALUES ('migration_version', '{int(version)}');"
        )
        conn.executescript(f"BEGIN;\n{sql}\n{version_stmt}\nCOMMIT;")
