"""Tests for interior/exterior per-unit-average denominator split.

Per Wave 2 Bug 2.6 fix: ``per_unit_average_high`` was mixing two
denominators — interior cost (which only touches units_needing_work) was
being divided by total_units (which includes the whole property). The fix
splits the field into:

  * ``interior_per_unit_average_*`` (denominator = units_needing_work)
  * ``exterior_per_unit_average_*`` (denominator = total_units, since
    exterior CapEx — roof, parking, landscape — covers all units)

The legacy ``per_unit_average_*`` fields are preserved for backwards-compat.
"""

from __future__ import annotations

from plat_costmodel.estimator import estimate_property
from plat_costmodel.models import (
    FinishTier,
    PropertyEstimateInput,
    PropertyClass,
    ScopeLevel,
    UnitSpec,
)


def _audited_like(units_needing_work: int, total_units: int) -> PropertyEstimateInput:
    """Build a Audited-shaped Property (179 cohorted units of 296 total).

    By default the audit's pattern: total_units=296, units_needing_work=179.
    Single uniform unit_mix (850sf 2BR/1BA) for clean math.
    """
    return PropertyEstimateInput(
        property_id="AUDITED_LIKE",
        year_built=1982,
        property_class=PropertyClass.C,
        market="midland",
        total_units=total_units,
        unit_mix=[
            UnitSpec(
                sqft=850, bedrooms=2, bathrooms=1, count=units_needing_work,
                scope_level=ScopeLevel.STANDARD_VALUE_ADD,
                finish_tier=FinishTier.BASIC,
            ),
        ],
        exterior_items=["roof", "parking"],
    )


class TestInteriorExteriorDenominators:
    def test_interior_per_unit_uses_units_needing_work_denominator(self):
        """Interior denominator must be units_needing_work (179), NOT total_units (296)."""
        prop = _audited_like(units_needing_work=179, total_units=296)
        result = estimate_property(prop)

        assert result.units_needing_work == 179
        assert result.total_units == 296

        # Interior cost = sum of UnitEstimate.total_high across 179 units.
        total_interior_high = sum(e.total_high for e in result.unit_estimates)
        expected_interior_per_unit = round(total_interior_high / 179)
        assert result.interior_per_unit_average_high == expected_interior_per_unit

        # Sanity bound: interior on a 850sf medium standard_value_add basic
        # is ~$13K-$17K/unit. NOT what you'd get dividing by 296.
        wrong_denom_per_unit = round(total_interior_high / 296)
        assert result.interior_per_unit_average_high != wrong_denom_per_unit

    def test_exterior_per_unit_uses_total_units_denominator(self):
        """Exterior denominator must be total_units (296), NOT units_needing_work."""
        prop = _audited_like(units_needing_work=179, total_units=296)
        result = estimate_property(prop)

        ext_high = result.exterior_capex_high
        assert ext_high > 0  # roof+parking definitely > 0
        expected_exterior_per_unit = round(ext_high / 296)
        assert result.exterior_per_unit_average_high == expected_exterior_per_unit

        # Sanity: dividing by units_needing_work would inflate it.
        wrong_denom_per_unit = round(ext_high / 179)
        # If by coincidence the denominators are equal we'd get the same
        # value, but on this 179-vs-296 fixture they must differ.
        assert result.exterior_per_unit_average_high != wrong_denom_per_unit

    def test_interior_low_uses_units_needing_work(self):
        prop = _audited_like(units_needing_work=179, total_units=296)
        result = estimate_property(prop)
        total_interior_low = sum(e.total_low for e in result.unit_estimates)
        assert result.interior_per_unit_average_low == round(total_interior_low / 179)

    def test_exterior_low_uses_total_units(self):
        prop = _audited_like(units_needing_work=179, total_units=296)
        result = estimate_property(prop)
        assert result.exterior_per_unit_average_low == round(
            result.exterior_capex_low / 296
        )

    def test_legacy_per_unit_average_preserved(self):
        """Backwards-compat: ``per_unit_average_high`` still divides total by total_units."""
        prop = _audited_like(units_needing_work=179, total_units=296)
        result = estimate_property(prop)
        expected_legacy = round(result.total_renovation_high / 296)
        assert result.per_unit_average_high == expected_legacy

    def test_full_property_no_renovation_skip(self):
        """When units_needing_work == total_units, both denominators equal."""
        prop = _audited_like(units_needing_work=50, total_units=50)
        result = estimate_property(prop)
        assert result.interior_per_unit_average_high == round(
            sum(e.total_high for e in result.unit_estimates) / 50
        )
        assert result.exterior_per_unit_average_high == round(
            result.exterior_capex_high / 50
        )

    def test_zero_units_needing_work_safe(self):
        """No units in mix → interior denominator is 0; must not divide by zero."""
        prop = PropertyEstimateInput(
            property_id="EMPTY",
            year_built=1985,
            property_class=PropertyClass.C,
            total_units=10,
            unit_mix=[],
            exterior_items=["roof"],
        )
        result = estimate_property(prop)
        assert result.units_needing_work == 0
        # Defensive: must not raise; 0 is acceptable.
        assert result.interior_per_unit_average_high == 0
        # Exterior still divides by total_units=10
        assert result.exterior_per_unit_average_high == round(
            result.exterior_capex_high / 10
        )
