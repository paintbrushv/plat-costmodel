"""Contractor bid evaluation against internal estimates."""

import re

from .estimator import estimate_unit
from .models import (
    BidEvaluation,
    BidFlag,
    ContractorBid,
    FinishTier,
    ScopeLevel,
    UnitEstimate,
)

# Map common bid descriptions to internal categories
_CATEGORY_ALIASES = {
    "flooring": "flooring",
    "lvp": "flooring",
    "vinyl plank": "flooring",
    "carpet": "flooring",
    "floor": "flooring",
    "kitchen": "kitchen",
    "cabinets": "kitchen",
    "countertops": "kitchen",
    "countertop": "kitchen",
    "counters": "kitchen",
    "cabinet": "kitchen",
    "bathroom": "bathroom",
    "bath": "bathroom",
    "vanity": "bathroom",
    "tub": "bathroom",
    "paint": "paint",
    "painting": "paint",
    "interior paint": "paint",
    "appliances": "appliances",
    "appliance": "appliances",
    "fridge": "appliances",
    "stove": "appliances",
    "range": "appliances",
    "fixtures": "fixtures_doors_trim",
    "doors": "fixtures_doors_trim",
    "trim": "fixtures_doors_trim",
    "hardware": "fixtures_doors_trim",
    "light fixtures": "fixtures_doors_trim",
    "cleaning": "cleaning",
    "clean": "cleaning",
    "patch": "patch_repair",
    "repair": "patch_repair",
    "drywall": "patch_repair",
    "hvac": "hvac",
    "ac": "hvac",
    "air conditioning": "hvac",
    "heating": "hvac",
    "plumbing": "plumbing",
    "electrical": "electrical",
    "wiring": "electrical",
}

# Minimum days for a standard value-add turn
_MIN_TIMELINE_DAYS = {
    ScopeLevel.LIGHT: 3,
    ScopeLevel.STANDARD_VALUE_ADD: 5,
}


# Short aliases that need word-boundary matching to avoid false positives
_WORD_BOUNDARY_ALIASES = {"ac", "range", "floor", "bath", "clean", "trim"}


def _match_category(description: str) -> str | None:
    """Try to match a bid line item description to an internal category."""
    desc_lower = description.lower().strip()
    for alias, category in _CATEGORY_ALIASES.items():
        if alias in _WORD_BOUNDARY_ALIASES:
            # Use word boundary to avoid false positives (e.g. "ac" in "vacancy")
            if re.search(r'\b' + re.escape(alias) + r'\b', desc_lower):
                return category
        else:
            if alias in desc_lower:
                return category
    return None


def evaluate_bid(
    bid: ContractorBid,
    estimate: UnitEstimate,
) -> BidEvaluation:
    """Evaluate a contractor bid against an internal estimate.

    Flags:
    - inflated: line item 30%+ above internal high estimate
    - vague: line item can't be matched to a known category
    - timeline: timeline shorter than minimum realistic days
    """
    flags: list[BidFlag] = []

    # Build lookup of internal estimates by category
    internal_by_cat = {li.category: li for li in estimate.line_items}

    matched_total = 0.0
    unmatched_total = 0.0

    for bid_item in bid.line_items:
        category = _match_category(bid_item.description)

        if category is None:
            # Vague / unmatched line item
            severity = "critical" if bid_item.amount > 1000 else "warning"
            flags.append(BidFlag(
                flag_type="vague",
                severity=severity,
                message=f"Cannot match '{bid_item.description}' to a known cost category. "
                        f"Amount: ${bid_item.amount:,.0f}. Request itemized breakdown.",
                line_item=bid_item.description,
                bid_amount=bid_item.amount,
            ))
            unmatched_total += bid_item.amount
            continue

        matched_total += bid_item.amount
        internal = internal_by_cat.get(category)
        if internal is None:
            continue

        # Check if 30%+ above internal high estimate
        threshold = internal.high * 1.30
        if bid_item.amount > threshold:
            overage_pct = ((bid_item.amount - internal.high) / internal.high) * 100
            flags.append(BidFlag(
                flag_type="inflated",
                severity="critical" if overage_pct > 50 else "warning",
                message=f"'{bid_item.description}' at ${bid_item.amount:,.0f} is "
                        f"{overage_pct:.0f}% above internal high estimate of ${internal.high:,.0f}.",
                line_item=bid_item.description,
                expected_range=f"${internal.low:,.0f}-${internal.high:,.0f}",
                bid_amount=bid_item.amount,
            ))

    # Check total bid against internal total
    if bid.total > estimate.total_high * 1.30:
        overage_pct = ((bid.total - estimate.total_high) / estimate.total_high) * 100
        flags.append(BidFlag(
            flag_type="inflated",
            severity="critical",
            message=f"Total bid ${bid.total:,.0f} is {overage_pct:.0f}% above internal high estimate "
                    f"of ${estimate.total_high:,.0f}.",
            expected_range=f"${estimate.total_low:,.0f}-${estimate.total_high:,.0f}",
            bid_amount=bid.total,
        ))

    # Check timeline
    if bid.timeline_days is not None:
        min_days = _MIN_TIMELINE_DAYS.get(estimate.scope_level, 5)
        if bid.timeline_days < min_days:
            flags.append(BidFlag(
                flag_type="timeline",
                severity="warning",
                message=f"Timeline of {bid.timeline_days} days is unrealistically short for "
                        f"{estimate.scope_level.value} scope (minimum realistic: {min_days} days). "
                        f"May indicate scope misunderstanding or intent to change-order later.",
                bid_amount=float(bid.timeline_days),
            ))

    # Check for high unmatched percentage
    if bid.total > 0 and unmatched_total / bid.total > 0.20:
        pct = (unmatched_total / bid.total) * 100
        flags.append(BidFlag(
            flag_type="vague",
            severity="critical",
            message=f"{pct:.0f}% of bid total (${unmatched_total:,.0f}) is in unmatched/vague line items. "
                    f"Request detailed breakdown.",
            bid_amount=unmatched_total,
        ))

    # Overall assessment
    critical_count = sum(1 for f in flags if f.severity == "critical")
    warning_count = sum(1 for f in flags if f.severity == "warning")

    if critical_count >= 2:
        assessment = "reject"
    elif critical_count >= 1 or warning_count >= 3:
        assessment = "concerns"
    else:
        assessment = "reasonable"

    return BidEvaluation(
        contractor_name=bid.contractor_name,
        bid_total=bid.total,
        internal_estimate_low=estimate.total_low,
        internal_estimate_high=estimate.total_high,
        flags=flags,
        overall_assessment=assessment,
    )
