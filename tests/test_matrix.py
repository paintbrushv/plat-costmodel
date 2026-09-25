"""Tests for the cost range data matrix module (matrix.py)."""

from unittest.mock import patch

import pytest
from plat_costmodel.matrix import (
    CostRange,
    _load_matrix,
    lookup_range,
    get_per_bathroom_increment,
    validate_estimate_against_matrix,
    get_matrix_summary,
)
from plat_costmodel.models import ScopeLevel, SizeCategory, FinishTier


# ---------------------------------------------------------------------------
# CostRange dataclass tests
# ---------------------------------------------------------------------------

class TestCostRange:
    def test_basic_construction(self):
        r = CostRange(low=5000, high=10000)
        assert r.low == 5000
        assert r.high == 10000

    def test_high_less_than_low_raises(self):
        with pytest.raises(ValueError, match="high"):
            CostRange(low=10000, high=5000)

    def test_equal_low_high_allowed(self):
        """Edge case: a fixed-price estimate has low == high."""
        r = CostRange(low=8000, high=8000)
        assert r.low == r.high

    def test_add_bathroom_increment_zero(self):
        base = CostRange(low=9000, high=13000)
        incr = CostRange(low=2300, high=3350)
        result = base.add_bathroom_increment(incr, count=0)
        assert result.low == 9000
        assert result.high == 13000

    def test_add_bathroom_increment_one(self):
        base = CostRange(low=9000, high=13000)
        incr = CostRange(low=2300, high=3350)
        result = base.add_bathroom_increment(incr, count=1)
        assert result.low == 9000 + 2300
        assert result.high == 13000 + 3350

    def test_add_bathroom_increment_two(self):
        base = CostRange(low=9000, high=13000)
        incr = CostRange(low=2300, high=3350)
        result = base.add_bathroom_increment(incr, count=2)
        assert result.low == 9000 + 2 * 2300
        assert result.high == 13000 + 2 * 3350

    def test_add_bathroom_increment_negative_treated_as_zero(self):
        base = CostRange(low=9000, high=13000)
        incr = CostRange(low=2300, high=3350)
        result = base.add_bathroom_increment(incr, count=-1)
        assert result.low == 9000
        assert result.high == 13000

    def test_as_dict(self):
        r = CostRange(low=5000, high=10000, basis="test", typical_unit="1BR/1BA")
        d = r.as_dict()
        assert d["low"] == 5000
        assert d["high"] == 10000
        assert d["basis"] == "test"
        assert d["typical_unit"] == "1BR/1BA"


# ---------------------------------------------------------------------------
# Matrix values — concrete range tests
# ---------------------------------------------------------------------------

class TestLightRanges:
    """Light scope: flat range, no size or finish differentiation."""

    def test_light_range_values(self):
        r = lookup_range("light", "medium", "basic")
        assert r.low == 3300
        assert r.high == 5500

    def test_light_ignores_size_small(self):
        r = lookup_range("light", "small", "basic")
        assert r.low == 3300
        assert r.high == 5500

    def test_light_ignores_size_large(self):
        r = lookup_range("light", "large", "basic")
        assert r.low == 3300
        assert r.high == 5500

    def test_light_ignores_finish_upgraded(self):
        basic = lookup_range("light", "medium", "basic")
        upgraded = lookup_range("light", "medium", "upgraded")
        assert basic.low == upgraded.low
        assert basic.high == upgraded.high

    def test_light_includes_contingency(self):
        """Light range ($3,300-$5,500) must exceed the pre-contingency base ($3,000-$5,000)."""
        r = lookup_range("light", "medium")
        # Knowledge base pre-contingency total_range is 3000-5000; post 10% → 3300-5500
        assert r.low >= 3000
        assert r.high >= 5000

    def test_light_bathrooms_arg_ignored(self):
        """Light turns don't scale by bathroom count."""
        one_ba = lookup_range("light", "medium", bathrooms=1)
        two_ba = lookup_range("light", "medium", bathrooms=2)
        assert one_ba.low == two_ba.low
        assert one_ba.high == two_ba.high


class TestStandardValueAddRanges:
    """Standard value-add: size × finish grid, 6 cells."""

    # --- Small units ---
    def test_small_basic_low_bound(self):
        r = lookup_range("standard_value_add", "small", "basic")
        assert r.low == 7600

    def test_small_basic_high_bound(self):
        r = lookup_range("standard_value_add", "small", "basic")
        assert r.high == 11000

    def test_small_upgraded_low_bound(self):
        r = lookup_range("standard_value_add", "small", "upgraded")
        assert r.low == 9600

    def test_small_upgraded_high_bound(self):
        r = lookup_range("standard_value_add", "small", "upgraded")
        assert r.high == 13000

    # --- Medium units ---
    def test_medium_basic_low_bound(self):
        r = lookup_range("standard_value_add", "medium", "basic")
        assert r.low == 9000

    def test_medium_basic_high_bound(self):
        r = lookup_range("standard_value_add", "medium", "basic")
        assert r.high == 13000

    def test_medium_upgraded_low_bound(self):
        r = lookup_range("standard_value_add", "medium", "upgraded")
        assert r.low == 11500

    def test_medium_upgraded_high_bound(self):
        r = lookup_range("standard_value_add", "medium", "upgraded")
        assert r.high == 15500

    # --- Large units ---
    def test_large_basic_low_bound(self):
        r = lookup_range("standard_value_add", "large", "basic")
        assert r.low == 10300

    def test_large_basic_high_bound(self):
        r = lookup_range("standard_value_add", "large", "basic")
        assert r.high == 15000

    def test_large_upgraded_low_bound(self):
        r = lookup_range("standard_value_add", "large", "upgraded")
        assert r.low == 13000

    def test_large_upgraded_high_bound(self):
        r = lookup_range("standard_value_add", "large", "upgraded")
        assert r.high == 17500


class TestRangeMonotonicity:
    """Conservative bias: ranges must be internally consistent."""

    def test_high_always_exceeds_low(self):
        """Every cell: high > low."""
        for scope in ScopeLevel:
            for size in SizeCategory:
                for finish in FinishTier:
                    r = lookup_range(scope, size, finish)
                    assert r.high > r.low, (
                        f"{scope.value}/{size.value}/{finish.value}: "
                        f"high={r.high} not > low={r.low}"
                    )

    def test_larger_units_cost_more_basic(self):
        """Size monotonicity: small < medium < large (basic finish)."""
        small = lookup_range("standard_value_add", "small", "basic")
        medium = lookup_range("standard_value_add", "medium", "basic")
        large = lookup_range("standard_value_add", "large", "basic")
        assert medium.high > small.high, "Medium high should exceed small high"
        assert large.high > medium.high, "Large high should exceed medium high"
        assert medium.low > small.low, "Medium low should exceed small low"
        assert large.low > medium.low, "Large low should exceed medium low"

    def test_larger_units_cost_more_upgraded(self):
        """Size monotonicity: small < medium < large (upgraded finish)."""
        small = lookup_range("standard_value_add", "small", "upgraded")
        medium = lookup_range("standard_value_add", "medium", "upgraded")
        large = lookup_range("standard_value_add", "large", "upgraded")
        assert medium.high > small.high
        assert large.high > medium.high

    def test_upgraded_costs_more_than_basic(self):
        """Finish monotonicity: upgraded high > basic high for every size."""
        for size in SizeCategory:
            basic = lookup_range("standard_value_add", size, "basic")
            upgraded = lookup_range("standard_value_add", size, "upgraded")
            assert upgraded.high > basic.high, (
                f"Size {size.value}: upgraded high={upgraded.high} not > basic high={basic.high}"
            )
            assert upgraded.low > basic.low, (
                f"Size {size.value}: upgraded low={upgraded.low} not > basic low={basic.low}"
            )

    def test_standard_value_add_always_more_than_light(self):
        """Any standard_value_add estimate should cost more than a light turn."""
        light = lookup_range("light", "medium")
        for size in SizeCategory:
            for finish in FinishTier:
                sva = lookup_range("standard_value_add", size, finish)
                assert sva.low > light.low, (
                    f"SVA {size.value}/{finish.value} low={sva.low} not > light low={light.low}"
                )


class TestPerBathroomIncrement:
    """Validate per-bathroom increment table values and monotonicity."""

    def test_medium_basic_increment(self):
        incr = get_per_bathroom_increment("medium", "basic")
        assert incr.low == 2300
        assert incr.high == 3350

    def test_medium_upgraded_increment(self):
        incr = get_per_bathroom_increment("medium", "upgraded")
        assert incr.low == 3000
        assert incr.high == 4025

    def test_small_basic_increment(self):
        incr = get_per_bathroom_increment("small", "basic")
        assert incr.low == 2000
        assert incr.high == 2850

    def test_large_upgraded_increment(self):
        incr = get_per_bathroom_increment("large", "upgraded")
        assert incr.low == 3450
        assert incr.high == 4625

    def test_increment_high_always_exceeds_low(self):
        for size in SizeCategory:
            for finish in FinishTier:
                incr = get_per_bathroom_increment(size, finish)
                assert incr.high > incr.low, (
                    f"Increment {size.value}/{finish.value}: high={incr.high} not > low={incr.low}"
                )

    def test_larger_size_higher_increment(self):
        """Per-bathroom increment should scale up with unit size."""
        for finish in FinishTier:
            small_incr = get_per_bathroom_increment("small", finish)
            medium_incr = get_per_bathroom_increment("medium", finish)
            large_incr = get_per_bathroom_increment("large", finish)
            assert medium_incr.high > small_incr.high, f"finish={finish.value}"
            assert large_incr.high > medium_incr.high, f"finish={finish.value}"

    def test_upgraded_increment_higher_than_basic(self):
        """Upgraded bathroom increment should exceed basic for every size."""
        for size in SizeCategory:
            basic_incr = get_per_bathroom_increment(size, "basic")
            upgraded_incr = get_per_bathroom_increment(size, "upgraded")
            assert upgraded_incr.high > basic_incr.high, f"size={size.value}"

    def test_two_bathroom_unit_higher_than_one_bathroom(self):
        """2BA unit range should exceed 1BA unit range by exactly one increment."""
        one_ba = lookup_range("standard_value_add", "medium", "basic", bathrooms=1)
        two_ba = lookup_range("standard_value_add", "medium", "basic", bathrooms=2)
        incr = get_per_bathroom_increment("medium", "basic")
        assert two_ba.low == one_ba.low + incr.low
        assert two_ba.high == one_ba.high + incr.high

    def test_three_bathroom_unit(self):
        """3BA unit should add two increments."""
        one_ba = lookup_range("standard_value_add", "medium", "basic", bathrooms=1)
        three_ba = lookup_range("standard_value_add", "medium", "basic", bathrooms=3)
        incr = get_per_bathroom_increment("medium", "basic")
        assert three_ba.low == one_ba.low + 2 * incr.low
        assert three_ba.high == one_ba.high + 2 * incr.high

    def test_bathrooms_below_one_treated_as_one(self):
        """Bathroom count of 0 or negative should not reduce the range."""
        one_ba = lookup_range("standard_value_add", "medium", "basic", bathrooms=1)
        zero_ba = lookup_range("standard_value_add", "medium", "basic", bathrooms=0)
        neg_ba = lookup_range("standard_value_add", "medium", "basic", bathrooms=-1)
        assert zero_ba.low == one_ba.low
        assert neg_ba.high == one_ba.high


# ---------------------------------------------------------------------------
# Enum / string input acceptance
# ---------------------------------------------------------------------------

class TestInputFlexibility:
    """lookup_range should accept both string and enum inputs."""

    def test_string_scope(self):
        r = lookup_range("standard_value_add", "medium", "basic")
        assert r.high > 0

    def test_enum_scope(self):
        r = lookup_range(ScopeLevel.STANDARD_VALUE_ADD, SizeCategory.MEDIUM, FinishTier.BASIC)
        assert r.high > 0

    def test_mixed_inputs(self):
        r1 = lookup_range("standard_value_add", SizeCategory.MEDIUM, "basic")
        r2 = lookup_range(ScopeLevel.STANDARD_VALUE_ADD, "medium", FinishTier.BASIC)
        assert r1.low == r2.low
        assert r1.high == r2.high

    def test_invalid_scope_raises(self):
        with pytest.raises(ValueError):
            lookup_range("gut_renovation", "medium", "basic")

    def test_invalid_size_raises(self):
        with pytest.raises(ValueError):
            lookup_range("standard_value_add", "jumbo", "basic")

    def test_invalid_finish_raises(self):
        with pytest.raises(ValueError):
            lookup_range("standard_value_add", "medium", "luxury")


# ---------------------------------------------------------------------------
# Estimate validation against matrix
# ---------------------------------------------------------------------------

class TestValidateEstimateAgainstMatrix:
    """validate_estimate_against_matrix sanity check utility."""

    def test_on_target_estimate_passes(self):
        """An estimate at matrix_high should be within range."""
        result = validate_estimate_against_matrix(
            total_high=13000,
            scope="standard_value_add",
            size="medium",
            finish="basic",
        )
        assert result["within_range"] is True
        assert result["matrix_low"] == 9000
        assert result["matrix_high"] == 13000
        assert "within" in result["note"].lower()

    def test_way_under_estimate_flagged(self):
        """An estimate far below matrix should be flagged as under-range."""
        result = validate_estimate_against_matrix(
            total_high=3000,
            scope="standard_value_add",
            size="medium",
            finish="basic",
        )
        assert result["within_range"] is False
        assert "UNDER-RANGE" in result["note"]

    def test_way_over_estimate_flagged(self):
        """An estimate far above matrix should be flagged as over-range."""
        result = validate_estimate_against_matrix(
            total_high=30000,
            scope="standard_value_add",
            size="medium",
            finish="basic",
        )
        assert result["within_range"] is False
        assert "OVER-RANGE" in result["note"]

    def test_deviation_pct_positive_when_over(self):
        result = validate_estimate_against_matrix(
            total_high=20000,
            scope="standard_value_add",
            size="medium",
            finish="basic",
        )
        assert result["deviation_pct"] > 0

    def test_deviation_pct_negative_when_under(self):
        result = validate_estimate_against_matrix(
            total_high=5000,
            scope="standard_value_add",
            size="medium",
            finish="basic",
        )
        assert result["deviation_pct"] < 0

    def test_light_scope_validation(self):
        result = validate_estimate_against_matrix(
            total_high=5500,
            scope="light",
            size="medium",
            finish="basic",
        )
        assert result["within_range"] is True

    def test_result_contains_required_keys(self):
        result = validate_estimate_against_matrix(13000, "standard_value_add", "medium")
        required = {"within_range", "matrix_low", "matrix_high", "total_high", "deviation_pct", "note"}
        assert required.issubset(result.keys())

    def test_custom_tolerance(self):
        """With a tight 5% tolerance, a 10% deviation should fail."""
        result = validate_estimate_against_matrix(
            total_high=14400,  # ~10.8% above matrix_high of 13000
            scope="standard_value_add",
            size="medium",
            finish="basic",
            tolerance_pct=5.0,
        )
        assert result["within_range"] is False


# ---------------------------------------------------------------------------
# Matrix summary
# ---------------------------------------------------------------------------

class TestGetMatrixSummary:
    def test_summary_has_light(self):
        summary = get_matrix_summary()
        assert summary.light is not None
        assert summary.light.low == 3300
        assert summary.light.high == 5500

    def test_summary_covers_all_size_finish_combos(self):
        summary = get_matrix_summary()
        for size in SizeCategory:
            assert size.value in summary.standard_value_add
            for finish in FinishTier:
                assert finish.value in summary.standard_value_add[size.value]
                r = summary.standard_value_add[size.value][finish.value]
                assert isinstance(r, CostRange)
                assert r.high > r.low

    def test_summary_covers_all_bathroom_increments(self):
        summary = get_matrix_summary()
        for size in SizeCategory:
            assert size.value in summary.per_bathroom_increment
            for finish in FinishTier:
                assert finish.value in summary.per_bathroom_increment[size.value]

    def test_summary_meta_present(self):
        summary = get_matrix_summary()
        assert "calibration_status" in summary.meta
        assert summary.meta["calibration_status"] == "seed"

    def test_summary_meta_includes_contingency_pcts(self):
        summary = get_matrix_summary()
        assert "contingency_pct_light" in summary.meta
        assert "contingency_pct_standard_value_add" in summary.meta
        assert summary.meta["contingency_pct_light"] == 10
        assert summary.meta["contingency_pct_standard_value_add"] == 15


# ---------------------------------------------------------------------------
# Conservative bias enforcement
# ---------------------------------------------------------------------------

class TestConservativeBias:
    """The matrix must always err on the high side — key evaluation criterion."""

    def test_all_standard_value_add_highs_within_stated_band(self):
        """All standard_value_add cell highs should be in the $10K-$20K range.

        This is a guard against data entry errors that would create unrealistically
        cheap estimates (which is more dangerous than expensive estimates).
        """
        for size in SizeCategory:
            for finish in FinishTier:
                r = lookup_range("standard_value_add", size, finish)
                assert r.high >= 10000, (
                    f"{size.value}/{finish.value}: high={r.high} is below $10K "
                    f"— likely under-estimated"
                )
                assert r.high <= 20000, (
                    f"{size.value}/{finish.value}: high={r.high} is above $20K "
                    f"— verify this is intentional"
                )

    def test_light_high_matches_stated_ceiling(self):
        """Light scope ceiling should match the stated $3K-$5K + contingency range."""
        r = lookup_range("light", "medium")
        # $5,000 * 1.10 contingency = $5,500 max
        assert r.high <= 6000, "Light scope high should not exceed $6K"

    def test_per_bathroom_increment_is_positive(self):
        """Additional bathrooms must always increase cost (never a discount)."""
        for size in SizeCategory:
            for finish in FinishTier:
                incr = get_per_bathroom_increment(size, finish)
                assert incr.low > 0
                assert incr.high > 0

    def test_large_upgraded_2ba_within_range(self):
        """A large upgraded 2BA unit is a common high-water-mark config."""
        r = lookup_range("standard_value_add", "large", "upgraded", bathrooms=2)
        # Should be meaningfully higher than the 1BA baseline
        one_ba = lookup_range("standard_value_add", "large", "upgraded", bathrooms=1)
        assert r.high > one_ba.high
        # But still in a believable range (< $25K — if higher, audit the data)
        assert r.high < 25000


# ---------------------------------------------------------------------------
# Hardening: total_high=0 in validate (division safety)
# ---------------------------------------------------------------------------

class TestValidateEdgeCases:
    def test_total_high_zero_no_divide_by_zero(self):
        """total_high=0 should not raise ZeroDivisionError."""
        result = validate_estimate_against_matrix(
            total_high=0,
            scope="standard_value_add",
            size="medium",
            finish="basic",
        )
        assert result["within_range"] is False
        assert result["total_high"] == 0
        assert "UNDER-RANGE" in result["note"]

    def test_total_high_negative(self):
        """Negative total_high should be flagged as under-range, not crash."""
        result = validate_estimate_against_matrix(
            total_high=-500,
            scope="standard_value_add",
            size="medium",
            finish="basic",
        )
        assert result["within_range"] is False
        assert result["deviation_pct"] < 0


# ---------------------------------------------------------------------------
# Hardening: missing cost_matrix section in KB
# ---------------------------------------------------------------------------

class TestMissingCostMatrix:
    def test_missing_cost_matrix_raises_descriptive_error(self):
        """If cost_matrix section is absent, error should explain the problem."""
        import tempfile, os
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write("some_other_key:\n  foo: bar\n")
            tmp = f.name
        try:
            with patch("plat_costmodel.matrix._KB_PATH", tmp):
                with pytest.raises(KeyError, match="cost_matrix section not found"):
                    _load_matrix()
        finally:
            os.unlink(tmp)

    def test_lookup_range_propagates_missing_section_error(self):
        """lookup_range should propagate the descriptive KeyError from _load_matrix."""
        import tempfile, os
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write("unrelated:\n  x: 1\n")
            tmp = f.name
        try:
            with patch("plat_costmodel.matrix._KB_PATH", tmp):
                with pytest.raises(KeyError, match="cost_matrix section not found"):
                    lookup_range("standard_value_add", "medium", "basic")
        finally:
            os.unlink(tmp)


# ---------------------------------------------------------------------------
# Hardening: get_matrix_summary with malformed KB
# ---------------------------------------------------------------------------

class TestMatrixSummaryMalformed:
    def test_summary_missing_cost_matrix_raises(self):
        """get_matrix_summary should raise descriptive error if cost_matrix missing."""
        import tempfile, os
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write("other_section:\n  foo: bar\n")
            tmp = f.name
        try:
            with patch("plat_costmodel.matrix._KB_PATH", tmp):
                with pytest.raises(KeyError, match="cost_matrix section not found"):
                    get_matrix_summary()
        finally:
            os.unlink(tmp)
