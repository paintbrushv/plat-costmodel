"""Pure deferred-maintenance cost estimator.

Given explicit items, an explicit quantity, an explicit schedule, and the
loaded knowledge base, price each item from ``deferred_maintenance`` per-unit
ranges. This module does not touch persistence.

A request that omits items, quantity, or schedule is not priced. An item that
is not in the knowledge base is not given a stand-in cost, and a missing
per-unit range is not filled in. Totals stay ``None`` in those cases. No
market multiplier is applied: ``markets`` in the knowledge base has no
adjustment factor, and this estimator does not add one.
"""
from __future__ import annotations

from typing import Optional

from plat_costmodel.models import LineItem
from plat_costmodel.schemas.scope import ProgramSchedule


def estimate_deferred_maintenance(
    items: Optional[list[str]],
    quantity: Optional[int],
    schedule: Optional[ProgramSchedule],
    kb: dict,
    *,
    age_at_replacement_years: Optional[int] = None,
    condition: str = "end_of_life",
) -> dict:
    """Price deferred-maintenance items from the knowledge base.

    Returns line_items, total_low, total_high, per_unit_low, per_unit_high,
    triggered_by, missing_items, missing_quantity, and missing_schedule.
    Dollar fields are ``None`` when the request cannot be priced without
    inventing an item, a quantity, or a unit cost.
    """
    catalog = kb.get("deferred_maintenance") or {}
    requested = list(items) if items else []
    unpriced = _unpriced(
        missing_items=[key for key in requested if key not in catalog],
        missing_quantity=quantity is None,
        missing_schedule=schedule is None,
    )
    if not requested or quantity is None or schedule is None or quantity < 1:
        unpriced["missing_quantity"] = quantity is None or quantity < 1
        unpriced["missing_schedule"] = schedule is None
        return unpriced

    line_items: list[LineItem] = []
    missing_items: list[str] = []
    total_low = 0.0
    total_high = 0.0
    for item_key in requested:
        entry = catalog.get(item_key)
        if (
            not isinstance(entry, dict)
            or "per_unit_low" not in entry
            or "per_unit_high" not in entry
        ):
            missing_items.append(item_key)
            continue
        item_low = float(entry["per_unit_low"]) * quantity
        item_high = float(entry["per_unit_high"]) * quantity
        line_items.append(LineItem(category=item_key, low=item_low, high=item_high))
        total_low += item_low
        total_high += item_high

    if missing_items:
        return _unpriced(
            missing_items=missing_items,
            missing_quantity=False,
            missing_schedule=False,
            line_items=line_items,
        )

    return {
        "line_items": line_items,
        "total_low": total_low,
        "total_high": total_high,
        "per_unit_low": total_low / quantity,
        "per_unit_high": total_high / quantity,
        "triggered_by": _triggered_by(
            requested,
            catalog,
            age_at_replacement_years=age_at_replacement_years,
            condition=condition,
        ),
        "missing_items": [],
        "missing_quantity": False,
        "missing_schedule": False,
    }


def _unpriced(
    *,
    missing_items: list[str],
    missing_quantity: bool,
    missing_schedule: bool,
    line_items: Optional[list[LineItem]] = None,
) -> dict:
    return {
        "line_items": line_items or [],
        "total_low": None,
        "total_high": None,
        "per_unit_low": None,
        "per_unit_high": None,
        "triggered_by": None,
        "missing_items": missing_items,
        "missing_quantity": missing_quantity,
        "missing_schedule": missing_schedule,
    }


def _triggered_by(
    items: list[str],
    catalog: dict,
    *,
    age_at_replacement_years: Optional[int],
    condition: str,
) -> str:
    """Describe only facts the caller or the knowledge base already stated."""
    parts: list[str] = []
    for item_key in items:
        entry = catalog[item_key]
        bits = [item_key, f"condition={condition}"]
        typical = entry.get("typical_age_years")
        if age_at_replacement_years is not None and typical is not None:
            age = age_at_replacement_years
            typical_years = int(typical)
            if age > typical_years:
                bits.append(f"age {age}yr exceeds typical_age_years={typical_years}")
            else:
                bits.append(f"age {age}yr; typical_age_years={typical_years}")
        elif typical is not None:
            bits.append(f"typical_age_years={int(typical)}")
        kb_trigger = entry.get("triggered_by")
        if kb_trigger:
            bits.append(str(kb_trigger))
        parts.append("; ".join(bits))
    return " | ".join(parts)
