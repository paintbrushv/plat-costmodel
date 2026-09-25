-- 002: denormalize floor_plan_id onto scope_estimates for the future
-- get_for_floor_plan calibration query. Backfill from the originating
-- scope_request's cohort_json (cohort.floor_plan_id field).

ALTER TABLE scope_estimates ADD COLUMN floor_plan_id TEXT;

-- Backfill existing rows from the cohort_json on scope_requests.
-- json_extract reads "$.floor_plan_id" out of the cohort blob.
UPDATE scope_estimates
SET floor_plan_id = (
    SELECT json_extract(scope_requests.cohort_json, '$.floor_plan_id')
    FROM scope_requests
    WHERE scope_requests.scope_request_id = scope_estimates.scope_request_id
);

CREATE INDEX IF NOT EXISTS idx_scope_estimates_floor_plan
    ON scope_estimates(floor_plan_id);
