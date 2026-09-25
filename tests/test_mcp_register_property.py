"""Tests for the register_property MCP tool."""
from plat_costmodel.server import register_property


def test_register_property_mints_and_persists(tmp_db):
    out = register_property({
        "external_alias": "addr-1",
        "address": "1 Main St",
        "total_units": 12,
        "floor_plans": [
            {"name": "A", "sqft": 750, "bedrooms": 1, "bathrooms": 1},
            {"name": "B", "sqft": 850, "bedrooms": 2, "bathrooms": 1},
        ],
    })
    assert "property_id" in out
    assert len(out["floor_plans"]) == 2
    assert all(fp["floor_plan_id"] for fp in out["floor_plans"])


def test_register_property_idempotent_on_alias(tmp_db):
    payload = {"external_alias": "addr-2", "total_units": 4}
    a = register_property(payload)
    b = register_property(payload)
    assert a["property_id"] == b["property_id"]


def test_register_property_returns_validation_problem_on_bad_input(tmp_db):
    out = register_property({"total_units": -1})  # negative not allowed
    assert out["error_type"] == "validation_error"
    assert out["field_errors"]


def test_register_property_dedupes_floor_plans_on_second_call(tmp_db):
    """Followup: previously, calling register_property twice with the same
    alias short-circuited and silently dropped any floor_plans in the second
    call. Now it dedupes by (sqft, beds, baths) so existing plans are reused
    and new plans are added."""
    payload_v1 = {
        "external_alias": "dedup-test",
        "total_units": 4,
        "floor_plans": [{"name": "A", "sqft": 750, "bedrooms": 1, "bathrooms": 1}],
    }
    a = register_property(payload_v1)
    assert len(a["floor_plans"]) == 1

    # Same alias + same floor plan → idempotent (no duplicate created).
    b = register_property(payload_v1)
    assert b["property_id"] == a["property_id"]
    assert len(b["floor_plans"]) == 1

    # Same alias + new floor plan → new plan added (previously dropped).
    payload_v2 = dict(payload_v1)
    payload_v2["floor_plans"] = [
        {"name": "A", "sqft": 750, "bedrooms": 1, "bathrooms": 1},  # existing
        {"name": "B", "sqft": 850, "bedrooms": 2, "bathrooms": 1},  # new
    ]
    c = register_property(payload_v2)
    assert c["property_id"] == a["property_id"]
    assert len(c["floor_plans"]) == 2
    assert {fp["name"] for fp in c["floor_plans"]} == {"A", "B"}
