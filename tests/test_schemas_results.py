"""Tests for per-program-type success-metric result models."""
import pytest
from pydantic import ValidationError

from plat_costmodel.schemas.results import (
    OccupancyLiftResult,
    RentPremiumResult,
)


def test_occupancy_lift_clears_threshold_when_projected_meets_target():
    r = OccupancyLiftResult(
        target_lift_pct=1.5,
        projected_lift_pct=1.8,
        clears_threshold=True,
    )
    assert r.clears_threshold is True
    assert r.shortfall_pct is None or r.shortfall_pct <= 0


def test_occupancy_lift_fails_threshold_when_projected_below_target():
    r = OccupancyLiftResult(
        target_lift_pct=2.0,
        projected_lift_pct=0.8,
        clears_threshold=False,
        shortfall_pct=1.2,
        path_to_pass="Add fitness amenity to lift projected occupancy by additional 1.2%",
    )
    assert r.clears_threshold is False
    assert r.shortfall_pct == 1.2


def test_occupancy_lift_round_trip():
    r = OccupancyLiftResult(
        target_lift_pct=1.5, projected_lift_pct=1.8, clears_threshold=True,
    )
    assert OccupancyLiftResult.model_validate(r.model_dump()) == r


def test_occupancy_lift_rejects_negative_target():
    with pytest.raises(ValidationError):
        OccupancyLiftResult(
            target_lift_pct=-0.5,
            projected_lift_pct=0.0,
            clears_threshold=False,
        )


def test_rent_premium_clears_threshold():
    r = RentPremiumResult(
        target_premium_monthly=25.0,
        projected_premium_monthly=30.0,
        clears_threshold=True,
    )
    assert r.clears_threshold is True
    assert r.annual_premium_per_unit == 360.0


def test_rent_premium_fails_with_path_to_pass():
    r = RentPremiumResult(
        target_premium_monthly=50.0,
        projected_premium_monthly=20.0,
        clears_threshold=False,
        shortfall_monthly=30.0,
        path_to_pass="Pair amenity with finish-tier upgrade to reach target premium",
    )
    assert r.shortfall_monthly == 30.0
    assert r.annual_premium_per_unit == 240.0


def test_rent_premium_round_trip():
    r = RentPremiumResult(
        target_premium_monthly=25.0,
        projected_premium_monthly=30.0,
        clears_threshold=True,
    )
    assert RentPremiumResult.model_validate(r.model_dump()) == r


# --- Negative-rejection tests for ge=0 fields ---

def test_occupancy_lift_rejects_negative_projected():
    with pytest.raises(ValidationError):
        OccupancyLiftResult(
            target_lift_pct=1.5,
            projected_lift_pct=-0.1,
            clears_threshold=False,
        )


def test_rent_premium_rejects_negative_target_premium():
    with pytest.raises(ValidationError):
        RentPremiumResult(
            target_premium_monthly=-10.0,
            projected_premium_monthly=0.0,
            clears_threshold=False,
        )


def test_rent_premium_rejects_negative_projected_premium():
    with pytest.raises(ValidationError):
        RentPremiumResult(
            target_premium_monthly=25.0,
            projected_premium_monthly=-5.0,
            clears_threshold=False,
        )
