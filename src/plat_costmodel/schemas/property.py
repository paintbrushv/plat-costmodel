"""Property and FloorPlan canonical types."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from plat_costmodel.models import PropertyClass


class FloorPlan(BaseModel):
    """A unit floor plan that one or more units share.

    First-class so the same plan can be referenced consistently across
    many ScopeRequests over months and years (the intelligence-accumulation
    goal). Cost actuals tied to a specific plan become a regression dataset.
    """

    floor_plan_id: str
    property_id: str
    name: str
    sqft: float = Field(gt=0)
    bedrooms: int = Field(ge=0)
    bathrooms: int = Field(ge=1)
    notes: str = ""
    external_alias: Optional[str] = None


class AmenityInventory(BaseModel):
    """Free-form amenity tags on a property.

    v1 stores plain strings. Slice B will introduce a typed Amenity model
    and migrate these tags; the wrapper shape stays the same.
    """

    existing: list[str] = Field(default_factory=list)
    planned: list[str] = Field(default_factory=list)


class Property(BaseModel):
    """A multifamily property — the long-lived spine.

    A property accumulates many ScopeRequests over its life (cohort-A
    renovation, exterior paint, pool addition, etc.). All keyed by
    ``property_id``.
    """

    property_id: str
    external_alias: Optional[str] = None
    address: str = ""
    market: Optional[str] = None
    year_built: Optional[int] = None
    property_class: Optional[PropertyClass] = None
    building_type: str = ""
    total_units: int = Field(ge=0)
    floor_plans: list[FloorPlan] = Field(default_factory=list)
    amenities: AmenityInventory = Field(default_factory=AmenityInventory)
