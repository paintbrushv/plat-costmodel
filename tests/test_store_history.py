"""Tests for PropertyRepo.get_history (the linked triple)."""
from datetime import datetime, timezone

from plat_costmodel.models import (
    FinishTier, LineItem, ROIResult, ScopeLevel, SizeCategory, UnitEstimate,
)
from plat_costmodel.schemas import (
    ActualOutcome, ProgramSchedule, ProgramType, Property, ScopeEstimate,
    ScopeRequest, UnitCohort,
)
from plat_costmodel.store.repo import (
    ActualsRepo, EstimateRepo, PropertyRepo, ScopeRepo, SnapshotRepo,
)


def _make_estimate(req_id, prop_id, snap_id) -> ScopeEstimate:
    ue = UnitEstimate(
        unit_id="u1", unit_sqft=850, bedrooms=2, bathrooms=1,
        scope_level=ScopeLevel.STANDARD_VALUE_ADD,
        finish_tier=FinishTier.BASIC,
        size_category=SizeCategory.MEDIUM,
        line_items=[], subtotal_low=0, subtotal_high=0,
        contingency_pct=0.1, contingency_low=0, contingency_high=0,
        total_low=0, total_high=0, risk_flags=[],
    )
    roi = ROIResult(
        total_cost_high=15840, current_monthly_rent=850, target_monthly_rent=1050,
        monthly_rent_lift=200, annual_rent_lift=2400,
        roi_pct=15.15, clears_threshold=True,
    )
    return ScopeEstimate(
        estimate_id="", scope_request_id=req_id,
        property_id=prop_id, floor_plan_id="fp-test",
        pricing_snapshot_id=snap_id,
        unit_estimates=[ue], cohort_total_low=0, cohort_total_high=0,
        per_unit_average_low=0, per_unit_average_high=0,
        roi_result=roi, risk_flags=[], sanity_flags=[],
        estimated_at=datetime.now(timezone.utc),
    )


def test_history_with_no_actuals_yields_none_for_actual(tmp_db):
    prop_repo = PropertyRepo(tmp_db)
    p = prop_repo.create(Property(property_id="", total_units=12))
    snap = SnapshotRepo(tmp_db).get_or_create_for_kb_hash("k1")
    req = ScopeRepo(tmp_db).create(ScopeRequest(
        property_id=p.property_id,
        program_type=ProgramType.INTERIOR_RENOVATION,
        cohort=UnitCohort(
            floor_plan_id="fp1", unit_count=12,
            scope_level=ScopeLevel.STANDARD_VALUE_ADD,
            finish_tier=FinishTier.BASIC,
            current_monthly_rent=850, target_monthly_rent=1050,
        ),
        schedule=ProgramSchedule(start_month="2026-06", monthly_pace=5),
    ))
    EstimateRepo(tmp_db).create(_make_estimate(req.scope_request_id, p.property_id, snap.snapshot_id))
    history = prop_repo.get_history(p.property_id)
    assert len(history) == 1
    triple = history[0]
    assert triple["scope_request"].scope_request_id == req.scope_request_id
    assert triple["scope_estimate"] is not None
    assert triple["actual_outcome"] is None


def test_history_links_actual_when_present(tmp_db):
    prop_repo = PropertyRepo(tmp_db)
    p = prop_repo.create(Property(property_id="", total_units=12))
    snap = SnapshotRepo(tmp_db).get_or_create_for_kb_hash("k1")
    req = ScopeRepo(tmp_db).create(ScopeRequest(
        property_id=p.property_id,
        program_type=ProgramType.INTERIOR_RENOVATION,
        cohort=UnitCohort(
            floor_plan_id="fp1", unit_count=12,
            scope_level=ScopeLevel.STANDARD_VALUE_ADD,
            finish_tier=FinishTier.BASIC,
            current_monthly_rent=850, target_monthly_rent=1050,
        ),
        schedule=ProgramSchedule(start_month="2026-06", monthly_pace=5),
    ))
    EstimateRepo(tmp_db).create(_make_estimate(req.scope_request_id, p.property_id, snap.snapshot_id))
    ActualsRepo(tmp_db).create(ActualOutcome(
        actual_id="", scope_request_id=req.scope_request_id,
        property_id=p.property_id, line_items=[LineItem(category="paint", low=900, high=900)],
        total_actual=900, completed_at=datetime.now(timezone.utc), source="manual",
    ))
    history = prop_repo.get_history(p.property_id)
    assert history[0]["actual_outcome"].total_actual == 900
