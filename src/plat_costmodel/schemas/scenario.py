"""Scenario discriminated union — runtime requests for estimate_from_deal.

Each scenario corresponds to one program the caller wants estimated. The
``scope_type`` discriminator routes to the right variant. ``InteriorScenario``
references a deal's unit_cohort by ``cohort_id``; the other variants are
property-scoped and carry their own item / amenity context inline.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field

from plat_costmodel.models import FinishTier, ScopeLevel
from plat_costmodel.schemas.scope import ProgramSchedule


class InteriorScenario(BaseModel):
    """Per-cohort interior renovation scenario.

    ``cohort_id`` references ``deal.unit_cohorts[*].cohort_id`` (backfilled
    to ``cohort_<i>`` if the deal lacks explicit ids).
    """

    scope_type: Literal["unit"] = "unit"
    cohort_id: str
    scope_level: ScopeLevel
    finish_tier: FinishTier
    rent_premium_monthly: float = Field(ge=0)
    schedule: ProgramSchedule


class ExteriorScenario(BaseModel):
    scope_type: Literal["exterior"] = "exterior"
    items: list[str] = Field(min_length=1)
    schedule: ProgramSchedule
    # mirrors KB exterior_capex.bundles class_shift_to values
    expected_rent_class_shift: Optional[Literal["B-", "B", "B+"]] = None
    payback_years_target: Optional[float] = Field(default=None, ge=0)


class AmenityScenario(BaseModel):
    scope_type: Literal["amenity"] = "amenity"
    amenity_type: str
    quantity: int = Field(default=1, ge=1)
    deluxe: bool = False
    schedule: ProgramSchedule
    expected_occupancy_lift_pct: Optional[float] = Field(default=None, ge=0)
    expected_rent_premium_monthly: Optional[float] = Field(default=None, ge=0)


class DeferredMaintenanceScenario(BaseModel):
    scope_type: Literal["deferred"] = "deferred"
    items: list[str] = Field(min_length=1)
    schedule: ProgramSchedule
    age_at_replacement_years: Optional[int] = Field(default=None, ge=0)
    condition: Literal["end_of_life", "failed", "near_end_of_life"] = "end_of_life"


ScenarioUnion = Annotated[
    Union[
        InteriorScenario, ExteriorScenario,
        AmenityScenario, DeferredMaintenanceScenario,
    ],
    Field(discriminator="scope_type"),
]
