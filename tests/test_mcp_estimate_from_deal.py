"""Tests for the estimate_from_deal MCP tool."""
from plat_costmodel.server import estimate_from_deal


def _good_deal() -> dict:
    return {
        "schema_version": "0.1",
        "property": {
            "external_alias": "deal-prop", "total_units": 12,
            "address": "1 Main St", "year_built": 1985,
        },
        "unit_cohorts": [
            {"avg_sqft": 850, "avg_bedrooms": 2, "avg_bathrooms": 1,
             "unit_count": 12, "current_avg_rent": 850},
        ],
        "renovation_programs": [
            {"cohort_index": 0, "scope_level": "standard_value_add",
             "finish_tier": "basic", "rent_premium_monthly": 250,
             "start_month": "2026-06", "monthly_pace": 5, "downtime_days": 21},
        ],
    }


def _scenarios_for_good_deal() -> list[dict]:
    """Mirrors the renovation_programs in _good_deal() as scenario dicts."""
    return [
        {
            "scope_type": "unit",
            "cohort_id": "cohort_0",
            "scope_level": "standard_value_add",
            "finish_tier": "basic",
            "rent_premium_monthly": 200,
            "schedule": {"start_month": "2026-06", "monthly_pace": 5},
        },
    ]


def test_estimate_from_deal_returns_index_aligned_lists(tmp_db):
    out = estimate_from_deal(_good_deal(), _scenarios_for_good_deal())
    assert len(out["estimates"]) == 1
    assert len(out["renovation_programs"]) == 1
    rp = out["renovation_programs"][0]
    assert rp["start_month"] == "2026-06"
    assert rp["renovation_cost_per_unit"] > 0
    assert rp["rent_premium_monthly"] == 200


def test_estimate_from_deal_returns_problem_on_missing_field(tmp_db):
    bad = _good_deal()
    bad.pop("unit_cohorts")
    out = estimate_from_deal(bad, _scenarios_for_good_deal())
    assert out["error_type"] == "validation_error"
    assert out["field_errors"]
    assert any("unit_cohorts" in str(fe.get("loc", "")) for fe in out["field_errors"])


def test_estimate_from_deal_does_not_return_taskgroup_string(tmp_db):
    """Regression: today's smoke test returned the literal swallowed string.
    The new path must never produce it."""
    bad = _good_deal()
    bad.pop("unit_cohorts")
    out = estimate_from_deal(bad, _scenarios_for_good_deal())
    assert "unhandled errors in a TaskGroup" not in (
        out.get("message", "") + " ".join(str(fe) for fe in out.get("field_errors", []))
    )
    assert out["error_type"] == "validation_error"


def test_estimate_from_deal_empty_scenarios_returns_empty_lists(tmp_db):
    out = estimate_from_deal(_good_deal(), [])
    assert out["estimates"] == []
    assert out["renovation_programs"] == []
