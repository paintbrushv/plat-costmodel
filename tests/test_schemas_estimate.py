"""Tests for PricingSnapshot and ScopeEstimate."""
import pytest
from datetime import datetime, timezone

from plat_costmodel.models import (
    FinishTier,
    LineItem,
    ROIResult,
    ScopeLevel,
    SizeCategory,
    UnitEstimate,
)
from plat_costmodel.schemas.estimate import PricingSnapshot, ScopeEstimate


def test_pricing_snapshot_round_trip():
    s = PricingSnapshot(
        snapshot_id="snap1",
        captured_at=datetime.now(timezone.utc),
        kb_version_hash="abc123",
    )
    assert s.external_feeds == {}
    assert PricingSnapshot.model_validate(s.model_dump()) == s


def test_scope_estimate_round_trip():
    ue = UnitEstimate(
        unit_id="u1", unit_sqft=850, bedrooms=2, bathrooms=1,
        scope_level=ScopeLevel.STANDARD_VALUE_ADD,
        finish_tier=FinishTier.BASIC,
        size_category=SizeCategory.MEDIUM,
        line_items=[LineItem(category="paint", low=800, high=1200)],
        subtotal_low=800, subtotal_high=1200,
        contingency_pct=0.10,
        contingency_low=80, contingency_high=120,
        total_low=880, total_high=1320,
        risk_flags=[],
    )
    roi = ROIResult(
        total_cost_high=15840,
        current_monthly_rent=850,
        target_monthly_rent=1050,
        monthly_rent_lift=200,
        annual_rent_lift=2400,
        roi_pct=15.15,
        clears_threshold=True,
    )
    est = ScopeEstimate(
        estimate_id="est1",
        scope_request_id="req1",
        property_id="p1",
        floor_plan_id="fp-test",
        pricing_snapshot_id="snap1",
        unit_estimates=[ue],
        cohort_total_low=10560,
        cohort_total_high=15840,
        per_unit_average_low=880,
        per_unit_average_high=1320,
        roi_result=roi,
        risk_flags=[],
        sanity_flags=[],
        estimated_at=datetime.now(timezone.utc),
    )
    assert ScopeEstimate.model_validate(est.model_dump()) == est


# Slice B additions
from pydantic import TypeAdapter, ValidationError

from plat_costmodel.models import LineItem
from plat_costmodel.schemas.estimate import (
    AmenityScopeEstimate,
    DeferredMaintenanceEstimate,
    ExteriorScopeEstimate,
    InteriorScopeEstimate,
    ScopeEstimate,
    ScopeEstimateUnion,
)
from plat_costmodel.schemas.results import (
    OccupancyLiftResult,
    RentPremiumResult,
)


def test_scope_estimate_alias_points_at_interior_variant():
    """Slice-A code imports ScopeEstimate; alias must keep the same concrete
    type so .unit_estimates / .roi_result access is type-stable."""
    assert ScopeEstimate is InteriorScopeEstimate


def test_interior_scope_estimate_has_unit_scope_type():
    ue = UnitEstimate(
        unit_id="u1", unit_sqft=850, bedrooms=2, bathrooms=1,
        scope_level=ScopeLevel.STANDARD_VALUE_ADD,
        finish_tier=FinishTier.BASIC,
        size_category=SizeCategory.MEDIUM,
        line_items=[LineItem(category="paint", low=800, high=1200)],
        subtotal_low=800, subtotal_high=1200,
        contingency_pct=0.10,
        contingency_low=80, contingency_high=120,
        total_low=880, total_high=1320,
        risk_flags=[],
    )
    roi = ROIResult(
        total_cost_high=15840, current_monthly_rent=850, target_monthly_rent=1050,
        monthly_rent_lift=200, annual_rent_lift=2400, roi_pct=15.15,
        clears_threshold=True,
    )
    est = InteriorScopeEstimate(
        estimate_id="est1", scope_request_id="req1",
        property_id="p1", floor_plan_id="fp1", pricing_snapshot_id="snap1",
        unit_estimates=[ue],
        cohort_total_low=880, cohort_total_high=1320,
        per_unit_average_low=880, per_unit_average_high=1320,
        roi_result=roi, risk_flags=[], sanity_flags=[],
        estimated_at=datetime.now(timezone.utc),
    )
    assert est.scope_type == "unit"


def test_exterior_scope_estimate_minimal():
    est = ExteriorScopeEstimate(
        estimate_id="est2", scope_request_id="req2", property_id="p1",
        pricing_snapshot_id="snap1",
        line_items=[LineItem(category="roof", low=120000, high=180000)],
        total_low=120000, total_high=180000,
        per_unit_low=1000, per_unit_high=1500,
        risk_flags=[], sanity_flags=[],
        estimated_at=datetime.now(timezone.utc),
    )
    assert est.scope_type == "exterior"
    assert est.payback_years_estimated is None


def test_amenity_scope_estimate_with_lift_result():
    lift = OccupancyLiftResult(
        target_lift_pct=1.5, projected_lift_pct=1.8, clears_threshold=True,
    )
    est = AmenityScopeEstimate(
        estimate_id="est3", scope_request_id="req3", property_id="p1",
        pricing_snapshot_id="snap1",
        amenity_type="pool",
        install_cost_low=80000, install_cost_high=150000,
        annual_opex_low=8000, annual_opex_high=15000,
        expected_occupancy_lift_result=lift,
        risk_flags=[], sanity_flags=[],
        estimated_at=datetime.now(timezone.utc),
    )
    assert est.scope_type == "amenity"
    assert est.expected_occupancy_lift_result.clears_threshold is True


def test_amenity_scope_estimate_with_rent_premium_result():
    premium = RentPremiumResult(
        target_premium_monthly=25.0, projected_premium_monthly=30.0,
        clears_threshold=True,
    )
    est = AmenityScopeEstimate(
        estimate_id="est4", scope_request_id="req4", property_id="p1",
        pricing_snapshot_id="snap1",
        amenity_type="ev_chargers",
        install_cost_low=16000, install_cost_high=32000,
        expected_rent_premium_result=premium,
        risk_flags=[], sanity_flags=[],
        estimated_at=datetime.now(timezone.utc),
    )
    assert est.expected_rent_premium_result.annual_premium_per_unit == 360.0


def test_deferred_maintenance_estimate_minimal():
    est = DeferredMaintenanceEstimate(
        estimate_id="est5", scope_request_id="req5", property_id="p1",
        pricing_snapshot_id="snap1",
        line_items=[LineItem(category="roof_full_replacement", low=300000, high=480000)],
        total_low=300000, total_high=480000,
        per_unit_low=2500, per_unit_high=4000,
        triggered_by="roof age 28yr exceeds typical_age_years=25",
        risk_flags=[], sanity_flags=[],
        estimated_at=datetime.now(timezone.utc),
    )
    assert est.scope_type == "deferred"


def test_scope_estimate_union_routes_by_discriminator():
    adapter = TypeAdapter(ScopeEstimateUnion)

    interior_payload = {
        "scope_type": "unit",
        "estimate_id": "e", "scope_request_id": "r", "property_id": "p",
        "floor_plan_id": "fp", "pricing_snapshot_id": "s",
        "unit_estimates": [],
        "cohort_total_low": 0, "cohort_total_high": 0,
        "per_unit_average_low": 0, "per_unit_average_high": 0,
        "roi_result": {
            "total_cost_high": 0, "current_monthly_rent": 0,
            "target_monthly_rent": 0, "monthly_rent_lift": 0,
            "annual_rent_lift": 0, "roi_pct": 0, "clears_threshold": False,
        },
        "risk_flags": [], "sanity_flags": [],
        "estimated_at": datetime.now(timezone.utc).isoformat(),
    }
    parsed = adapter.validate_python(interior_payload)
    assert isinstance(parsed, InteriorScopeEstimate)

    exterior_payload = {
        "scope_type": "exterior",
        "estimate_id": "e", "scope_request_id": "r", "property_id": "p",
        "pricing_snapshot_id": "s",
        "line_items": [{"category": "roof", "low": 100, "high": 200}],
        "total_low": 100, "total_high": 200,
        "per_unit_low": 10, "per_unit_high": 20,
        "risk_flags": [], "sanity_flags": [],
        "estimated_at": datetime.now(timezone.utc).isoformat(),
    }
    parsed = adapter.validate_python(exterior_payload)
    assert isinstance(parsed, ExteriorScopeEstimate)

    amenity_payload = {
        "scope_type": "amenity",
        "estimate_id": "e", "scope_request_id": "r", "property_id": "p",
        "pricing_snapshot_id": "s",
        "amenity_type": "pool",
        "install_cost_low": 80000, "install_cost_high": 150000,
        "risk_flags": [], "sanity_flags": [],
        "estimated_at": datetime.now(timezone.utc).isoformat(),
    }
    parsed = adapter.validate_python(amenity_payload)
    assert isinstance(parsed, AmenityScopeEstimate)

    deferred_payload = {
        "scope_type": "deferred",
        "estimate_id": "e", "scope_request_id": "r", "property_id": "p",
        "pricing_snapshot_id": "s",
        "line_items": [{"category": "roof_full_replacement", "low": 100, "high": 200}],
        "total_low": 100, "total_high": 200,
        "per_unit_low": 10, "per_unit_high": 20,
        "triggered_by": "roof age 28yr",
        "risk_flags": [], "sanity_flags": [],
        "estimated_at": datetime.now(timezone.utc).isoformat(),
    }
    parsed = adapter.validate_python(deferred_payload)
    assert isinstance(parsed, DeferredMaintenanceEstimate)


def test_scope_estimate_union_rejects_unknown_scope_type():
    adapter = TypeAdapter(ScopeEstimateUnion)
    with pytest.raises(ValidationError):
        adapter.validate_python({"scope_type": "bogus"})
