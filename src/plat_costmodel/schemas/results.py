"""Per-program-type success-metric result models.

Mirrors ``models.ROIResult``'s shape (target / projected / cleared / shortfall /
path_to_pass) so every program type produces structurally similar gate output.

Note on ``path_to_pass`` divergence from ``ROIResult``:
  ``ROIResult.path_to_pass`` is ``list[str]`` because ROI failures can require
  multiple ordered suggestions (cut cost AND raise rent).  These slice-B models
  represent simpler single-threshold gates, so ``Optional[str]`` is sufficient
  and avoids forcing callers to unwrap a list for what is almost always one hint.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, computed_field


class OccupancyLiftResult(BaseModel):
    """Success-metric result for amenity additions targeting occupancy lift.

    ``target_lift_pct`` and ``projected_lift_pct`` are percentage points
    (e.g. 1.5 means a 1.5pp lift, not 0.015 fraction).
    """

    target_lift_pct: float = Field(ge=0)
    projected_lift_pct: float = Field(ge=0)
    clears_threshold: bool
    shortfall_pct: Optional[float] = None
    path_to_pass: Optional[str] = None


class RentPremiumResult(BaseModel):
    """Success-metric result for amenities or scopes targeting a rent premium.

    Premiums are per-unit monthly dollars.

    ``annual_premium_per_unit`` is a computed field derived from
    ``projected_premium_monthly * 12``; it cannot be set independently,
    eliminating the risk of callers passing an inconsistent annual value.
    """

    target_premium_monthly: float = Field(ge=0)
    projected_premium_monthly: float = Field(ge=0)
    clears_threshold: bool
    shortfall_monthly: Optional[float] = None
    path_to_pass: Optional[str] = None

    @computed_field
    @property
    def annual_premium_per_unit(self) -> float:
        """Annual rent premium per unit, derived from projected_premium_monthly * 12."""
        return self.projected_premium_monthly * 12
