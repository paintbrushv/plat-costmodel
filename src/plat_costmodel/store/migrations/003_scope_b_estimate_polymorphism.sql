-- 003: support polymorphic ScopeEstimate variants for slice B.
--
-- Drops the slice-A interior-specific columns (unit_estimates_json,
-- cohort_total_low/high, per_unit_average_low/high, roi_result_json,
-- risk_flags_json, sanity_flags_json) and replaces them with a single
-- estimate_json blob keyed by a new scope_type column. floor_plan_id
-- becomes nullable (exterior/amenity/deferred have no floor plan).
--
-- Existing rows are all interior (slice A only ever wrote unit cohorts);
-- the backfill reconstructs the InteriorScopeEstimate JSON from the
-- legacy columns before they are dropped.
--
-- NOTE on FK safety during table swap:
-- This migration recreates scope_estimates. SQLite cannot toggle
-- PRAGMA foreign_keys inside a transaction, and store/db.py::_bootstrap
-- wraps every migration in BEGIN/COMMIT. The swap is safe here only
-- because scope_estimates is a leaf table — no other table FK-references
-- it, so dropping it does not orphan any rows.
--
-- Any future migration that swaps a table with inbound FKs will need a
-- different approach: either skip the transaction wrapper, or apply
-- PRAGMA foreign_keys = OFF on the connection before invoking the loader.

CREATE TABLE scope_estimates_new (
    estimate_id TEXT PRIMARY KEY,
    scope_request_id TEXT NOT NULL,
    property_id TEXT NOT NULL,
    floor_plan_id TEXT NULL,
    pricing_snapshot_id TEXT NOT NULL,
    scope_type TEXT NOT NULL,
    estimate_json TEXT NOT NULL,
    estimated_at TEXT NOT NULL,
    FOREIGN KEY (scope_request_id) REFERENCES scope_requests(scope_request_id),
    FOREIGN KEY (property_id) REFERENCES properties(property_id),
    FOREIGN KEY (pricing_snapshot_id) REFERENCES pricing_snapshots(snapshot_id)
);

-- Backfill: every existing row is an interior estimate. Build the
-- ScopeEstimate JSON from legacy columns + the row's metadata. The
-- shape must match InteriorScopeEstimate (scope_type='unit', plus
-- estimate_id, scope_request_id, property_id, floor_plan_id,
-- pricing_snapshot_id, unit_estimates, cohort_total_low/high,
-- per_unit_average_low/high, roi_result, risk_flags, sanity_flags,
-- estimated_at).
INSERT INTO scope_estimates_new (
    estimate_id, scope_request_id, property_id, floor_plan_id,
    pricing_snapshot_id, scope_type, estimate_json, estimated_at
)
SELECT
    estimate_id,
    scope_request_id,
    property_id,
    floor_plan_id,
    pricing_snapshot_id,
    'unit' AS scope_type,
    json_object(
        'scope_type', 'unit',
        'estimate_id', estimate_id,
        'scope_request_id', scope_request_id,
        'property_id', property_id,
        'floor_plan_id', floor_plan_id,
        'pricing_snapshot_id', pricing_snapshot_id,
        'unit_estimates', json(unit_estimates_json),
        'cohort_total_low', cohort_total_low,
        'cohort_total_high', cohort_total_high,
        'per_unit_average_low', per_unit_average_low,
        'per_unit_average_high', per_unit_average_high,
        'roi_result', json(roi_result_json),
        'risk_flags', json(risk_flags_json),
        'sanity_flags', json(sanity_flags_json),
        'estimated_at', estimated_at
    ) AS estimate_json,
    estimated_at
FROM scope_estimates;

DROP TABLE scope_estimates;
ALTER TABLE scope_estimates_new RENAME TO scope_estimates;

CREATE INDEX IF NOT EXISTS idx_scope_estimates_property ON scope_estimates(property_id);
CREATE INDEX IF NOT EXISTS idx_scope_estimates_request ON scope_estimates(scope_request_id);
CREATE INDEX IF NOT EXISTS idx_scope_estimates_floor_plan ON scope_estimates(floor_plan_id);
CREATE INDEX IF NOT EXISTS idx_scope_estimates_scope_type ON scope_estimates(scope_type);
