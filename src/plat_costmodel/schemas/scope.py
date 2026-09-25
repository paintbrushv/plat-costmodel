"""ScopeRequest and friends — what to estimate, for which property cohort.

Slice B: ``ScopeRequest.cohort`` is a discriminated union over four cohort
variants, distinguished by the ``scope_type`` literal. ``program_type`` and
``cohort.scope_type`` are kept consistent by a model_validator — the former
is the persisted/queryable header, the latter is the Pydantic discriminator.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator

from plat_costmodel.models import FinishTier, ScopeLevel


class ProgramType(str, Enum):
    """Program categories. All four variants are live as of slice B."""

    INTERIOR_RENOVATION = "interior_renovation"
    EXTERIOR_RENOVATION = "exterior_renovation"
    AMENITY_ADDITION = "amenity_addition"
    DEFERRED_MAINTENANCE = "deferred_maintenance"


# Maps ProgramType → expected cohort.scope_type for cross-field validation.
_PROGRAM_TYPE_TO_SCOPE_TYPE: dict[ProgramType, str] = {
    ProgramType.INTERIOR_RENOVATION: "unit",
    ProgramType.EXTERIOR_RENOVATION: "exterior",
    ProgramType.AMENITY_ADDITION: "amenity",
    ProgramType.DEFERRED_MAINTENANCE: "deferred",
}


class UnitCohort(BaseModel):
    """Subset of property units this ScopeRequest is estimating against."""

    scope_type: Literal["unit"] = "unit"
    floor_plan_id: str
    unit_count: int = Field(ge=1)
    scope_level: ScopeLevel
    finish_tier: FinishTier
    current_monthly_rent: float = Field(ge=0)
    target_monthly_rent: float = Field(ge=0)


class ExteriorCohort(BaseModel):
    """Property-scale exterior program (envelope, parking, landscape, etc.).

    ``items`` are atomic categories from ``knowledge_base.yaml::exterior_capex.items``
    (validated at estimate time, not here). ``total_units`` is needed to scale
    the per-unit cost ranges in the KB into property-level totals.
    """

    scope_type: Literal["exterior"] = "exterior"
    items: list[str] = Field(min_length=1)
    total_units: int = Field(ge=1)
    roof_age_years: Optional[int] = Field(default=None, ge=0)
    parking_condition: Optional[Literal["good", "fair", "poor"]] = None
    # mirrors KB exterior_capex.bundles class_shift_to values
    expected_rent_class_shift: Optional[Literal["B-", "B", "B+"]] = None
    payback_years_target: Optional[float] = Field(default=None, ge=0)


class AmenityCohort(BaseModel):
    """One amenity addition (pool, dog park, EV chargers, etc.).

    ``amenity_type`` is a key in ``knowledge_base.yaml::amenity_catalog``
    (validated at estimate time). ``quantity`` multiplies install + opex
    where the catalog entry is per-unit (e.g. EV chargers).
    """

    scope_type: Literal["amenity"] = "amenity"
    amenity_type: str
    quantity: int = Field(default=1, ge=1)
    deluxe: bool = False
    expected_occupancy_lift_pct: Optional[float] = Field(default=None, ge=0)
    expected_rent_premium_monthly: Optional[float] = Field(default=None, ge=0)


class DeferredMaintenanceCohort(BaseModel):
    """End-of-life replacements triggered by age + condition, not value-add.

    ``items`` are keys in ``knowledge_base.yaml::deferred_maintenance``.
    """

    scope_type: Literal["deferred"] = "deferred"
    items: list[str] = Field(min_length=1)
    total_units: int = Field(ge=1)
    age_at_replacement_years: Optional[int] = Field(default=None, ge=0)
    condition: Literal["end_of_life", "failed", "near_end_of_life"] = "end_of_life"


CohortUnion = Annotated[
    Union[UnitCohort, ExteriorCohort, AmenityCohort, DeferredMaintenanceCohort],
    Field(discriminator="scope_type"),
]


class ProgramSchedule(BaseModel):
    start_month: str  # YYYY-MM
    monthly_pace: int = Field(ge=1)
    downtime_days: int = Field(ge=0, default=21)


class ScopeRequest(BaseModel):
    """A single program request: one cohort, one schedule, one program type.

    Cross-field invariant: ``program_type`` and ``cohort.scope_type`` must
    correspond per ``_PROGRAM_TYPE_TO_SCOPE_TYPE``. The discriminator routes
    parsing of nested cohort dicts; the validator catches mismatched pairings
    in already-built objects.

    Backward-compat: callers that omit ``cohort.scope_type`` in the raw dict
    get it injected automatically from ``program_type`` (slice-A contract).
    """

    scope_request_id: Optional[str] = None  # ULID minted on persist if None
    property_id: str
    program_type: ProgramType
    cohort: CohortUnion
    schedule: ProgramSchedule
    requested_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    requested_by: str = ""

    @model_validator(mode="before")
    @classmethod
    def _inject_scope_type_if_missing(cls, data: object) -> object:
        """Backfill ``cohort.scope_type`` from ``program_type`` when absent.

        This preserves the slice-A wire format where callers send a plain
        UnitCohort dict without an explicit ``scope_type`` key.
        """
        if not isinstance(data, dict):
            return data
        cohort = data.get("cohort")
        program_type_raw = data.get("program_type")
        if isinstance(cohort, dict) and "scope_type" not in cohort and program_type_raw is not None:
            # Resolve program_type string → ProgramType if needed
            try:
                pt = ProgramType(program_type_raw)
            except ValueError:
                return data  # let normal validation report the bad value
            # Copy both the cohort dict and the outer data dict to avoid
            # mutating the caller's original payload.
            cohort = {**cohort, "scope_type": _PROGRAM_TYPE_TO_SCOPE_TYPE[pt]}
            data = {**data, "cohort": cohort}
        return data

    @model_validator(mode="after")
    def _check_program_cohort_alignment(self) -> "ScopeRequest":
        expected = _PROGRAM_TYPE_TO_SCOPE_TYPE[self.program_type]
        if self.cohort.scope_type != expected:
            raise ValueError(
                f"program_type={self.program_type.value} requires "
                f"cohort.scope_type={expected!r}, got {self.cohort.scope_type!r}"
            )
        return self
