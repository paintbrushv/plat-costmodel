"""Tests for ActualsRepo (schema-only path; manual insertion supported)."""
from datetime import datetime, timezone

from plat_costmodel.models import (
    FinishTier, LineItem, ScopeLevel,
)
from plat_costmodel.schemas import (
    ActualOutcome, ProgramSchedule, ProgramType, Property,
    ScopeRequest, UnitCohort,
)
from plat_costmodel.store.repo import (
    ActualsRepo, PropertyRepo, ScopeRepo,
)


def _seed(tmp_db):
    p = PropertyRepo(tmp_db).create(Property(property_id="", total_units=10))
    req = ScopeRepo(tmp_db).create(ScopeRequest(
        property_id=p.property_id,
        program_type=ProgramType.INTERIOR_RENOVATION,
        cohort=UnitCohort(
            floor_plan_id="fp1", unit_count=10,
            scope_level=ScopeLevel.STANDARD_VALUE_ADD,
            finish_tier=FinishTier.BASIC,
            current_monthly_rent=850, target_monthly_rent=1050,
        ),
        schedule=ProgramSchedule(start_month="2026-06", monthly_pace=5),
    ))
    return p, req


def test_create_mints_id_and_round_trip(tmp_db):
    p, req = _seed(tmp_db)
    repo = ActualsRepo(tmp_db)
    saved = repo.create(ActualOutcome(
        actual_id="", scope_request_id=req.scope_request_id,
        property_id=p.property_id,
        line_items=[LineItem(category="paint", low=900, high=900)],
        total_actual=900,
        completed_at=datetime.now(timezone.utc),
        source="manual",
    ))
    assert len(saved.actual_id) == 26
    fetched = repo.get(saved.actual_id)
    assert fetched.total_actual == 900


def test_list_for_request(tmp_db):
    p, req = _seed(tmp_db)
    repo = ActualsRepo(tmp_db)
    repo.create(ActualOutcome(
        actual_id="", scope_request_id=req.scope_request_id,
        property_id=p.property_id, line_items=[],
        total_actual=100, completed_at=datetime.now(timezone.utc), source="manual",
    ))
    repo.create(ActualOutcome(
        actual_id="", scope_request_id=req.scope_request_id,
        property_id=p.property_id, line_items=[],
        total_actual=200, completed_at=datetime.now(timezone.utc), source="manual",
    ))
    assert len(repo.list_for_request(req.scope_request_id)) == 2
