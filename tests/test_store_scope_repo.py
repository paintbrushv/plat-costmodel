"""Tests for ScopeRepo."""
import pytest

from plat_costmodel.models import FinishTier, ScopeLevel
from plat_costmodel.schemas import (
    AmenityCohort,
    DeferredMaintenanceCohort,
    ExteriorCohort,
    InteriorScopeEstimate,
    ProgramSchedule,
    ProgramType,
    Property,
    ScopeRequest,
    UnitCohort,
)
from plat_costmodel.store.repo import PropertyRepo, ScopeRepo


def _seed_property(tmp_db) -> Property:
    return PropertyRepo(tmp_db).create(Property(property_id="", total_units=12))


def _make_request(property_id: str) -> ScopeRequest:
    return ScopeRequest(
        property_id=property_id,
        program_type=ProgramType.INTERIOR_RENOVATION,
        cohort=UnitCohort(
            floor_plan_id="fp1", unit_count=12,
            scope_level=ScopeLevel.STANDARD_VALUE_ADD,
            finish_tier=FinishTier.BASIC,
            current_monthly_rent=850, target_monthly_rent=1050,
        ),
        schedule=ProgramSchedule(start_month="2026-06", monthly_pace=5),
    )


def test_create_mints_id_and_persists(tmp_db):
    p = _seed_property(tmp_db)
    repo = ScopeRepo(tmp_db)
    saved = repo.create(_make_request(p.property_id))
    assert len(saved.scope_request_id) == 26
    fetched = repo.get(saved.scope_request_id)
    assert fetched is not None
    assert fetched.cohort.unit_count == 12


def test_create_with_supplied_id_keeps_it(tmp_db):
    p = _seed_property(tmp_db)
    repo = ScopeRepo(tmp_db)
    req = _make_request(p.property_id)
    req = req.model_copy(update={"scope_request_id": "REQ-CUSTOM"})
    saved = repo.create(req)
    assert saved.scope_request_id == "REQ-CUSTOM"


def test_orphan_request_rejected(tmp_db):
    repo = ScopeRepo(tmp_db)
    with pytest.raises(Exception):  # FK violation surfaces as IntegrityError
        repo.create(_make_request("does-not-exist"))


def test_list_for_property(tmp_db):
    p = _seed_property(tmp_db)
    repo = ScopeRepo(tmp_db)
    repo.create(_make_request(p.property_id))
    repo.create(_make_request(p.property_id))
    requests = repo.list_for_property(p.property_id)
    assert len(requests) == 2


# ---------------------------------------------------------------------------
# 4-variant cohort round-trip tests (TypeAdapter(CohortUnion) path)
# ---------------------------------------------------------------------------

def test_scope_repo_round_trips_unit_cohort(tmp_db):
    """UnitCohort deserializes via TypeAdapter after ScopeRepo switch."""
    p = _seed_property(tmp_db)
    repo = ScopeRepo(tmp_db)
    saved = repo.create(_make_request(p.property_id))
    fetched = repo.get(saved.scope_request_id)
    assert isinstance(fetched.cohort, UnitCohort)
    assert fetched.cohort.unit_count == 12
    assert fetched.cohort.floor_plan_id == "fp1"


def test_scope_repo_round_trips_exterior_cohort(tmp_db):
    """ExteriorCohort persists and deserializes correctly."""
    p = _seed_property(tmp_db)
    repo = ScopeRepo(tmp_db)
    req = ScopeRequest(
        property_id=p.property_id,
        program_type=ProgramType.EXTERIOR_RENOVATION,
        cohort=ExteriorCohort(
            items=["roof", "siding_paint"],
            total_units=80,
            roof_age_years=22,
        ),
        schedule=ProgramSchedule(start_month="2026-07", monthly_pace=1),
    )
    saved = repo.create(req)
    fetched = repo.get(saved.scope_request_id)
    assert isinstance(fetched.cohort, ExteriorCohort)
    assert fetched.cohort.total_units == 80
    assert "roof" in fetched.cohort.items
    assert fetched.cohort.roof_age_years == 22


def test_scope_repo_round_trips_amenity_cohort(tmp_db):
    """AmenityCohort persists and deserializes correctly."""
    p = _seed_property(tmp_db)
    repo = ScopeRepo(tmp_db)
    req = ScopeRequest(
        property_id=p.property_id,
        program_type=ProgramType.AMENITY_ADDITION,
        cohort=AmenityCohort(
            amenity_type="ev_chargers",
            quantity=10,
            deluxe=True,
        ),
        schedule=ProgramSchedule(start_month="2026-08", monthly_pace=1),
    )
    saved = repo.create(req)
    fetched = repo.get(saved.scope_request_id)
    assert isinstance(fetched.cohort, AmenityCohort)
    assert fetched.cohort.amenity_type == "ev_chargers"
    assert fetched.cohort.quantity == 10
    assert fetched.cohort.deluxe is True


def test_scope_repo_round_trips_deferred_maintenance_cohort(tmp_db):
    """DeferredMaintenanceCohort persists and deserializes correctly."""
    p = _seed_property(tmp_db)
    repo = ScopeRepo(tmp_db)
    req = ScopeRequest(
        property_id=p.property_id,
        program_type=ProgramType.DEFERRED_MAINTENANCE,
        cohort=DeferredMaintenanceCohort(
            items=["roof", "hvac"],
            total_units=60,
            age_at_replacement_years=25,
            condition="end_of_life",
        ),
        schedule=ProgramSchedule(start_month="2026-09", monthly_pace=1),
    )
    saved = repo.create(req)
    fetched = repo.get(saved.scope_request_id)
    assert isinstance(fetched.cohort, DeferredMaintenanceCohort)
    assert fetched.cohort.total_units == 60
    assert "hvac" in fetched.cohort.items
    assert fetched.cohort.age_at_replacement_years == 25
    assert fetched.cohort.condition == "end_of_life"
