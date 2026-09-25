"""Migration 003 — backfills estimate_json from legacy interior columns."""
import json
import sqlite3
from pathlib import Path

import pytest

from plat_costmodel.store.db import _MIGRATIONS_DIR


def _connect_at_v002(tmp_path) -> sqlite3.Connection:
    """Create a DB with only 001 + 002 applied (slice-A schema)."""
    db_path = tmp_path / "v002.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    for name in ("001_initial.sql", "002_floor_plan_id_on_estimates.sql"):
        conn.executescript((_MIGRATIONS_DIR / name).read_text())
    conn.commit()
    return conn


def test_migration_003_backfills_estimate_json_from_legacy_columns(tmp_path):
    conn = _connect_at_v002(tmp_path)
    # Seed: minimal property/snapshot/scope_request foreign keys, then one
    # interior estimate row using the legacy column shape.
    conn.executescript("""
        INSERT INTO properties (property_id, total_units, address, year_built, created_at)
        VALUES ('prop1', 12, '1 Main', 1985, '2026-04-01T00:00:00+00:00');
        INSERT INTO pricing_snapshots (snapshot_id, captured_at, kb_version_hash)
        VALUES ('snap1', '2026-04-01T00:00:00+00:00', 'h1');
        INSERT INTO scope_requests (
            scope_request_id, property_id, program_type, cohort_json,
            schedule_json, requested_at, requested_by
        ) VALUES (
            'req1', 'prop1', 'interior_renovation',
            '{"floor_plan_id":"fp1","unit_count":10,"scope_level":"standard_value_add","finish_tier":"basic","current_monthly_rent":800,"target_monthly_rent":1000}',
            '{"start_month":"2026-06","monthly_pace":5,"downtime_days":21}',
            '2026-04-01T00:00:00+00:00', 'test'
        );
        INSERT INTO scope_estimates (
            estimate_id, scope_request_id, property_id, floor_plan_id,
            pricing_snapshot_id, unit_estimates_json,
            cohort_total_low, cohort_total_high,
            per_unit_average_low, per_unit_average_high,
            roi_result_json, risk_flags_json, sanity_flags_json, estimated_at
        ) VALUES (
            'est1', 'req1', 'prop1', 'fp1', 'snap1',
            '[]', 8800, 13200, 880, 1320,
            '{"total_cost_high":13200,"current_monthly_rent":800,"target_monthly_rent":1000,"monthly_rent_lift":200,"annual_rent_lift":2400,"roi_pct":18.18,"clears_threshold":true,"path_to_pass":[]}',
            '[]', '[]', '2026-04-01T00:00:00+00:00'
        );
    """)
    conn.commit()

    migration_003 = (_MIGRATIONS_DIR / "003_scope_b_estimate_polymorphism.sql").read_text()
    conn.executescript(migration_003)
    conn.commit()

    row = conn.execute("SELECT * FROM scope_estimates WHERE estimate_id='est1'").fetchone()
    assert row["scope_type"] == "unit"
    assert row["floor_plan_id"] == "fp1"
    payload = json.loads(row["estimate_json"])
    assert payload["scope_type"] == "unit"
    assert payload["estimate_id"] == "est1"
    assert payload["cohort_total_high"] == 13200
    assert payload["roi_result"]["roi_pct"] == 18.18


def test_migration_003_makes_floor_plan_id_nullable(tmp_path):
    conn = _connect_at_v002(tmp_path)
    migration_003 = (_MIGRATIONS_DIR / "003_scope_b_estimate_polymorphism.sql").read_text()
    conn.executescript(migration_003)
    conn.commit()
    # Should be able to insert a row with NULL floor_plan_id.
    conn.execute("""
        INSERT INTO properties (property_id, total_units, address, year_built, created_at)
        VALUES ('prop2', 12, '2 Main', 1985, '2026-04-01T00:00:00+00:00')
    """)
    conn.execute("""
        INSERT INTO pricing_snapshots (snapshot_id, captured_at, kb_version_hash)
        VALUES ('snap2', '2026-04-01T00:00:00+00:00', 'h2')
    """)
    conn.execute("""
        INSERT INTO scope_requests (
            scope_request_id, property_id, program_type, cohort_json,
            schedule_json, requested_at, requested_by
        ) VALUES ('req2', 'prop2', 'exterior_renovation', '{}', '{}',
                  '2026-04-01T00:00:00+00:00', 'test')
    """)
    conn.execute("""
        INSERT INTO scope_estimates (
            estimate_id, scope_request_id, property_id, floor_plan_id,
            pricing_snapshot_id, scope_type, estimate_json, estimated_at
        ) VALUES ('est2', 'req2', 'prop2', NULL, 'snap2', 'exterior',
                  '{"scope_type":"exterior"}', '2026-04-01T00:00:00+00:00')
    """)
    conn.commit()
    row = conn.execute("SELECT floor_plan_id FROM scope_estimates WHERE estimate_id='est2'").fetchone()
    assert row["floor_plan_id"] is None
