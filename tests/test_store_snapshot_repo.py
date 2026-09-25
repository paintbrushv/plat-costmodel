"""Tests for SnapshotRepo (PricingSnapshot dedup by KB hash)."""
from datetime import datetime, timezone

from plat_costmodel.schemas import PricingSnapshot
from plat_costmodel.store.repo import SnapshotRepo


def test_get_or_create_mints_on_first_call(tmp_db):
    repo = SnapshotRepo(tmp_db)
    s = repo.get_or_create_for_kb_hash("abc123")
    assert len(s.snapshot_id) == 26
    assert s.kb_version_hash == "abc123"
    assert s.external_feeds == {}


def test_get_or_create_dedup_on_same_hash(tmp_db):
    repo = SnapshotRepo(tmp_db)
    s1 = repo.get_or_create_for_kb_hash("abc123")
    s2 = repo.get_or_create_for_kb_hash("abc123")
    assert s1.snapshot_id == s2.snapshot_id


def test_different_hash_creates_different_snapshot(tmp_db):
    repo = SnapshotRepo(tmp_db)
    s1 = repo.get_or_create_for_kb_hash("abc")
    s2 = repo.get_or_create_for_kb_hash("def")
    assert s1.snapshot_id != s2.snapshot_id


def test_get_by_id(tmp_db):
    repo = SnapshotRepo(tmp_db)
    s = repo.get_or_create_for_kb_hash("abc")
    fetched = repo.get(s.snapshot_id)
    assert fetched == s


def test_different_hash_creates_two_distinct_snapshots(tmp_db):
    """Negative dedup boundary: two different hashes must produce two distinct
    rows (existing tests cover same-hash dedup but not the negative case)."""
    repo = SnapshotRepo(tmp_db)
    s1 = repo.get_or_create_for_kb_hash("hash-a")
    s2 = repo.get_or_create_for_kb_hash("hash-b")
    assert s1.snapshot_id != s2.snapshot_id
    rows = tmp_db.execute("SELECT COUNT(*) FROM pricing_snapshots").fetchone()[0]
    assert rows == 2
