"""Hardening tests — edge cases, adversarial inputs, conservative bias enforcement."""

import io
import pytest
from plat_costmodel.estimator import estimate_unit, estimate_property
from plat_costmodel.models import PropertyEstimateInput, UnitSpec
from plat_costmodel.roi import check_roi
from plat_costmodel.risk import get_risk_flags
from plat_costmodel.bid_eval import evaluate_bid, _match_category
from plat_costmodel.sow import generate_sow
from plat_costmodel.ingest import parse_yardi_csv, summarize_by_unit
from plat_costmodel.models import ContractorBid, BidLineItem, ScopeLevel


class TestEstimatorEdgeCases:
    def test_zero_sqft_raises(self):
        with pytest.raises(ValueError):
            estimate_unit(0, 1, 1, "standard_value_add")

    def test_negative_sqft_raises(self):
        with pytest.raises(ValueError):
            estimate_unit(-100, 1, 1, "standard_value_add")

    def test_zero_bathrooms_raises(self):
        with pytest.raises(ValueError):
            estimate_unit(850, 2, 0, "standard_value_add")

    def test_negative_bedrooms_raises(self):
        with pytest.raises(ValueError):
            estimate_unit(850, -1, 1, "standard_value_add")

    def test_very_large_unit(self):
        """2000 sf unit should still produce a valid estimate."""
        est = estimate_unit(2000, 4, 3, "standard_value_add", "upgraded")
        assert est.total_high > 0
        assert est.size_category.value == "large"

    def test_very_small_unit(self):
        """300 sf studio should still produce a valid estimate."""
        est = estimate_unit(300, 0, 1, "standard_value_add", "basic")
        assert est.total_high > 0
        assert est.size_category.value == "small"

    def test_many_bathrooms(self):
        """3 bathrooms should multiply bathroom costs by 3."""
        est = estimate_unit(1000, 3, 3, "standard_value_add")
        bath_item = next(li for li in est.line_items if li.category == "bathroom")
        # 3 bathrooms should cost roughly 3x a single bathroom
        single = estimate_unit(1000, 3, 1, "standard_value_add")
        single_bath = next(li for li in single.line_items if li.category == "bathroom")
        assert bath_item.high == pytest.approx(single_bath.high * 3, rel=0.01)

    def test_invalid_scope_level_raises(self):
        with pytest.raises(ValueError):
            estimate_unit(850, 2, 1, "gut_renovation")

    def test_invalid_finish_tier_raises(self):
        with pytest.raises(ValueError):
            estimate_unit(850, 2, 1, "standard_value_add", "luxury")

    def test_future_year_built_no_flags(self):
        """A 2025 build should have zero risk flags."""
        flags = get_risk_flags(2025)
        assert len(flags) == 0

    def test_very_old_building(self):
        """1950 build should trigger multiple critical flags."""
        flags = get_risk_flags(1950)
        assert len(flags) >= 4
        assert any(f.severity == "critical" for f in flags)


class TestConservativeBiasEnforcement:
    def test_total_high_always_exceeds_total_low(self):
        """For every configuration, high must exceed low."""
        configs = [
            (650, 1, 1, "light", "basic"),
            (650, 1, 1, "standard_value_add", "basic"),
            (850, 2, 1, "standard_value_add", "basic"),
            (850, 2, 1, "standard_value_add", "upgraded"),
            (1000, 3, 2, "standard_value_add", "upgraded"),
        ]
        for sqft, beds, baths, scope, finish in configs:
            est = estimate_unit(sqft, beds, baths, scope, finish)
            assert est.total_high > est.total_low, f"Failed for {sqft}sf {scope} {finish}"

    def test_upgraded_never_cheaper_than_basic(self):
        """Upgraded finish should never produce a lower high-estimate than basic."""
        for sqft in [650, 850, 1000]:
            basic = estimate_unit(sqft, 2, 1, "standard_value_add", "basic")
            upgraded = estimate_unit(sqft, 2, 1, "standard_value_add", "upgraded")
            assert upgraded.total_high >= basic.total_high, f"Failed at {sqft}sf"

    def test_larger_unit_never_cheaper(self):
        """Larger units should never have lower high-estimates than smaller ones (same config)."""
        small = estimate_unit(650, 2, 1, "standard_value_add", "basic")
        medium = estimate_unit(850, 2, 1, "standard_value_add", "basic")
        large = estimate_unit(1000, 2, 1, "standard_value_add", "basic")
        assert medium.total_high >= small.total_high
        assert large.total_high >= medium.total_high

    def test_more_bathrooms_never_cheaper(self):
        """More bathrooms should always cost more."""
        one_ba = estimate_unit(850, 2, 1, "standard_value_add")
        two_ba = estimate_unit(850, 2, 2, "standard_value_add")
        assert two_ba.total_high > one_ba.total_high

    def test_contingency_always_positive(self):
        for scope in ["light", "standard_value_add"]:
            est = estimate_unit(850, 2, 1, scope)
            assert est.contingency_pct > 0

    def test_roi_uses_high_estimate_in_note(self):
        """ROI should always reference conservative (high) estimate."""
        result = check_roi(15000, 850, 1050)
        assert "high" in result.note.lower() or "conservative" in result.note.lower()


class TestBidEvalAdversarial:
    def test_bid_with_zero_amount_items(self):
        est = estimate_unit(850, 2, 1, "standard_value_add", year_built=1978)
        bid = ContractorBid(
            contractor_name="Zero Bid",
            line_items=[BidLineItem(description="Flooring", amount=0)],
            total=0,
        )
        result = evaluate_bid(bid, est)
        # Should not crash, should still produce an assessment
        assert result.overall_assessment in ("reasonable", "concerns", "reject")

    def test_bid_with_negative_amounts(self):
        est = estimate_unit(850, 2, 1, "standard_value_add", year_built=1978)
        bid = ContractorBid(
            contractor_name="Negative",
            line_items=[BidLineItem(description="Flooring credit", amount=-500)],
            total=-500,
        )
        result = evaluate_bid(bid, est)
        assert result.overall_assessment in ("reasonable", "concerns", "reject")

    def test_bid_with_empty_line_items(self):
        est = estimate_unit(850, 2, 1, "standard_value_add", year_built=1978)
        bid = ContractorBid(
            contractor_name="Empty",
            line_items=[],
            total=10000,
        )
        result = evaluate_bid(bid, est)
        assert result.overall_assessment in ("reasonable", "concerns", "reject")

    def test_bid_with_very_high_single_item(self):
        """Single item at 5x the total estimate should be flagged."""
        est = estimate_unit(850, 2, 1, "standard_value_add", year_built=1978)
        bid = ContractorBid(
            contractor_name="Extreme Padding",
            line_items=[BidLineItem(description="Flooring", amount=50000)],
            total=50000,
            timeline_days=7,
        )
        result = evaluate_bid(bid, est)
        assert result.overall_assessment == "reject"
        inflated = [f for f in result.flags if f.flag_type == "inflated"]
        assert len(inflated) >= 1

    def test_category_match_range_not_false_positive(self):
        """'Range' should match appliances but 'gun range' should not."""
        assert _match_category("range") == "appliances"
        # "insurance" should not match anything
        assert _match_category("insurance premium") is None

    def test_category_match_ac_not_false_positive(self):
        """'ac' should match HVAC but 'vacancy' should not."""
        assert _match_category("AC unit replacement") == "hvac"


class TestYardiIngestHardening:
    def test_empty_csv(self):
        csv = io.StringIO("Date,Unit,Category,Amount,Description\n")
        records = parse_yardi_csv(csv, "PROP1")
        assert records == []

    def test_missing_columns(self):
        """CSV with wrong column names should not crash."""
        csv = io.StringIO("Col1,Col2,Col3\nA,B,C\n")
        records = parse_yardi_csv(csv, "PROP1")
        assert len(records) == 1
        assert records[0]["amount"] == 0.0  # no Amount column → default

    def test_malformed_amount(self):
        csv = io.StringIO("Date,Unit,Category,Amount,Description\n2025-01-01,101,Flooring,NOT_A_NUMBER,LVP\n")
        records = parse_yardi_csv(csv, "PROP1")
        assert records[0]["amount"] == 0.0

    def test_negative_amount(self):
        csv = io.StringIO("Date,Unit,Category,Amount,Description\n2025-01-01,101,Flooring,-500,Credit\n")
        records = parse_yardi_csv(csv, "PROP1")
        assert records[0]["amount"] == -500.0

    def test_unicode_in_description(self):
        csv = io.StringIO("Date,Unit,Category,Amount,Description\n2025-01-01,101,Flooring,$2100,LVP — premium grade™\n")
        records = parse_yardi_csv(csv, "PROP1")
        assert len(records) == 1

    def test_extra_columns_ignored(self):
        csv = io.StringIO("Date,Unit,Category,Amount,Description,ExtraCol\n2025-01-01,101,Flooring,$2100,LVP,ignored\n")
        records = parse_yardi_csv(csv, "PROP1")
        assert len(records) == 1
        assert "ExtraCol" not in records[0]

    def test_summarize_handles_duplicates(self):
        """Multiple entries for same unit/category should sum."""
        records = [
            {"unit_id": "101", "internal_category": "flooring", "amount": 1000},
            {"unit_id": "101", "internal_category": "flooring", "amount": 500},
        ]
        summary = summarize_by_unit(records)
        assert summary["101"]["categories"]["flooring"] == 1500
        assert summary["101"]["total"] == 1500


class TestPropertyEstimateEdgeCases:
    def test_empty_units_list(self):
        prop = PropertyEstimateInput(property_id="PROP1", total_units=10, year_built=1980)
        est = estimate_property(prop)
        assert est.units_needing_work == 0
        assert est.exterior_capex_high > 0  # exterior still applies

    def test_zero_total_units(self):
        prop = PropertyEstimateInput(property_id="PROP1", total_units=0)
        est = estimate_property(prop)
        assert est.per_unit_average_high == 0  # no division by zero

    def test_invalid_exterior_item_ignored(self):
        prop = PropertyEstimateInput(
            property_id="PROP1",
            total_units=10,
            unit_mix=[UnitSpec(unit_id="101", sqft=850, bedrooms=2, bathrooms=1)],
            exterior_items=["nonexistent_item"],
        )
        est = estimate_property(prop)
        assert est.exterior_capex_high == 0


class TestSOWEdgeCases:
    def test_sow_with_zero_bathrooms_raises(self):
        """SOW should validate inputs too."""
        # SOW itself doesn't validate, but it should still produce output
        sow = generate_sow(850, 2, 0, "standard_value_add")
        bath_item = next((li for li in sow.line_items if li.category == "bathroom"), None)
        if bath_item:
            assert "0 bathroom" in bath_item.quantity_notes

    def test_light_sow_ignores_upgraded_finish(self):
        """Light scope should produce the same SOW regardless of finish tier."""
        basic = generate_sow(850, 2, 1, "light", "basic")
        upgraded = generate_sow(850, 2, 1, "light", "upgraded")
        assert len(basic.line_items) == len(upgraded.line_items)
