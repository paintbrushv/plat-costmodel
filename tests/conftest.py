"""Shared pytest fixtures."""
import pytest

from plat_costmodel.store.db import connect


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Per-test SQLite DB; sets PLAT_COSTMODEL_DB_PATH so any code path
    that calls default_db_path() picks it up too."""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("PLAT_COSTMODEL_DB_PATH", str(db_path))
    conn = connect(str(db_path))
    yield conn
    conn.close()
