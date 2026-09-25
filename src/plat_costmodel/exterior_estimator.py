"""Pure exterior-program cost estimator.

Given an ExteriorCohort + the loaded knowledge base, compute line items per
KB exterior_capex.items entry, total cost range, per-unit cost range, and
a payback_years_estimated placeholder (None — payback computation lands
in a follow-up PR).

This module is dependency-free of the persistence layer; it returns a plain
dict that scope_service._estimate_exterior shapes into an ExteriorScopeEstimate
after attaching estimate_id, scope_request_id, property_id, pricing_snapshot_id,
estimated_at, and risk flags.
"""
from __future__ import annotations

from plat_costmodel.models import LineItem
from plat_costmodel.schemas import ExteriorCohort, raise_problem


def estimate_exterior(cohort: ExteriorCohort, kb: dict) -> dict:
    """Compute exterior cost components for one ExteriorCohort.

    Returns a dict with keys: line_items, total_low, total_high,
    per_unit_low, per_unit_high, payback_years_estimated.
    """
    items_kb = kb.get("exterior_capex", {}).get("items", {})
    line_items: list[LineItem] = []
    total_low = 0.0
    total_high = 0.0
    for item_key in cohort.items:
        entry = items_kb.get(item_key)
        if entry is None:
            raise_problem(
                "validation_error",
                f"exterior item {item_key!r} not in knowledge_base.exterior_capex.items",
                field_errors=[{
                    "loc": ["cohort", "items"],
                    "msg": f"unknown exterior item: {item_key!r}",
                }],
                hint="Use one of: " + ", ".join(sorted(items_kb.keys())),
            )
        per_unit_low = float(entry["per_unit_low"])
        per_unit_high = float(entry["per_unit_high"])
        item_low = per_unit_low * cohort.total_units
        item_high = per_unit_high * cohort.total_units
        line_items.append(LineItem(category=item_key, low=item_low, high=item_high))
        total_low += item_low
        total_high += item_high

    per_unit_low_total = total_low / cohort.total_units if cohort.total_units else 0.0
    per_unit_high_total = total_high / cohort.total_units if cohort.total_units else 0.0

    return {
        "line_items": line_items,
        "total_low": total_low,
        "total_high": total_high,
        "per_unit_low": per_unit_low_total,
        "per_unit_high": per_unit_high_total,
        "payback_years_estimated": None,
    }
