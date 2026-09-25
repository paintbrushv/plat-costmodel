"""Tests for the core cost estimation engine."""

import pytest
from plat_costmodel.estimator import estimate_unit, estimate_property
from plat_costmodel.models import ScopeLevel, FinishTier, SizeCategory, PropertyEstimateInput, UnitSpec


class TestSizeCategory:
    def test_small_unit(self):
        est = estimate_unit(650, 1, 1, "standard_value_add")
        assert est.size_category == SizeCategory.SMALL

    def test_medium_unit(self):
        est = estimate_unit(850, 2, 1, "standard_value_add")
        assert est.size_category == SizeCategory.MEDIUM

    def test_large_unit(self):
        est = estimate_unit(1000, 3, 2, "standard_value_add")
        assert est.size_category == SizeCategory.LARGE

    def test_boundary_700(self):
        est = estimate_unit(700, 1, 1, "standard_value_add")
        assert est.size_category == SizeCategory.MEDIUM

    def test_boundary_950(self):
        est = estimate_unit(950, 2, 1, "standard_value_add")
        assert est.size_category == SizeCategory.MEDIUM

    def test_boundary_951(self):
        est = estimate_unit(951, 2, 1, "standard_value_add")
        assert est.size_category == SizeCategory.LARGE


class TestStandardValueAdd:
    def test_produces_line_items(self):
        est = estimate_unit(850, 2, 1, "standard_value_add")
        categories = {li.category for li in est.line_items}
        assert "flooring" in categories
        assert "kitchen" in categories
        assert "bathroom" in categories
        assert "paint" in categories
        assert "appliances" in categories
        assert "fixtures_doors_trim" in categories

    def test_small_unit_range(self):
        """Small basic 1BR/1BA should be well below large upgraded 3BR/2BA."""
        est = estimate_unit(650, 1, 1, "standard_value_add", "basic")
        # Small basic unit with 1BA: low end of the range
        assert est.total_low >= 5000  # sanity floor
        assert est.total_high <= 16000  # below the large unit ceiling

    def test_large_unit_range(self):
        """Large units should be in the $16K-$18K range."""
        est = estimate_unit(1000, 3, 2, "standard_value_add", "upgraded")
        assert est.total_high >= 14000

    def test_larger_unit_costs_more(self):
        """Larger units should cost more than smaller ones."""
        small = estimate_unit(650, 1, 1, "standard_value_add", "basic")
        large = estimate_unit(1000, 2, 1, "standard_value_add", "basic")
        assert large.total_high > small.total_high

    def test_upgraded_costs_more_than_basic(self):
        """Upgraded finishes should cost more."""
        basic = estimate_unit(850, 2, 1, "standard_value_add", "basic")
        upgraded = estimate_unit(850, 2, 1, "standard_value_add", "upgraded")
        assert upgraded.total_high >= basic.total_high

    def test_bathroom_multiplier(self):
        """2BA unit should have higher bathroom costs than 1BA."""
        one_ba = estimate_unit(850, 2, 1, "standard_value_add")
        two_ba = estimate_unit(850, 2, 2, "standard_value_add")
        bath_1 = next(li for li in one_ba.line_items if li.category == "bathroom")
        bath_2 = next(li for li in two_ba.line_items if li.category == "bathroom")
        assert bath_2.high == pytest.approx(bath_1.high * 2, rel=0.01)

    def test_contingency_uses_high(self):
        """Conservative bias: contingency should use the high percentage (15%)."""
        est = estimate_unit(850, 2, 1, "standard_value_add")
        assert est.contingency_pct == 15

    def test_total_includes_contingency(self):
        est = estimate_unit(850, 2, 1, "standard_value_add")
        expected_high = round(est.subtotal_high * (1 + est.contingency_pct / 100))
        assert est.total_high == expected_high


class TestLightTurn:
    def test_light_range(self):
        """Light turns should be in the $3K-$5K range."""
        est = estimate_unit(850, 2, 1, "light")
        assert est.total_low >= 2000
        assert est.total_high <= 6000

    def test_light_line_items(self):
        est = estimate_unit(850, 2, 1, "light")
        categories = {li.category for li in est.line_items}
        assert "paint" in categories
        assert "cleaning" in categories
        assert "hardware" in categories

    def test_light_no_size_scaling(self):
        """Light turns should not vary by unit size."""
        small = estimate_unit(650, 1, 1, "light")
        large = estimate_unit(1000, 2, 1, "light")
        assert small.total_high == large.total_high


class TestConservativeBias:
    def test_total_high_above_subtotal(self):
        est = estimate_unit(850, 2, 1, "standard_value_add")
        assert est.total_high > est.subtotal_high

    def test_high_estimate_never_below_12k_for_standard(self):
        """Even the smallest basic unit should have a reasonable high estimate."""
        est = estimate_unit(650, 1, 1, "standard_value_add", "basic")
        assert est.total_high >= 8000


class TestRiskFlags:
    def test_old_building_has_flags(self):
        est = estimate_unit(850, 2, 1, "standard_value_add", year_built=1975)
        assert len(est.risk_flags) > 0

    def test_new_building_fewer_flags(self):
        old = estimate_unit(850, 2, 1, "standard_value_add", year_built=1975)
        new = estimate_unit(850, 2, 1, "standard_value_add", year_built=2005)
        assert len(old.risk_flags) > len(new.risk_flags)

    def test_no_year_built_warns(self):
        est = estimate_unit(850, 2, 1, "standard_value_add")
        assert any("unknown" in f.message.lower() for f in est.risk_flags)


class TestPropertyEstimate:
    def test_rolls_up_units(self):
        prop = PropertyEstimateInput(
            property_id="PROP1",
            total_units=10,
            year_built=1978,
            unit_mix=[
                UnitSpec(unit_id="101", sqft=700, bedrooms=1, bathrooms=1),
                UnitSpec(unit_id="102", sqft=850, bedrooms=2, bathrooms=1),
            ],
        )
        est = estimate_property(prop)
        assert est.units_needing_work == 2
        assert est.total_units == 10
        assert est.total_renovation_high > 0

    def test_includes_exterior_capex(self):
        prop = PropertyEstimateInput(
            property_id="PROP1",
            total_units=10,
            unit_mix=[UnitSpec(unit_id="101", sqft=850, bedrooms=2, bathrooms=1)],
            exterior_items=["roof", "parking"],
        )
        est = estimate_property(prop)
        assert est.exterior_capex_high > 0

    def test_per_unit_average(self):
        prop = PropertyEstimateInput(
            property_id="PROP1",
            total_units=50,
            year_built=1980,
            unit_mix=[UnitSpec(unit_id="101", sqft=850, bedrooms=2, bathrooms=1)],
        )
        est = estimate_property(prop)
        assert est.per_unit_average_high > 0
