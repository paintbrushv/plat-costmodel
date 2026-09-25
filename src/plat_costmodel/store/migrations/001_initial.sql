-- 001_initial: canonical schema tables.
-- All JSON columns are TEXT in SQLite; serialized via json.dumps in Python.
-- ULIDs are 26-char Crockford base32 stored as TEXT.

CREATE TABLE IF NOT EXISTS _meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS properties (
    property_id     TEXT PRIMARY KEY,
    external_alias  TEXT,
    address         TEXT NOT NULL DEFAULT '',
    market          TEXT,
    year_built      INTEGER,
    property_class  TEXT,
    building_type   TEXT NOT NULL DEFAULT '',
    total_units     INTEGER NOT NULL,
    amenities_json  TEXT NOT NULL DEFAULT '{"existing":[],"planned":[]}',
    created_at      TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_properties_alias
    ON properties(external_alias) WHERE external_alias IS NOT NULL;

CREATE TABLE IF NOT EXISTS floor_plans (
    floor_plan_id   TEXT PRIMARY KEY,
    property_id     TEXT NOT NULL REFERENCES properties(property_id),
    name            TEXT NOT NULL,
    sqft            REAL NOT NULL,
    bedrooms        INTEGER NOT NULL,
    bathrooms       INTEGER NOT NULL,
    notes           TEXT NOT NULL DEFAULT '',
    external_alias  TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_floor_plans_alias
    ON floor_plans(property_id, external_alias) WHERE external_alias IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_floor_plans_property
    ON floor_plans(property_id);

CREATE TABLE IF NOT EXISTS pricing_snapshots (
    snapshot_id         TEXT PRIMARY KEY,
    captured_at         TEXT NOT NULL,
    kb_version_hash     TEXT NOT NULL,
    external_feeds_json TEXT NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_pricing_snapshots_hash
    ON pricing_snapshots(kb_version_hash);

CREATE TABLE IF NOT EXISTS scope_requests (
    scope_request_id TEXT PRIMARY KEY,
    property_id      TEXT NOT NULL REFERENCES properties(property_id),
    program_type     TEXT NOT NULL,
    cohort_json      TEXT NOT NULL,
    schedule_json    TEXT NOT NULL,
    requested_at     TEXT NOT NULL,
    requested_by     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_scope_requests_property
    ON scope_requests(property_id);

CREATE TABLE IF NOT EXISTS scope_estimates (
    estimate_id          TEXT PRIMARY KEY,
    scope_request_id     TEXT NOT NULL REFERENCES scope_requests(scope_request_id),
    property_id          TEXT NOT NULL REFERENCES properties(property_id),
    pricing_snapshot_id  TEXT NOT NULL REFERENCES pricing_snapshots(snapshot_id),
    unit_estimates_json  TEXT NOT NULL,
    cohort_total_low     REAL NOT NULL,
    cohort_total_high    REAL NOT NULL,
    per_unit_average_low  REAL NOT NULL,
    per_unit_average_high REAL NOT NULL,
    roi_result_json      TEXT NOT NULL,
    risk_flags_json      TEXT NOT NULL DEFAULT '[]',
    sanity_flags_json    TEXT NOT NULL DEFAULT '[]',
    estimated_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scope_estimates_property
    ON scope_estimates(property_id);
CREATE INDEX IF NOT EXISTS idx_scope_estimates_request
    ON scope_estimates(scope_request_id);

CREATE TABLE IF NOT EXISTS actual_outcomes (
    actual_id        TEXT PRIMARY KEY,
    scope_request_id TEXT NOT NULL REFERENCES scope_requests(scope_request_id),
    property_id      TEXT NOT NULL REFERENCES properties(property_id),
    line_items_json  TEXT NOT NULL,
    total_actual     REAL NOT NULL,
    completed_at     TEXT NOT NULL,
    source           TEXT NOT NULL,
    notes            TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_actual_outcomes_property
    ON actual_outcomes(property_id);
CREATE INDEX IF NOT EXISTS idx_actual_outcomes_request
    ON actual_outcomes(scope_request_id);
