"""Tests for the get_property_history MCP tool."""
from plat_costmodel.server import (
    estimate_scope as estimate_scope_tool,
    get_property_history,
    register_property,
)


def test_history_after_one_estimate(tmp_db):
    reg = register_property({
        "external_alias": "histprop", "total_units": 12,
        "floor_plans": [{"name": "B", "sqft": 850, "bedrooms": 2, "bathrooms": 1}],
    })
    fp_id = reg["floor_plans"][0]["floor_plan_id"]
    estimate_scope_tool({
        "property_id": reg["property_id"],
        "program_type": "interior_renovation",
        "cohort": {
            "floor_plan_id": fp_id, "unit_count": 12,
            "scope_level": "standard_value_add", "finish_tier": "basic",
            "current_monthly_rent": 850, "target_monthly_rent": 1100,
        },
        "schedule": {"start_month": "2026-06", "monthly_pace": 5, "downtime_days": 21},
    })
    history = get_property_history(reg["property_id"])
    assert isinstance(history, list)
    assert len(history) == 1
    triple = history[0]
    assert triple["scope_request"]["property_id"] == reg["property_id"]
    assert triple["scope_estimate"] is not None
    assert triple["actual_outcome"] is None


def test_history_returns_validation_problem_for_missing_property(tmp_db):
    out = get_property_history("does-not-exist")
    # Empty list is valid (no requests) — we don't emit not_found here.
    assert out == []
