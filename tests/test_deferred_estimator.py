"""Synthetic deferred-maintenance estimate from one knowledge-base item."""
from pathlib import Path

import yaml

from plat_costmodel.deferred_estimator import estimate_deferred_maintenance
from plat_costmodel.schemas import ProgramSchedule


def _knowledge_base() -> dict:
    path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "plat_costmodel"
        / "data"
        / "knowledge_base.yaml"
    )
    with path.open() as handle:
        return yaml.safe_load(handle)


def test_one_knowledge_base_item_explicit_quantity_has_high_and_low():
    """Roof replacement, quantity 4, uses the knowledge-base range as written."""
    kb = _knowledge_base()
    item = "roof_full_replacement"
    entry = kb["deferred_maintenance"][item]
    quantity = 4
    schedule = ProgramSchedule(start_month="2026-06", monthly_pace=1)

    result = estimate_deferred_maintenance(
        items=[item],
        quantity=quantity,
        schedule=schedule,
        kb=kb,
    )

    assert result["missing_items"] == []
    assert result["total_low"] == entry["per_unit_low"] * quantity
    assert result["total_high"] == entry["per_unit_high"] * quantity
    assert result["per_unit_low"] == entry["per_unit_low"]
    assert result["per_unit_high"] == entry["per_unit_high"]
    assert result["line_items"][0].category == item
    assert result["line_items"][0].low == 10_000
    assert result["line_items"][0].high == 16_000

    missing_quantity = estimate_deferred_maintenance(
        items=[item],
        quantity=None,
        schedule=schedule,
        kb=kb,
    )
    assert missing_quantity["total_low"] is None
    assert missing_quantity["total_high"] is None
    assert missing_quantity["missing_quantity"] is True

    missing_item = estimate_deferred_maintenance(
        items=["not_in_knowledge_base"],
        quantity=quantity,
        schedule=schedule,
        kb=kb,
    )
    assert missing_item["total_low"] is None
    assert missing_item["total_high"] is None
    assert missing_item["missing_items"] == ["not_in_knowledge_base"]
    assert missing_item["line_items"] == []
