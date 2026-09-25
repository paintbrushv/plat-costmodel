"""Tests for contractor bid evaluation."""

from plat_costmodel.bid_eval import evaluate_bid
from plat_costmodel.estimator import estimate_unit
from plat_costmodel.models import ContractorBid, BidLineItem


def _get_estimate():
    return estimate_unit(850, 2, 1, "standard_value_add", "basic", year_built=1978)


class TestBidEvaluation:
    def test_reasonable_bid(self):
        est = _get_estimate()
        bid = ContractorBid(
            contractor_name="Good Contractor",
            line_items=[
                BidLineItem(description="Flooring - LVP", amount=2000),
                BidLineItem(description="Kitchen update", amount=2000),
                BidLineItem(description="Bathroom renovation", amount=2800),
                BidLineItem(description="Interior paint", amount=1000),
                BidLineItem(description="Appliance package", amount=2000),
                BidLineItem(description="Fixtures and hardware", amount=700),
            ],
            total=10500,
            timeline_days=10,
        )
        result = evaluate_bid(bid, est)
        assert result.overall_assessment == "reasonable"

    def test_inflated_line_item(self):
        est = _get_estimate()
        bid = ContractorBid(
            contractor_name="Padded Contractor",
            line_items=[
                BidLineItem(description="Flooring - LVP", amount=5000),  # Way over
                BidLineItem(description="Kitchen update", amount=2000),
                BidLineItem(description="Bathroom", amount=2800),
                BidLineItem(description="Paint", amount=1000),
                BidLineItem(description="Appliances", amount=2000),
            ],
            total=12800,
            timeline_days=10,
        )
        result = evaluate_bid(bid, est)
        inflated = [f for f in result.flags if f.flag_type == "inflated"]
        assert len(inflated) > 0
        assert any("flooring" in f.line_item.lower() for f in inflated)

    def test_vague_lump_sum(self):
        est = _get_estimate()
        bid = ContractorBid(
            contractor_name="Vague Contractor",
            line_items=[
                BidLineItem(description="General labor", amount=5000),
                BidLineItem(description="Miscellaneous", amount=3000),
                BidLineItem(description="Materials", amount=4000),
            ],
            total=12000,
            timeline_days=10,
        )
        result = evaluate_bid(bid, est)
        vague = [f for f in result.flags if f.flag_type == "vague"]
        assert len(vague) >= 2  # At least the unmatched items

    def test_unrealistic_timeline(self):
        est = _get_estimate()
        bid = ContractorBid(
            contractor_name="Too Fast Contractor",
            line_items=[
                BidLineItem(description="Flooring", amount=2000),
                BidLineItem(description="Kitchen", amount=2000),
                BidLineItem(description="Bathroom", amount=2800),
                BidLineItem(description="Paint", amount=1000),
            ],
            total=7800,
            timeline_days=3,  # Way too fast
        )
        result = evaluate_bid(bid, est)
        timeline = [f for f in result.flags if f.flag_type == "timeline"]
        assert len(timeline) == 1

    def test_no_timeline_flag_when_none(self):
        est = _get_estimate()
        bid = ContractorBid(
            contractor_name="No Timeline",
            line_items=[BidLineItem(description="Flooring", amount=2000)],
            total=2000,
        )
        result = evaluate_bid(bid, est)
        timeline = [f for f in result.flags if f.flag_type == "timeline"]
        assert len(timeline) == 0

    def test_reject_assessment_multiple_criticals(self):
        est = _get_estimate()
        bid = ContractorBid(
            contractor_name="Bad Contractor",
            line_items=[
                BidLineItem(description="General work", amount=8000),  # vague + large
                BidLineItem(description="Miscellaneous", amount=5000),  # vague + large
                BidLineItem(description="Flooring", amount=6000),  # inflated
            ],
            total=19000,  # way over
            timeline_days=3,
        )
        result = evaluate_bid(bid, est)
        assert result.overall_assessment == "reject"

    def test_category_matching_aliases(self):
        """Various descriptions should match to correct categories."""
        est = _get_estimate()
        bid = ContractorBid(
            contractor_name="Alias Test",
            line_items=[
                BidLineItem(description="LVP flooring install", amount=2000),
                BidLineItem(description="Cabinet and countertop work", amount=2000),
                BidLineItem(description="Vanity and tub work", amount=2800),
            ],
            total=6800,
            timeline_days=10,
        )
        result = evaluate_bid(bid, est)
        # Should not flag these as vague since they match aliases
        vague = [f for f in result.flags if f.flag_type == "vague"]
        assert len(vague) == 0

    def test_bid_total_vs_estimate(self):
        est = _get_estimate()
        bid = ContractorBid(
            contractor_name="Test",
            line_items=[BidLineItem(description="Flooring", amount=2000)],
            total=2000,
            timeline_days=10,
        )
        result = evaluate_bid(bid, est)
        assert result.internal_estimate_low == est.total_low
        assert result.internal_estimate_high == est.total_high
