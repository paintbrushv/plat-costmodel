"""PricingSnapshot and ScopeEstimate variants — frozen, persisted estimate records.

Slice B: ``ScopeEstimate`` is the legacy name; the slice-A class is now
``InteriorScopeEstimate`` with ``scope_type: Literal["unit"]``. Three new
variants — Exterior, Amenity, DeferredMaintenance — are joined in
``ScopeEstimateUnion``. The legacy ``ScopeEstimate`` symbol is preserved as
an alias for ``InteriorScopeEstimate`` (concrete type, not the union) so
existing slice-A callers' attribute access (``est.unit_estimates``,
``est.roi_result``) remains type-stable.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, Field

from plat_costmodel.models import LineItem, RiskFlag, ROIResult, UnitEstimate
from plat_costmodel.schemas.results import (
    OccupancyLiftResult,
    RentPremiumResult,
)


class PricingSnapshot(BaseModel):
    """Frozen pricing context for an estimate."""

    snapshot_id: str
    captured_at: datetime
    kb_version_hash: str
    external_feeds: dict[str, Any] = Field(default_factory=dict)  # reserved for slice C (RSMeans, ConstructConnect)


class InteriorScopeEstimate(BaseModel):
    """Result of estimating a UnitCohort scope (interior unit renovation).

    This is the slice-A ``ScopeEstimate`` with the ``scope_type`` discriminator
    literal added. The legacy ``ScopeEstimate`` name is kept as an alias for
    backwards compat (see bottom of module).
    """

    scope_type: Literal["unit"] = "unit"
    estimate_id: str
    scope_request_id: str
    property_id: str  # denormalized for query convenience
    floor_plan_id: str  # denormalized from cohort.floor_plan_id
    pricing_snapshot_id: str
    unit_estimates: list[UnitEstimate]
    cohort_total_low: float
    cohort_total_high: float
    per_unit_average_low: float
    per_unit_average_high: float
    roi_result: ROIResult
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    sanity_flags: list[str] = Field(default_factory=list)
    estimated_at: datetime


class ExteriorScopeEstimate(BaseModel):
    """Result of estimating an ExteriorCohort scope (envelope/site work)."""

    scope_type: Literal["exterior"] = "exterior"
    estimate_id: str
    scope_request_id: str
    property_id: str
    pricing_snapshot_id: str
    line_items: list[LineItem]  # one per cohort.items entry
    total_low: float
    total_high: float
    per_unit_low: float  # total / cohort.total_units
    per_unit_high: float
    payback_years_estimated: Optional[float] = None
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    sanity_flags: list[str] = Field(default_factory=list)
    estimated_at: datetime


class AmenityScopeEstimate(BaseModel):
    """Result of estimating an AmenityCohort scope (one amenity addition)."""

    scope_type: Literal["amenity"] = "amenity"
    estimate_id: str
    scope_request_id: str
    property_id: str
    pricing_snapshot_id: str
    amenity_type: str
    install_cost_low: float
    install_cost_high: float
    annual_opex_low: Optional[float] = None
    annual_opex_high: Optional[float] = None
    expected_occupancy_lift_result: Optional[OccupancyLiftResult] = None
    expected_rent_premium_result: Optional[RentPremiumResult] = None
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    sanity_flags: list[str] = Field(default_factory=list)
    estimated_at: datetime


class DeferredMaintenanceEstimate(BaseModel):
    """Result of estimating a DeferredMaintenanceCohort scope."""

    scope_type: Literal["deferred"] = "deferred"
    estimate_id: str
    scope_request_id: str
    property_id: str
    pricing_snapshot_id: str
    line_items: list[LineItem]
    total_low: float
    total_high: float
    per_unit_low: float
    per_unit_high: float
    triggered_by: str  # human-readable reason: "roof age 25yr", "hvac eol", etc.
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    sanity_flags: list[str] = Field(default_factory=list)
    estimated_at: datetime


ScopeEstimateUnion = Annotated[
    Union[
        InteriorScopeEstimate,
        ExteriorScopeEstimate,
        AmenityScopeEstimate,
        DeferredMaintenanceEstimate,
    ],
    Field(discriminator="scope_type"),
]


# Backwards-compat alias for slice-A code paths. Points at the concrete
# Interior variant (not the union) so attribute access stays type-stable
# in callers that already do est.unit_estimates / est.roi_result.
ScopeEstimate = InteriorScopeEstimate
