"""Tests for PropertyRepo (also handles FloorPlans)."""
import pytest

from plat_costmodel.schemas import AmenityInventory, FloorPlan, Property
from plat_costmodel.store.repo import PropertyRepo


def test_create_mints_property_id_and_persists(tmp_db):
    repo = PropertyRepo(tmp_db)
    p = Property(property_id="", total_units=12, address="1 Main St")
    saved = repo.create(p)
    assert len(saved.property_id) == 26  # ULID
    fetched = repo.get(saved.property_id)
    assert fetched is not None
    assert fetched.total_units == 12
    assert fetched.address == "1 Main St"


def test_create_with_caller_supplied_id_keeps_it(tmp_db):
    repo = PropertyRepo(tmp_db)
    p = Property(property_id="P-CUSTOM", total_units=5)
    saved = repo.create(p)
    assert saved.property_id == "P-CUSTOM"


def test_get_by_alias_returns_existing(tmp_db):
    repo = PropertyRepo(tmp_db)
    p = Property(property_id="", external_alias="123-main", total_units=4)
    saved = repo.create(p)
    found = repo.get_by_alias("123-main")
    assert found is not None
    assert found.property_id == saved.property_id


def test_get_by_alias_returns_none_when_missing(tmp_db):
    assert PropertyRepo(tmp_db).get_by_alias("does-not-exist") is None


def test_amenities_round_trip(tmp_db):
    repo = PropertyRepo(tmp_db)
    p = Property(
        property_id="", total_units=1,
        amenities=AmenityInventory(existing=["pool"], planned=["dog park"]),
    )
    saved = repo.create(p)
    fetched = repo.get(saved.property_id)
    assert fetched.amenities.existing == ["pool"]
    assert fetched.amenities.planned == ["dog park"]


def test_create_floor_plan_mints_id(tmp_db):
    repo = PropertyRepo(tmp_db)
    p = repo.create(Property(property_id="", total_units=10))
    fp = FloorPlan(
        floor_plan_id="", property_id=p.property_id,
        name="Plan B", sqft=850, bedrooms=2, bathrooms=1,
    )
    saved = repo.create_floor_plan(fp)
    assert len(saved.floor_plan_id) == 26


def test_get_floor_plans_by_property(tmp_db):
    repo = PropertyRepo(tmp_db)
    p = repo.create(Property(property_id="", total_units=10))
    repo.create_floor_plan(FloorPlan(
        floor_plan_id="", property_id=p.property_id,
        name="A", sqft=750, bedrooms=1, bathrooms=1,
    ))
    repo.create_floor_plan(FloorPlan(
        floor_plan_id="", property_id=p.property_id,
        name="B", sqft=900, bedrooms=2, bathrooms=1,
    ))
    plans = repo.get_floor_plans(p.property_id)
    assert {fp.name for fp in plans} == {"A", "B"}


def test_get_floor_plan_by_alias(tmp_db):
    repo = PropertyRepo(tmp_db)
    p = repo.create(Property(property_id="", total_units=10))
    repo.create_floor_plan(FloorPlan(
        floor_plan_id="", property_id=p.property_id, name="A",
        sqft=750, bedrooms=1, bathrooms=1, external_alias="plan-a",
    ))
    fp = repo.get_floor_plan_by_alias(p.property_id, "plan-a")
    assert fp is not None
    assert fp.name == "A"


def test_find_floor_plan_by_dims(tmp_db):
    """The (sqft, bedrooms, bathrooms) join key used by deal_projection."""
    repo = PropertyRepo(tmp_db)
    p = repo.create(Property(property_id="", total_units=10))
    repo.create_floor_plan(FloorPlan(
        floor_plan_id="", property_id=p.property_id,
        name="B", sqft=850, bedrooms=2, bathrooms=1,
    ))
    fp = repo.find_floor_plan_by_dims(p.property_id, sqft=850, bedrooms=2, bathrooms=1)
    assert fp is not None and fp.name == "B"
    assert repo.find_floor_plan_by_dims(p.property_id, sqft=999, bedrooms=2, bathrooms=1) is None
