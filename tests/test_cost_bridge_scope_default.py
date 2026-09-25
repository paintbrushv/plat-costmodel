"""Tests for vintage/class scope-level defaulting (Wave 2 Bug 2.2 fix).

Per the Wave 2 fix-plan + user Q4 answer:
  - Vintage <= 1990 + property_class C → default to standard_value_add
    (NOT light, which would silently produce a flat $3,850/unit).
  - Explicit scope_level=light on a vintage 1980s class-C property is
    respected but tagged with a sanity_flag for downstream review.
  - Newer vintage / non-class-C: explicit scope_level is respected silently.
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


def _build_property(
    *,
    year_built: int,
    property_class: PropertyClass | None,
    scope_level: ScopeLevel | None = None,
) -> PropertyEstimateInput:
    """Build a single-unit Property for scope-resolution testing."""
    if scope_level is None:
        spec = UnitSpec(unit_id="U001", sqft=850, bedrooms=2, bathrooms=1)
    else:
        spec = UnitSpec(
            unit_id="U001", sqft=850, bedrooms=2, bathrooms=1,
            scope_level=scope_level, finish_tier=FinishTier.BASIC,
        )
    return PropertyEstimateInput(
        property_id="TEST_PROP",
        year_built=year_built,
        property_class=property_class,
        market="dallas",
        total_units=10,
        unit_mix=[spec],
    )


class TestVintageClassScopeDefault:
    def test_vintage_1982_class_c_default_to_standard(self):
        """1982 + class C with no explicit scope → resolved scope = standard_value_add.

        The full standard_value_add cost should land in the $10K-$18K range
        (size-scaled), NOT the degenerate $3,850/unit flat light branch.
        """
        prop = _build_property(year_built=1982, property_class=PropertyClass.C)
        result = estimate_property(prop)

        assert len(result.unit_estimates) == 1
        est = result.unit_estimates[0]
        assert est.scope_level == ScopeLevel.STANDARD_VALUE_ADD
        # standard_value_add basic-tier on an 850sf 2BR/1BA medium unit
        # should land in $10K-$18K, never the light flat $3,850.
        assert 10_000 <= est.total_high <= 18_000
        assert est.total_high != 3850
        # No anomaly tag — default fired correctly, no light scope chosen.
        assert result.sanity_flags == []

    def test_vintage_2015_class_a_default_to_light(self):
        """A modern non-class-C property with explicit light scope is respected.

        property_class enum carries B and C only; "class A" (non-value-add) is
        modeled here as property_class=None. Explicit scope_level=light should
        produce the light branch and emit NO sanity_flag — current behavior
        preserved for non-value-add deals.
        """
        prop = _build_property(
            year_built=2015,
            property_class=None,
            scope_level=ScopeLevel.LIGHT,
        )
        result = estimate_property(prop)

        assert len(result.unit_estimates) == 1
        est = result.unit_estimates[0]
        assert est.scope_level == ScopeLevel.LIGHT
        # Light scope produces the small flat ~$3K-$5K range
        assert 3_000 <= est.total_high <= 5_500
        # No anomaly tag because property is not a value-add target.
        assert result.sanity_flags == []

    def test_explicit_light_scope_overridden_on_vintage_class_c(self):
        """Explicit scope_level=light on 1982 class-C is OVERRIDDEN to
        standard_value_add per conservative-bias policy (CLAUDE.md:
        "underestimating renovation costs is far worse than overestimating").

        This is the exact failure mode of Stage 2 audit Bug 2.2: the
        cost-bridge-analyst was passing scope_level=light explicitly on the
        1982 class-C audited property, producing a flat $3,850/unit cost
        that masked ROI failures. The override forces standard_value_add and
        emits a sanity_flag so downstream consumers see what happened.
        """
        prop = _build_property(
            year_built=1982,
            property_class=PropertyClass.C,
            scope_level=ScopeLevel.LIGHT,
        )
        result = estimate_property(prop)

        assert len(result.unit_estimates) == 1
        est = result.unit_estimates[0]
        # Explicit light is OVERRIDDEN to standard_value_add (the Bug 2.2 fix).
        assert est.scope_level == ScopeLevel.STANDARD_VALUE_ADD
        # Cost reflects standard_value_add ($12K-$18K for typical sqft), not
        # the buggy $3,850 light flat.
        assert est.total_high > 5_000, (
            f"Expected standard_value_add cost > $5K, got ${est.total_high:.0f}. "
            f"If this is ~$3,850, the override is dead code again."
        )
        # Sanity flag with the new stable identifier.
        assert len(result.sanity_flags) == 1
        flag = result.sanity_flags[0]
        assert flag.startswith("vintage_class_light_scope_overridden")
        assert "U001" in flag
        assert "1982" in flag
        assert "overridden to" in flag.lower()

    def test_vintage_1980_class_c_no_explicit_scope_skips_light_branch(self):
        """Boundary check: year_built=1980 (definitely <=1990) + class C with
        no explicit scope must NOT land on the $3,850 flat light branch.
        """
        prop = _build_property(year_built=1980, property_class=PropertyClass.C)
        result = estimate_property(prop)
        est = result.unit_estimates[0]
        assert est.scope_level == ScopeLevel.STANDARD_VALUE_ADD
        assert est.total_high > 5_000  # never light flat

    def test_vintage_1990_boundary_class_c(self):
        """year_built=1990 is the inclusive boundary; class C → standard_value_add."""
        prop = _build_property(year_built=1990, property_class=PropertyClass.C)
        result = estimate_property(prop)
        est = result.unit_estimates[0]
        assert est.scope_level == ScopeLevel.STANDARD_VALUE_ADD

    def test_vintage_1991_class_c_no_anomaly_on_light(self):
        """Just past the vintage cutoff (1991), class C + explicit light → no flag."""
        prop = _build_property(
            year_built=1991, property_class=PropertyClass.C,
            scope_level=ScopeLevel.LIGHT,
        )
        result = estimate_property(prop)
        assert result.sanity_flags == []
