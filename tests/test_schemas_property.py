"""Tests for Property / FloorPlan / AmenityInventory schemas."""
import pytest
from pydantic import ValidationError

from plat_costmodel.schemas.property import (
    AmenityInventory,
    FloorPlan,
    Property,
)
from plat_costmodel.models import PropertyClass


def test_floor_plan_minimal():
    fp = FloorPlan(
        floor_plan_id="fp1",
        property_id="p1",
        name="Plan B",
        sqft=850.0,
        bedrooms=2,
        bathrooms=1,
    )
    assert fp.notes == ""
    assert fp.external_alias is None


def test_floor_plan_round_trip():
    original = FloorPlan(
        floor_plan_id="fp1",
        property_id="p1",
        name="Plan B",
        sqft=850.0,
        bedrooms=2,
        bathrooms=1,
        notes="bay window, washer hookup",
        external_alias="plan-b",
    )
    assert FloorPlan.model_validate(original.model_dump()) == original


def test_floor_plan_rejects_zero_sqft():
    with pytest.raises(ValidationError):
        FloorPlan(floor_plan_id="x", property_id="p", name="bad",
                  sqft=0, bedrooms=1, bathrooms=1)


def test_amenity_inventory_defaults_empty():
    inv = AmenityInventory()
    assert inv.existing == []
    assert inv.planned == []


def test_property_minimal():
    p = Property(property_id="p1", total_units=12)
    assert p.external_alias is None
    assert p.address == ""
    assert p.market is None
    assert p.year_built is None
    assert p.property_class is None
    assert p.building_type == ""
    assert p.floor_plans == []
    assert p.amenities == AmenityInventory()


def test_property_full_round_trip():
    fp = FloorPlan(floor_plan_id="fp1", property_id="p1", name="A",
                   sqft=750, bedrooms=1, bathrooms=1)
    p = Property(
        property_id="p1",
        external_alias="123-main-st",
        address="123 Main St",
        market="dallas",
        year_built=1985,
        property_class=PropertyClass.C,
        building_type="garden",
        total_units=12,
        floor_plans=[fp],
        amenities=AmenityInventory(existing=["pool"], planned=["dog park"]),
    )
    assert Property.model_validate(p.model_dump()) == p


def test_property_total_units_must_be_non_negative():
    with pytest.raises(ValidationError):
        Property(property_id="p", total_units=-1)
