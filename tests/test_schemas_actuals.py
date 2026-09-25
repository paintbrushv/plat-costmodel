"""Tests for ActualOutcome — schema only, no ingestion."""
from datetime import datetime, timezone

from plat_costmodel.models import LineItem
from plat_costmodel.schemas.actuals import ActualOutcome


def test_actual_outcome_round_trip():
    a = ActualOutcome(
        actual_id="a1",
        scope_request_id="req1",
        property_id="p1",
        line_items=[LineItem(category="paint", low=900, high=900)],
        total_actual=900,
        completed_at=datetime.now(timezone.utc),
        source="manual",
        notes="test insertion",
    )
    assert ActualOutcome.model_validate(a.model_dump()) == a


def test_actual_outcome_defaults():
    a = ActualOutcome(
        actual_id="a1", scope_request_id="r1", property_id="p1",
        line_items=[], total_actual=0,
        completed_at=datetime.now(timezone.utc), source="manual",
    )
    assert a.notes == ""
