"""ActualOutcome — completed-project ground truth.

Schema only in v1; no ingestion logic. A future spec will define the
Yardi reconciliation and contractor-invoice parsers that populate these
rows. The CLI insertion path exists in v1 for testing the link-back
to ScopeEstimate.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from plat_costmodel.models import LineItem


class ActualOutcome(BaseModel):
    """Completed-project actuals linked back to the originating ScopeRequest."""

    actual_id: str
    scope_request_id: str
    property_id: str
    line_items: list[LineItem]
    total_actual: float
    completed_at: datetime
    source: str  # "yardi", "contractor_invoice", "manual"
    notes: str = ""
