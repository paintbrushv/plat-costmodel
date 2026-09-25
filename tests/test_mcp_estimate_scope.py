"""Tests for the estimate_scope MCP tool."""
from plat_costmodel.server import estimate_scope as estimate_scope_tool, register_property


def test_estimate_scope_round_trip(tmp_db):
    reg = register_property({
        "external_alias": "p1", "total_units": 12,
        "floor_plans": [{"name": "B", "sqft": 850, "bedrooms": 2, "bathrooms": 1}],
    })
    fp_id = reg["floor_plans"][0]["floor_plan_id"]
    out = estimate_scope_tool({
        "property_id": reg["property_id"],
        "program_type": "interior_renovation",
        "cohort": {
            "floor_plan_id": fp_id,
            "unit_count": 12,
            "scope_level": "standard_value_add",
            "finish_tier": "basic",
            "current_monthly_rent": 850,
            "target_monthly_rent": 1100,
        },
        "schedule": {"start_month": "2026-06", "monthly_pace": 5, "downtime_days": 21},
    })
    assert "estimate_id" in out
    assert out["per_unit_average_high"] > 0
    assert out["roi_result"]["clears_threshold"]


def test_estimate_scope_returns_problem_on_unknown_property(tmp_db):
    out = estimate_scope_tool({
        "property_id": "does-not-exist",
        "program_type": "interior_renovation",
        "cohort": {
            "floor_plan_id": "fp1", "unit_count": 1,
            "scope_level": "standard_value_add", "finish_tier": "basic",
            "current_monthly_rent": 1, "target_monthly_rent": 1,
        },
        "schedule": {"start_month": "2026-06", "monthly_pace": 1},
    })
    assert out["error_type"] == "not_found"
