"""ROI threshold gating for renovation plans."""

from __future__ import annotations

from .models import LineItem, ROIPathItem, ROIResult

DEFAULT_THRESHOLD_PCT = 15.0


def check_roi(
    total_cost_high: float,
    current_monthly_rent: float,
    target_monthly_rent: float,
    threshold_pct: float = DEFAULT_THRESHOLD_PCT,
    line_items: list[LineItem] | None = None,
) -> ROIResult:
    """Check whether a renovation plan clears the minimum ROI threshold.

    Always uses the HIGH cost estimate (conservative).
    Formula: (annual_rent_lift / total_cost_high) * 100 >= threshold

    When the gate fails and ``line_items`` are supplied the result includes
    per-line-item cut candidates (``line_item_suggestions``) ranked by
    potential savings, plus a ``path_to_pass`` list of human-readable
    ordered steps the analyst can take.
    """
    monthly_lift = target_monthly_rent - current_monthly_rent
    annual_lift = monthly_lift * 12

    if total_cost_high <= 0:
        roi_pct = 0.0
        note = "Invalid: total cost must be positive."
    else:
        roi_pct = (annual_lift / total_cost_high) * 100
        note = ""

    clears = roi_pct >= threshold_pct

    if not note:
        if clears:
            note = f"Passes {threshold_pct}% ROI gate. Uses conservative (high) cost estimate."
        else:
            shortfall = threshold_pct - roi_pct
            needed_monthly = (total_cost_high * threshold_pct / 100) / 12
            note = (
                f"Fails {threshold_pct}% ROI gate by {shortfall:.1f}pp. "
                f"Need ${needed_monthly:,.0f}/mo target rent to clear "
                f"(currently ${target_monthly_rent:,.0f}/mo)."
            )

    # Compute path-to-pass fields on failure only
    cost_reduction_needed: float | None = None
    rent_increase_needed: float | None = None
    path_to_pass: list[str] = []
    line_item_suggestions: list[ROIPathItem] = []

    if not clears and total_cost_high > 0:
        # How much to reduce cost to pass at the *current* target rent
        # Required: (annual_lift / required_cost) * 100 >= threshold_pct
        # => required_cost = annual_lift * 100 / threshold_pct  (only valid if annual_lift > 0)
        if annual_lift > 0:
            required_cost = (annual_lift * 100.0) / threshold_pct
            cost_reduction_needed = round(total_cost_high - required_cost)
        else:
            cost_reduction_needed = None  # rent lift is non-positive; cost cut won't help

        # How much to raise monthly target rent to pass at the *current* cost
        # Required: (needed_annual / total_cost_high) * 100 >= threshold_pct
        # => needed_annual = total_cost_high * threshold_pct / 100
        needed_annual = total_cost_high * threshold_pct / 100.0
        needed_monthly_lift = needed_annual / 12.0
        needed_target_rent = current_monthly_rent + needed_monthly_lift
        rent_increase_needed = round(needed_target_rent - target_monthly_rent)

        # Build human-readable path_to_pass
        path_to_pass = _build_path_to_pass(
            total_cost_high=total_cost_high,
            cost_reduction_needed=cost_reduction_needed,
            target_monthly_rent=target_monthly_rent,
            rent_increase_needed=rent_increase_needed,
            threshold_pct=threshold_pct,
            roi_pct=roi_pct,
        )

        # Per-line-item suggestions when line items are available
        if line_items:
            line_item_suggestions = _build_line_item_suggestions(
                line_items=line_items,
                cost_reduction_needed=cost_reduction_needed,
                total_cost_high=total_cost_high,
            )

    return ROIResult(
        total_cost_high=total_cost_high,
        current_monthly_rent=current_monthly_rent,
        target_monthly_rent=target_monthly_rent,
        monthly_rent_lift=monthly_lift,
        annual_rent_lift=annual_lift,
        roi_pct=round(roi_pct, 2),
        threshold_pct=threshold_pct,
        clears_threshold=clears,
        note=note,
        cost_reduction_needed=cost_reduction_needed,
        rent_increase_needed=rent_increase_needed,
        path_to_pass=path_to_pass,
        line_item_suggestions=line_item_suggestions,
    )


def _build_path_to_pass(
    total_cost_high: float,
    cost_reduction_needed: float | None,
    target_monthly_rent: float,
    rent_increase_needed: float,
    threshold_pct: float,
    roi_pct: float,
) -> list[str]:
    """Return an ordered list of plain-English steps to clear the ROI gate."""
    steps: list[str] = []

    shortfall_pp = threshold_pct - roi_pct
    steps.append(
        f"ROI shortfall: {shortfall_pp:.1f} percentage points below the {threshold_pct:.0f}% minimum. "
        "Choose one (or combine) of the options below:"
    )

    # Option A — reduce cost
    if cost_reduction_needed is not None and cost_reduction_needed > 0:
        pct_of_budget = (cost_reduction_needed / total_cost_high) * 100
        steps.append(
            f"A) Reduce total renovation cost by ${cost_reduction_needed:,.0f} "
            f"({pct_of_budget:.0f}% of current budget). "
            "See line-item suggestions below for the largest cut candidates."
        )
    elif cost_reduction_needed is not None and cost_reduction_needed <= 0:
        steps.append(
            "A) Cost reduction alone is insufficient — the rent lift is too small to "
            "support this scope even at $0 cost. Focus on Option B."
        )
    else:
        steps.append(
            "A) Cost reduction will not help — the projected rent lift is zero or negative."
        )

    # Option B — raise rent assumption
    if rent_increase_needed > 0:
        steps.append(
            f"B) Raise target rent by ${rent_increase_needed:,.0f}/mo "
            f"(from ${target_monthly_rent:,.0f} to ${target_monthly_rent + rent_increase_needed:,.0f}/mo). "
            "Validate against current comps before underwriting at higher rent."
        )
    else:
        steps.append(
            f"B) Target rent is already at or above the level needed — "
            "the gap is entirely on the cost side."
        )

    # Option C — combination
    if cost_reduction_needed is not None and cost_reduction_needed > 0 and rent_increase_needed > 0:
        half_cost = round(cost_reduction_needed / 2)
        half_rent = round(rent_increase_needed / 2)
        steps.append(
            f"C) Split the difference: cut cost by ~${half_cost:,.0f} "
            f"and raise target rent by ~${half_rent:,.0f}/mo."
        )

    return steps


def _build_line_item_suggestions(
    line_items: list[LineItem],
    cost_reduction_needed: float | None,
    total_cost_high: float,
) -> list[ROIPathItem]:
    """Rank line items by high-end cost and suggest cuts to reach the required savings.

    Returns up to 5 line items sorted largest-to-smallest. Each item shows
    what its cost would need to be reduced to in order to contribute proportionally
    to the total required savings.
    """
    if cost_reduction_needed is None or cost_reduction_needed <= 0:
        return []

    # Sort by high cost descending — biggest items = best cut candidates
    ranked = sorted(line_items, key=lambda li: li.high, reverse=True)[:5]

    suggestions: list[ROIPathItem] = []
    for item in ranked:
        if item.high <= 0:
            continue
        # Pro-rata share of required reduction based on this item's % of total high
        item_pct_of_budget = item.high / total_cost_high if total_cost_high > 0 else 0
        proportional_cut = round(cost_reduction_needed * item_pct_of_budget)
        required_value = max(0.0, item.high - proportional_cut)
        suggestions.append(ROIPathItem(
            action_type="cut_cost",
            description=f"Reduce '{item.category}' budget",
            current_value=item.high,
            required_value=required_value,
            delta=proportional_cut,
        ))

    return suggestions
