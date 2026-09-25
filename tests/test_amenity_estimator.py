"""Unit tests for the pure amenity estimator (KB-only; no DB)."""
import pytest

from plat_costmodel.amenity_estimator import estimate_amenity
from plat_costmodel.schemas import AmenityCohort, OccupancyLiftResult, RentPremiumResult


def _kb_minimal() -> dict:
    return {
        "amenity_catalog": {
            "pool": {
                "install_low": 80000,
                "install_high": 150000,
                "annual_opex_low": 8000,
                "annual_opex_high": 15000,
                "typical_occupancy_lift_pct": 1.5,
            },
            "ev_chargers": {
                "install_low": 4000,
                "install_high": 8000,
                "annual_opex_low": 200,
                "annual_opex_high": 500,
                "typical_rent_premium_monthly": 25,
            },
            "package_room": {
                "install_low": 3000,
                "install_high": 8000,
                # no rent_premium, no occupancy_lift in KB — gates absent
            },
        }
    }


def test_estimate_amenity_pool_single_unit():
    cohort = AmenityCohort(amenity_type="pool")
    result = estimate_amenity(cohort, _kb_minimal())
    assert result["install_cost_low"] == 80000
    assert result["install_cost_high"] == 150000
    assert result["annual_opex_low"] == 8000
    assert result["annual_opex_high"] == 15000


def test_estimate_amenity_ev_chargers_quantity_multiplies_costs():
    cohort = AmenityCohort(amenity_type="ev_chargers", quantity=4)
    result = estimate_amenity(cohort, _kb_minimal())
    assert result["install_cost_low"] == 4000 * 4
    assert result["install_cost_high"] == 8000 * 4
    assert result["annual_opex_low"] == 200 * 4
    assert result["annual_opex_high"] == 500 * 4


def test_estimate_amenity_unknown_type_raises_validation_error():
    cohort = AmenityCohort(amenity_type="moonbase")
    with pytest.raises(ValueError) as exc:
        estimate_amenity(cohort, _kb_minimal())
    assert "moonbase" in str(exc.value)


def test_estimate_amenity_occupancy_lift_gate_clears_when_kb_meets_target():
    cohort = AmenityCohort(amenity_type="pool", expected_occupancy_lift_pct=1.0)
    result = estimate_amenity(cohort, _kb_minimal())
    lift = result["expected_occupancy_lift_result"]
    assert isinstance(lift, OccupancyLiftResult)
    assert lift.target_lift_pct == 1.0
    assert lift.projected_lift_pct == 1.5
    assert lift.clears_threshold is True


def test_estimate_amenity_occupancy_lift_gate_fails_with_shortfall():
    cohort = AmenityCohort(amenity_type="pool", expected_occupancy_lift_pct=2.0)
    result = estimate_amenity(cohort, _kb_minimal())
    lift = result["expected_occupancy_lift_result"]
    assert lift.clears_threshold is False
    assert lift.shortfall_pct == pytest.approx(0.5)


def test_estimate_amenity_lift_quantity_does_NOT_multiply_lift():
    """typical_occupancy_lift_pct is per-installation; saturation effect."""
    cohort = AmenityCohort(amenity_type="pool", quantity=2,
                           expected_occupancy_lift_pct=1.0)
    result = estimate_amenity(cohort, _kb_minimal())
    assert result["expected_occupancy_lift_result"].projected_lift_pct == 1.5


def test_estimate_amenity_rent_premium_gate_clears():
    """ev_chargers typical=25/mo. quantity=4 → projected=100/mo."""
    cohort = AmenityCohort(amenity_type="ev_chargers", quantity=4,
                           expected_rent_premium_monthly=80)
    result = estimate_amenity(cohort, _kb_minimal())
    premium = result["expected_rent_premium_result"]
    assert isinstance(premium, RentPremiumResult)
    assert premium.target_premium_monthly == 80
    assert premium.projected_premium_monthly == 100
    assert premium.clears_threshold is True
    # annual_premium_per_unit is computed: projected * 12 = 1200
    assert premium.annual_premium_per_unit == 1200


def test_estimate_amenity_rent_premium_quantity_DOES_multiply():
    cohort_q1 = AmenityCohort(amenity_type="ev_chargers", quantity=1,
                              expected_rent_premium_monthly=20)
    cohort_q4 = AmenityCohort(amenity_type="ev_chargers", quantity=4,
                              expected_rent_premium_monthly=80)
    r1 = estimate_amenity(cohort_q1, _kb_minimal())
    r4 = estimate_amenity(cohort_q4, _kb_minimal())
    assert r1["expected_rent_premium_result"].projected_premium_monthly == 25
    assert r4["expected_rent_premium_result"].projected_premium_monthly == 100


def test_estimate_amenity_no_target_no_gate():
    cohort = AmenityCohort(amenity_type="pool")
    result = estimate_amenity(cohort, _kb_minimal())
    assert result["expected_occupancy_lift_result"] is None
    assert result["expected_rent_premium_result"] is None


def test_estimate_amenity_target_set_but_kb_missing_typical_no_gate():
    """package_room has no typical_rent_premium_monthly in KB."""
    cohort = AmenityCohort(amenity_type="package_room",
                           expected_rent_premium_monthly=20)
    result = estimate_amenity(cohort, _kb_minimal())
    assert result["expected_rent_premium_result"] is None


def test_estimate_amenity_deluxe_flag_currently_no_op():
    """deluxe documented but no pricing effect until KB encodes deluxe tiers."""
    base = AmenityCohort(amenity_type="pool")
    deluxe = AmenityCohort(amenity_type="pool", deluxe=True)
    r_base = estimate_amenity(base, _kb_minimal())
    r_deluxe = estimate_amenity(deluxe, _kb_minimal())
    assert r_base["install_cost_high"] == r_deluxe["install_cost_high"]
