"""Tests for scenario discriminated union (slice B PR 2)."""
from datetime import datetime, timezone

import pytest
from pydantic import TypeAdapter, ValidationError

from plat_costmodel.models import FinishTier, ScopeLevel
from plat_costmodel.schemas import ProgramSchedule
from plat_costmodel.schemas.scenario import (
    AmenityScenario,
    DeferredMaintenanceScenario,
    ExteriorScenario,
    InteriorScenario,
    ScenarioUnion,
)


def _schedule() -> ProgramSchedule:
    return ProgramSchedule(start_month="2026-06", monthly_pace=5)


def test_interior_scenario_minimal():
    s = InteriorScenario(
        cohort_id="C1",
        scope_level=ScopeLevel.STANDARD_VALUE_ADD,
        finish_tier=FinishTier.BASIC,
        rent_premium_monthly=200.0,
        schedule=_schedule(),
    )
    assert s.scope_type == "unit"
    assert s.cohort_id == "C1"


def test_interior_scenario_rejects_negative_premium():
    with pytest.raises(ValidationError):
        InteriorScenario(
            cohort_id="C1",
            scope_level=ScopeLevel.STANDARD_VALUE_ADD,
            finish_tier=FinishTier.BASIC,
            rent_premium_monthly=-10.0,
            schedule=_schedule(),
        )


def test_exterior_scenario_minimal():
    s = ExteriorScenario(items=["roof", "siding_paint"], schedule=_schedule())
    assert s.scope_type == "exterior"
    assert s.expected_rent_class_shift is None


def test_exterior_scenario_with_class_shift():
    s = ExteriorScenario(
        items=["roof"],
        schedule=_schedule(),
        expected_rent_class_shift="B",
        payback_years_target=8.0,
    )
    assert s.expected_rent_class_shift == "B"


def test_exterior_scenario_rejects_invalid_class_shift():
    with pytest.raises(ValidationError):
        ExteriorScenario(items=["roof"], schedule=_schedule(),
                         expected_rent_class_shift="A")


def test_amenity_scenario_minimal():
    s = AmenityScenario(amenity_type="pool", schedule=_schedule())
    assert s.scope_type == "amenity"
    assert s.quantity == 1
    assert s.deluxe is False


def test_amenity_scenario_with_quantity():
    s = AmenityScenario(amenity_type="ev_chargers", quantity=4, deluxe=True,
                        schedule=_schedule(),
                        expected_rent_premium_monthly=25.0)
    assert s.quantity == 4
    assert s.deluxe is True


def test_amenity_scenario_rejects_zero_quantity():
    with pytest.raises(ValidationError):
        AmenityScenario(amenity_type="pool", quantity=0, schedule=_schedule())


def test_deferred_maintenance_scenario_minimal():
    s = DeferredMaintenanceScenario(
        items=["roof_full_replacement"], schedule=_schedule(),
    )
    assert s.scope_type == "deferred"
    assert s.condition == "end_of_life"


def test_scenario_union_routes_by_discriminator():
    adapter = TypeAdapter(ScenarioUnion)

    interior_payload = {
        "scope_type": "unit", "cohort_id": "C1",
        "scope_level": "standard_value_add", "finish_tier": "basic",
        "rent_premium_monthly": 200.0,
        "schedule": {"start_month": "2026-06", "monthly_pace": 5},
    }
    assert isinstance(adapter.validate_python(interior_payload), InteriorScenario)

    exterior_payload = {
        "scope_type": "exterior", "items": ["roof"],
        "schedule": {"start_month": "2026-06", "monthly_pace": 1},
    }
    assert isinstance(adapter.validate_python(exterior_payload), ExteriorScenario)

    amenity_payload = {
        "scope_type": "amenity", "amenity_type": "pool",
        "schedule": {"start_month": "2026-06", "monthly_pace": 1},
    }
    assert isinstance(adapter.validate_python(amenity_payload), AmenityScenario)

    deferred_payload = {
        "scope_type": "deferred", "items": ["roof_full_replacement"],
        "schedule": {"start_month": "2026-06", "monthly_pace": 1},
    }
    assert isinstance(adapter.validate_python(deferred_payload), DeferredMaintenanceScenario)


def test_scenario_union_rejects_unknown_scope_type():
    adapter = TypeAdapter(ScenarioUnion)
    with pytest.raises(ValidationError):
        adapter.validate_python({"scope_type": "bogus"})
