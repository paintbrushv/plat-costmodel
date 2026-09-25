"""Unit tests for the pure exterior estimator (KB-only; no DB)."""
import pytest

from plat_costmodel.exterior_estimator import estimate_exterior
from plat_costmodel.schemas import ExteriorCohort


def _kb_minimal() -> dict:
    return {
        "exterior_capex": {
            "items": {
                "roof": {"per_unit_low": 1000, "per_unit_high": 1500},
                "siding_paint": {"per_unit_low": 1000, "per_unit_high": 2000},
            },
        }
    }


def test_estimate_exterior_single_item_scales_by_total_units():
    cohort = ExteriorCohort(items=["roof"], total_units=100)
    result = estimate_exterior(cohort, _kb_minimal())
    assert result["total_low"] == 100 * 1000
    assert result["total_high"] == 100 * 1500
    assert result["per_unit_low"] == 1000
    assert result["per_unit_high"] == 1500
    assert len(result["line_items"]) == 1
    assert result["line_items"][0].category == "roof"
    assert result["line_items"][0].low == 100_000
    assert result["line_items"][0].high == 150_000


def test_estimate_exterior_multiple_items_sum_per_category():
    cohort = ExteriorCohort(items=["roof", "siding_paint"], total_units=50)
    result = estimate_exterior(cohort, _kb_minimal())
    assert result["total_low"] == 50 * (1000 + 1000)
    assert result["total_high"] == 50 * (1500 + 2000)
    assert {li.category for li in result["line_items"]} == {"roof", "siding_paint"}


def test_estimate_exterior_unknown_item_raises_validation_error():
    cohort = ExteriorCohort(items=["mystery_item"], total_units=10)
    with pytest.raises(ValueError) as exc:
        estimate_exterior(cohort, _kb_minimal())
    assert "mystery_item" in str(exc.value)


def test_estimate_exterior_payback_is_none_for_now():
    """Payback computation lands in a follow-up; placeholder must be None."""
    cohort = ExteriorCohort(items=["roof"], total_units=10)
    result = estimate_exterior(cohort, _kb_minimal())
    assert result["payback_years_estimated"] is None
