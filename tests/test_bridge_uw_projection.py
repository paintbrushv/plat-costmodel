"""Tests for the new ScopeEstimate → renovation_program projection."""
from datetime import datetime, timezone

import pytest

from plat_costmodel.bridge.uw_projection import (
    project_estimate_to_renovation_program,
)
from plat_costmodel.models import (
    FinishTier, ROIResult, ScopeLevel, SizeCategory, UnitEstimate,
)
from plat_costmodel.schemas import ProgramSchedule, ScopeEstimate


def _est(per_unit_high: float = 14000, clears: bool = True) -> ScopeEstimate:
    ue = UnitEstimate(
        unit_id="u1", unit_sqft=850, bedrooms=2, bathrooms=1,
        scope_level=ScopeLevel.STANDARD_VALUE_ADD,
        finish_tier=FinishTier.BASIC,
        size_category=SizeCategory.MEDIUM,
        line_items=[], subtotal_low=0, subtotal_high=0,
        contingency_pct=0.1, contingency_low=0, contingency_high=0,
        total_low=per_unit_high * 0.7, total_high=per_unit_high,
        risk_flags=[],
    )
    roi = ROIResult(
        total_cost_high=per_unit_high, current_monthly_rent=850,
        target_monthly_rent=1050, monthly_rent_lift=200, annual_rent_lift=2400,
        roi_pct=2400 / per_unit_high * 100,
        clears_threshold=clears,
    )
    return ScopeEstimate(
        estimate_id="e1", scope_request_id="r1", property_id="p1",
        floor_plan_id="fp-test",
        pricing_snapshot_id="s1",
        unit_estimates=[ue],
        cohort_total_low=per_unit_high * 0.7,
        cohort_total_high=per_unit_high,
        per_unit_average_low=per_unit_high * 0.7,
        per_unit_average_high=per_unit_high,
        roi_result=roi, risk_flags=[], sanity_flags=[],
        estimated_at=datetime.now(timezone.utc),
    )


def test_project_uses_per_unit_high_as_cost():
    sched = ProgramSchedule(start_month="2026-06", monthly_pace=5)
    out = project_estimate_to_renovation_program(_est(14000), sched)
    assert out["renovation_cost_per_unit"] == 14000
    assert out["start_month"] == "2026-06"
    assert out["monthly_pace"] == 5
    assert out["downtime_days"] == 21
    assert out["strategy"] == "renovation"
    assert out["rent_premium_monthly"] == 200  # 1050 - 850


def test_project_quantizes_currency_to_2dp():
    # Set up an estimate where the float arithmetic would drift.
    est = _est(14000.005)
    out = project_estimate_to_renovation_program(
        est, ProgramSchedule(start_month="2026-06", monthly_pace=5)
    )
    assert isinstance(out["renovation_cost_per_unit"], float)
    # quantized via Decimal — would be 14000.01, not 14000.0049999...
    assert out["renovation_cost_per_unit"] == 14000.01
