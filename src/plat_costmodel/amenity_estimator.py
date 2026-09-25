"""Pure amenity-program cost estimator.

Given an AmenityCohort + the loaded knowledge base, compute install + opex
cost ranges and optional success-metric results (occupancy lift, rent premium).

Quantity rules:
- install + opex multiply by ``cohort.quantity``
- ``typical_occupancy_lift_pct`` is per-installation (saturation effect on
  a second pool), so NOT multiplied by quantity
- ``typical_rent_premium_monthly`` IS multiplied by quantity (per-unit pricing
  for ev_chargers etc.)

Gates fire only when both the caller's expected target AND the KB's typical
projection are present. If either is missing, the corresponding result is
None — we don't fabricate a projection from no data.

This module is dependency-free of the persistence layer; it returns a plain
dict that scope_service._estimate_amenity shapes into an AmenityScopeEstimate.
"""
from __future__ import annotations

from typing import Optional

from plat_costmodel.schemas import (
    AmenityCohort,
    OccupancyLiftResult,
    RentPremiumResult,
    raise_problem,
)


def estimate_amenity(cohort: AmenityCohort, kb: dict) -> dict:
    """Compute amenity cost components + optional success-metric results.

    Returns a dict with keys: install_cost_low, install_cost_high,
    annual_opex_low, annual_opex_high, expected_occupancy_lift_result,
    expected_rent_premium_result.
    """
    catalog = kb.get("amenity_catalog", {})
    entry = catalog.get(cohort.amenity_type)
    if entry is None:
        raise_problem(
            "validation_error",
            f"amenity_type {cohort.amenity_type!r} not in knowledge_base.amenity_catalog",
            field_errors=[{
                "loc": ["cohort", "amenity_type"],
                "msg": f"unknown amenity_type: {cohort.amenity_type!r}",
            }],
            hint="Use one of: " + ", ".join(sorted(catalog.keys())),
        )

    qty = cohort.quantity
    install_low = float(entry["install_low"]) * qty
    install_high = float(entry["install_high"]) * qty
    annual_opex_low: Optional[float] = (
        float(entry["annual_opex_low"]) * qty
        if "annual_opex_low" in entry else None
    )
    annual_opex_high: Optional[float] = (
        float(entry["annual_opex_high"]) * qty
        if "annual_opex_high" in entry else None
    )

    # Occupancy lift gate — fires only if caller supplied a target AND
    # KB has a typical projection.
    lift_result: Optional[OccupancyLiftResult] = None
    if (
        cohort.expected_occupancy_lift_pct is not None
        and "typical_occupancy_lift_pct" in entry
    ):
        target = float(cohort.expected_occupancy_lift_pct)
        # NOT multiplied by quantity — saturation effect on second-pool etc.
        projected = float(entry["typical_occupancy_lift_pct"])
        clears = projected >= target
        shortfall = (target - projected) if not clears else None
        lift_result = OccupancyLiftResult(
            target_lift_pct=target,
            projected_lift_pct=projected,
            clears_threshold=clears,
            shortfall_pct=shortfall,
        )

    # Rent premium gate — fires only if caller supplied a target AND KB has
    # a typical premium. typical_rent_premium_monthly IS multiplied by qty.
    premium_result: Optional[RentPremiumResult] = None
    if (
        cohort.expected_rent_premium_monthly is not None
        and "typical_rent_premium_monthly" in entry
    ):
        target = float(cohort.expected_rent_premium_monthly)
        projected = float(entry["typical_rent_premium_monthly"]) * qty
        clears = projected >= target
        shortfall_monthly = (target - projected) if not clears else None
        premium_result = RentPremiumResult(
            target_premium_monthly=target,
            projected_premium_monthly=projected,
            clears_threshold=clears,
            shortfall_monthly=shortfall_monthly,
        )

    # deluxe field is read here to acknowledge it has been considered. The KB
    # does not yet encode deluxe-tier cost multipliers, so this is intentionally
    # a no-op until a future PR adds the pricing logic. The assignment to _ keeps
    # this acknowledgment durable: a future automated refactor or linter sweep
    # will not silently strip a bare attribute access, preserving the intent that
    # deluxe was evaluated and deliberately left as a no-op rather than forgotten.
    _ = cohort.deluxe

    return {
        "install_cost_low": install_low,
        "install_cost_high": install_high,
        "annual_opex_low": annual_opex_low,
        "annual_opex_high": annual_opex_high,
        "expected_occupancy_lift_result": lift_result,
        "expected_rent_premium_result": premium_result,
    }
