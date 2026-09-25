"""Tests for ScopeRequest and friends."""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from plat_costmodel.models import FinishTier, ScopeLevel
from plat_costmodel.schemas.scope import (
    ProgramSchedule,
    ProgramType,
    ScopeRequest,
    UnitCohort,
)


def test_program_type_v1_enum_only_interior():
    assert ProgramType.INTERIOR_RENOVATION.value == "interior_renovation"


def test_unit_cohort_minimal():
    c = UnitCohort(
        floor_plan_id="fp1",
        unit_count=12,
        scope_level=ScopeLevel.STANDARD_VALUE_ADD,
        finish_tier=FinishTier.BASIC,
        current_monthly_rent=850,
        target_monthly_rent=1050,
    )
    assert c.unit_count == 12


def test_unit_cohort_rejects_zero_units():
    with pytest.raises(ValidationError):
        UnitCohort(
            floor_plan_id="fp1", unit_count=0,
            scope_level=ScopeLevel.STANDARD_VALUE_ADD,
            finish_tier=FinishTier.BASIC,
            current_monthly_rent=850, target_monthly_rent=1050,
        )


def test_program_schedule_default_downtime():
    s = ProgramSchedule(start_month="2026-06", monthly_pace=5)
    assert s.downtime_days == 21


def test_scope_request_default_requested_at_is_utc_now():
    req = _scope_request()
    assert req.requested_at.tzinfo is not None
    # within a few seconds of now
    delta = (datetime.now(timezone.utc) - req.requested_at).total_seconds()
    assert 0 <= delta < 5


def test_scope_request_round_trip():
    req = _scope_request()
    assert ScopeRequest.model_validate(req.model_dump()) == req


def _scope_request() -> ScopeRequest:
    return ScopeRequest(
        property_id="p1",
        program_type=ProgramType.INTERIOR_RENOVATION,
        cohort=UnitCohort(
            floor_plan_id="fp1", unit_count=12,
            scope_level=ScopeLevel.STANDARD_VALUE_ADD,
            finish_tier=FinishTier.BASIC,
            current_monthly_rent=850, target_monthly_rent=1050,
        ),
        schedule=ProgramSchedule(start_month="2026-06", monthly_pace=5),
    )


# Slice B additions
from plat_costmodel.schemas.scope import (
    AmenityCohort,
    CohortUnion,
    DeferredMaintenanceCohort,
    ExteriorCohort,
)


def test_program_type_enum_includes_all_four_variants():
    from plat_costmodel.schemas.scope import ProgramType
    assert ProgramType.INTERIOR_RENOVATION.value == "interior_renovation"
    assert ProgramType.EXTERIOR_RENOVATION.value == "exterior_renovation"
    assert ProgramType.AMENITY_ADDITION.value == "amenity_addition"
    assert ProgramType.DEFERRED_MAINTENANCE.value == "deferred_maintenance"


def test_unit_cohort_has_unit_scope_type_default():
    c = UnitCohort(
        floor_plan_id="fp1", unit_count=12,
        scope_level=ScopeLevel.STANDARD_VALUE_ADD,
        finish_tier=FinishTier.BASIC,
        current_monthly_rent=850, target_monthly_rent=1050,
    )
    assert c.scope_type == "unit"


def test_exterior_cohort_minimal():
    c = ExteriorCohort(
        items=["roof", "siding_paint"],
        total_units=120,
    )
    assert c.scope_type == "exterior"
    assert c.items == ["roof", "siding_paint"]
    assert c.roof_age_years is None


def test_exterior_cohort_with_condition_signals():
    c = ExteriorCohort(
        items=["roof", "parking"],
        total_units=80,
        roof_age_years=22,
        parking_condition="poor",
        expected_rent_class_shift="B",
        payback_years_target=7.0,
    )
    assert c.parking_condition == "poor"
    assert c.expected_rent_class_shift == "B"


def test_exterior_cohort_rejects_invalid_parking_condition():
    with pytest.raises(ValidationError):
        ExteriorCohort(
            items=["parking"], total_units=10,
            parking_condition="terrible",
        )


def test_amenity_cohort_minimal():
    c = AmenityCohort(amenity_type="pool")
    assert c.scope_type == "amenity"
    assert c.quantity == 1
    assert c.deluxe is False


def test_amenity_cohort_with_quantity_and_deluxe():
    c = AmenityCohort(
        amenity_type="ev_chargers", quantity=4, deluxe=True,
        expected_occupancy_lift_pct=0.5,
        expected_rent_premium_monthly=25.0,
    )
    assert c.quantity == 4
    assert c.deluxe is True


def test_amenity_cohort_rejects_zero_quantity():
    with pytest.raises(ValidationError):
        AmenityCohort(amenity_type="pool", quantity=0)


def test_deferred_maintenance_cohort_minimal():
    c = DeferredMaintenanceCohort(
        items=["roof_full_replacement"],
        total_units=120,
    )
    assert c.scope_type == "deferred"
    assert c.condition == "end_of_life"


def test_deferred_maintenance_cohort_rejects_invalid_condition():
    with pytest.raises(ValidationError):
        DeferredMaintenanceCohort(
            items=["roof_full_replacement"], total_units=120,
            condition="aging",
        )


def test_cohort_union_routes_by_discriminator_unit():
    payload = {
        "scope_type": "unit", "floor_plan_id": "fp1", "unit_count": 5,
        "scope_level": "standard_value_add", "finish_tier": "basic",
        "current_monthly_rent": 800, "target_monthly_rent": 1000,
    }
    from pydantic import TypeAdapter
    adapter = TypeAdapter(CohortUnion)
    c = adapter.validate_python(payload)
    assert isinstance(c, UnitCohort)


def test_cohort_union_routes_by_discriminator_exterior():
    payload = {"scope_type": "exterior", "items": ["roof"], "total_units": 50}
    from pydantic import TypeAdapter
    adapter = TypeAdapter(CohortUnion)
    c = adapter.validate_python(payload)
    assert isinstance(c, ExteriorCohort)


def test_cohort_union_routes_by_discriminator_amenity():
    payload = {"scope_type": "amenity", "amenity_type": "pool"}
    from pydantic import TypeAdapter
    adapter = TypeAdapter(CohortUnion)
    c = adapter.validate_python(payload)
    assert isinstance(c, AmenityCohort)


def test_cohort_union_routes_by_discriminator_deferred():
    payload = {"scope_type": "deferred", "items": ["roof_full_replacement"], "total_units": 100}
    from pydantic import TypeAdapter
    adapter = TypeAdapter(CohortUnion)
    c = adapter.validate_python(payload)
    assert isinstance(c, DeferredMaintenanceCohort)


def test_cohort_union_rejects_unknown_scope_type():
    payload = {"scope_type": "bogus"}
    from pydantic import TypeAdapter
    adapter = TypeAdapter(CohortUnion)
    with pytest.raises(ValidationError):
        adapter.validate_python(payload)


def test_scope_request_program_type_must_match_cohort_scope_type():
    with pytest.raises(ValidationError) as exc:
        ScopeRequest(
            property_id="p1",
            program_type=ProgramType.INTERIOR_RENOVATION,
            cohort=ExteriorCohort(items=["roof"], total_units=10),
            schedule=ProgramSchedule(start_month="2026-06", monthly_pace=5),
        )
    assert "program_type" in str(exc.value) or "scope_type" in str(exc.value)


def test_scope_request_exterior_renovation_requires_exterior_cohort():
    req = ScopeRequest(
        property_id="p1",
        program_type=ProgramType.EXTERIOR_RENOVATION,
        cohort=ExteriorCohort(items=["roof"], total_units=10),
        schedule=ProgramSchedule(start_month="2026-06", monthly_pace=5),
    )
    assert req.program_type == ProgramType.EXTERIOR_RENOVATION
    assert isinstance(req.cohort, ExteriorCohort)


def test_scope_request_amenity_addition_requires_amenity_cohort():
    req = ScopeRequest(
        property_id="p1",
        program_type=ProgramType.AMENITY_ADDITION,
        cohort=AmenityCohort(amenity_type="pool"),
        schedule=ProgramSchedule(start_month="2026-06", monthly_pace=1),
    )
    assert isinstance(req.cohort, AmenityCohort)


def test_scope_request_deferred_maintenance_requires_deferred_cohort():
    req = ScopeRequest(
        property_id="p1",
        program_type=ProgramType.DEFERRED_MAINTENANCE,
        cohort=DeferredMaintenanceCohort(
            items=["roof_full_replacement"], total_units=10,
        ),
        schedule=ProgramSchedule(start_month="2026-06", monthly_pace=1),
    )
    assert isinstance(req.cohort, DeferredMaintenanceCohort)


def test_scope_request_round_trip_with_exterior_cohort():
    req = ScopeRequest(
        property_id="p1",
        program_type=ProgramType.EXTERIOR_RENOVATION,
        cohort=ExteriorCohort(items=["roof", "parking"], total_units=80),
        schedule=ProgramSchedule(start_month="2026-06", monthly_pace=1),
    )
    rebuilt = ScopeRequest.model_validate(req.model_dump())
    assert rebuilt == req
    assert isinstance(rebuilt.cohort, ExteriorCohort)


def test_scope_request_backfills_scope_type_from_program_type_unit():
    """Slice-A wire callers don't include scope_type in cohort dicts.
    The mode='before' validator must backfill from program_type."""
    raw = {
        "property_id": "p1",
        "program_type": "interior_renovation",
        "cohort": {
            "floor_plan_id": "fp1", "unit_count": 5,
            "scope_level": "standard_value_add", "finish_tier": "basic",
            "current_monthly_rent": 800, "target_monthly_rent": 1000,
        },
        "schedule": {"start_month": "2026-06", "monthly_pace": 5},
    }
    req = ScopeRequest.model_validate(raw)
    assert isinstance(req.cohort, UnitCohort)
    assert req.cohort.scope_type == "unit"


def test_scope_request_backfills_scope_type_for_exterior():
    """Same backfill works for the new variants."""
    raw = {
        "property_id": "p1",
        "program_type": "exterior_renovation",
        "cohort": {"items": ["roof"], "total_units": 50},
        "schedule": {"start_month": "2026-06", "monthly_pace": 1},
    }
    req = ScopeRequest.model_validate(raw)
    assert isinstance(req.cohort, ExteriorCohort)


def test_scope_request_does_not_mutate_caller_dict():
    """Backfill must not mutate the caller's payload."""
    raw = {
        "property_id": "p1",
        "program_type": "interior_renovation",
        "cohort": {
            "floor_plan_id": "fp1", "unit_count": 5,
            "scope_level": "standard_value_add", "finish_tier": "basic",
            "current_monthly_rent": 800, "target_monthly_rent": 1000,
        },
        "schedule": {"start_month": "2026-06", "monthly_pace": 5},
    }
    original_cohort = dict(raw["cohort"])
    ScopeRequest.model_validate(raw)
    assert raw["cohort"] == original_cohort, "validator mutated caller's dict"
