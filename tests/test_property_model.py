"""Tests for the Property first-class entity (Track 4).

Covers:
  - Property and UnitSpec model construction and validation
  - to_unit_dicts() expansion (count > 1, single units, mixed)
  - units_in_mix computed property
  - estimate_property with Property model
  - MCP tool estimate_property_from_model
  - Edge cases: empty unit_mix, 0 total_units, property with no optional fields
"""

import pytest
from pydantic import ValidationError

from plat_costmodel.estimator import estimate_property
from plat_costmodel.models import (
    FinishTier,
    PropertyEstimateInput,
    PropertyClass,
    PropertyEstimate,
    ScopeLevel,
    UnitSpec,
)
from plat_costmodel.server import estimate_property_from_model


# ---------------------------------------------------------------------------
# UnitSpec construction
# ---------------------------------------------------------------------------

class TestUnitSpec:
    def test_basic_construction(self):
        spec = UnitSpec(sqft=850, bedrooms=2, bathrooms=1)
        assert spec.sqft == 850
        assert spec.bedrooms == 2
        assert spec.bathrooms == 1
        assert spec.scope_level == ScopeLevel.STANDARD_VALUE_ADD
        assert spec.finish_tier == FinishTier.BASIC
        assert spec.count == 1

    def test_count_gt_1(self):
        spec = UnitSpec(sqft=850, bedrooms=2, bathrooms=1, count=12)
        assert spec.count == 12

    def test_zero_sqft_rejected(self):
        with pytest.raises(ValidationError):
            UnitSpec(sqft=0, bedrooms=2, bathrooms=1)

    def test_negative_sqft_rejected(self):
        with pytest.raises(ValidationError):
            UnitSpec(sqft=-100, bedrooms=2, bathrooms=1)

    def test_zero_bathrooms_rejected(self):
        with pytest.raises(ValidationError):
            UnitSpec(sqft=850, bedrooms=2, bathrooms=0)

    def test_zero_bedrooms_allowed(self):
        """Studios have 0 bedrooms."""
        spec = UnitSpec(sqft=500, bedrooms=0, bathrooms=1)
        assert spec.bedrooms == 0

    def test_zero_count_rejected(self):
        with pytest.raises(ValidationError):
            UnitSpec(sqft=850, bedrooms=2, bathrooms=1, count=0)

    def test_with_unit_id(self):
        spec = UnitSpec(unit_id="101A", sqft=850, bedrooms=2, bathrooms=1)
        assert spec.unit_id == "101A"

    def test_custom_scope_and_finish(self):
        spec = UnitSpec(
            sqft=600, bedrooms=1, bathrooms=1,
            scope_level=ScopeLevel.LIGHT, finish_tier=FinishTier.UPGRADED,
        )
        assert spec.scope_level == ScopeLevel.LIGHT
        assert spec.finish_tier == FinishTier.UPGRADED


# ---------------------------------------------------------------------------
# Property construction
# ---------------------------------------------------------------------------

class TestProperty:
    def test_minimal_construction(self):
        prop = PropertyEstimateInput(property_id="PROP001", total_units=50)
        assert prop.property_id == "PROP001"
        assert prop.total_units == 50
        assert prop.unit_mix == []
        assert prop.year_built is None
        assert prop.property_class is None
        assert prop.market is None
        assert prop.building_type == ""

    def test_full_construction(self):
        prop = PropertyEstimateInput(
            property_id="PROP001",
            year_built=1985,
            property_class=PropertyClass.C,
            market="dallas",
            total_units=100,
            unit_mix=[
                UnitSpec(sqft=600, bedrooms=1, bathrooms=1, count=30),
                UnitSpec(sqft=850, bedrooms=2, bathrooms=1, count=50),
                UnitSpec(sqft=1050, bedrooms=3, bathrooms=2, count=20),
            ],
            building_type="garden",
            exterior_items=["roof", "parking"],
        )
        assert prop.year_built == 1985
        assert prop.property_class == PropertyClass.C
        assert prop.market == "dallas"
        assert prop.building_type == "garden"
        assert len(prop.unit_mix) == 3
        assert prop.exterior_items == ["roof", "parking"]

    def test_negative_total_units_rejected(self):
        with pytest.raises(ValidationError):
            PropertyEstimateInput(property_id="PROP001", total_units=-1)

    def test_zero_total_units_allowed(self):
        prop = PropertyEstimateInput(property_id="PROP001", total_units=0)
        assert prop.total_units == 0


# ---------------------------------------------------------------------------
# Property.units_in_mix
# ---------------------------------------------------------------------------

class TestUnitsInMix:
    def test_empty_mix(self):
        prop = PropertyEstimateInput(property_id="P1", total_units=50)
        assert prop.units_in_mix == 0

    def test_single_spec_count_1(self):
        prop = PropertyEstimateInput(
            property_id="P1", total_units=1,
            unit_mix=[UnitSpec(sqft=850, bedrooms=2, bathrooms=1)],
        )
        assert prop.units_in_mix == 1

    def test_multiple_specs_with_counts(self):
        prop = PropertyEstimateInput(
            property_id="P1", total_units=100,
            unit_mix=[
                UnitSpec(sqft=600, bedrooms=1, bathrooms=1, count=30),
                UnitSpec(sqft=850, bedrooms=2, bathrooms=1, count=50),
                UnitSpec(sqft=1050, bedrooms=3, bathrooms=2, count=20),
            ],
        )
        assert prop.units_in_mix == 100


# ---------------------------------------------------------------------------
# Property.to_unit_dicts()
# ---------------------------------------------------------------------------

class TestToUnitDicts:
    def test_single_unit_preserves_id(self):
        prop = PropertyEstimateInput(
            property_id="P1", total_units=1,
            unit_mix=[UnitSpec(unit_id="101A", sqft=850, bedrooms=2, bathrooms=1)],
        )
        dicts = prop.to_unit_dicts()
        assert len(dicts) == 1
        assert dicts[0]["unit_id"] == "101A"
        assert dicts[0]["sqft"] == 850
        assert dicts[0]["bedrooms"] == 2
        assert dicts[0]["bathrooms"] == 1

    def test_count_gt_1_expands(self):
        prop = PropertyEstimateInput(
            property_id="P1", total_units=5,
            unit_mix=[UnitSpec(sqft=850, bedrooms=2, bathrooms=1, count=5)],
        )
        dicts = prop.to_unit_dicts()
        assert len(dicts) == 5
        # Should have unique sequential IDs
        ids = [d["unit_id"] for d in dicts]
        assert len(set(ids)) == 5

    def test_mixed_specs_expand_correctly(self):
        prop = PropertyEstimateInput(
            property_id="P1", total_units=15,
            unit_mix=[
                UnitSpec(sqft=600, bedrooms=1, bathrooms=1, count=5),
                UnitSpec(sqft=850, bedrooms=2, bathrooms=1, count=7),
                UnitSpec(sqft=1050, bedrooms=3, bathrooms=2, count=3),
            ],
        )
        dicts = prop.to_unit_dicts()
        assert len(dicts) == 15
        # All IDs unique
        ids = [d["unit_id"] for d in dicts]
        assert len(set(ids)) == 15

    def test_scope_and_finish_carried_through(self):
        prop = PropertyEstimateInput(
            property_id="P1", total_units=1,
            unit_mix=[
                UnitSpec(sqft=600, bedrooms=1, bathrooms=1,
                         scope_level=ScopeLevel.LIGHT, finish_tier=FinishTier.UPGRADED),
            ],
        )
        dicts = prop.to_unit_dicts()
        assert dicts[0]["scope_level"] == "light"
        assert dicts[0]["finish_tier"] == "upgraded"

    def test_empty_mix_returns_empty(self):
        prop = PropertyEstimateInput(property_id="P1", total_units=0)
        assert prop.to_unit_dicts() == []


# ---------------------------------------------------------------------------
# estimate_property with Property model
# ---------------------------------------------------------------------------

class TestEstimateProperty:
    def test_produces_property_estimate(self):
        prop = PropertyEstimateInput(
            property_id="PROP001",
            total_units=10,
            year_built=1985,
            unit_mix=[
                UnitSpec(sqft=850, bedrooms=2, bathrooms=1, count=2),
            ],
        )
        result = estimate_property(prop)
        assert isinstance(result, PropertyEstimate)
        assert result.property_id == "PROP001"
        assert result.total_units == 10

    def test_two_unit_types_correct_rollup(self):
        """Two distinct unit specs should produce per-spec estimates with correct totals."""
        prop = PropertyEstimateInput(
            property_id="PROP001",
            total_units=10,
            year_built=1985,
            property_class=PropertyClass.C,
            market="dallas",
            unit_mix=[
                UnitSpec(unit_id="U001", sqft=850, bedrooms=2, bathrooms=1),
                UnitSpec(unit_id="U002", sqft=600, bedrooms=1, bathrooms=1),
            ],
        )
        result = estimate_property(prop)

        assert result.units_needing_work == 2
        assert len(result.unit_estimates) == 2
        assert result.total_renovation_high > 0
        assert result.total_renovation_high == sum(
            e.total_high for e in result.unit_estimates
        ) + result.exterior_capex_high

    def test_with_exterior_items(self):
        prop = PropertyEstimateInput(
            property_id="PROP001",
            total_units=10,
            unit_mix=[UnitSpec(sqft=850, bedrooms=2, bathrooms=1)],
            exterior_items=["roof", "parking"],
        )
        result = estimate_property(prop)
        assert result.exterior_capex_high > 0

    def test_empty_unit_mix(self):
        prop = PropertyEstimateInput(property_id="PROP001", total_units=10)
        result = estimate_property(prop)
        assert result.units_needing_work == 0
        assert result.exterior_capex_high > 0  # exterior still applies

    def test_count_expansion(self):
        """count=5 in spec should produce 5 unit estimates."""
        prop = PropertyEstimateInput(
            property_id="PROP001",
            total_units=5,
            unit_mix=[UnitSpec(sqft=850, bedrooms=2, bathrooms=1, count=5)],
        )
        result = estimate_property(prop)
        assert result.units_needing_work == 5
        assert len(result.unit_estimates) == 5

    def test_risk_flags_from_year_built(self):
        prop = PropertyEstimateInput(
            property_id="PROP001",
            total_units=10,
            year_built=1975,
            unit_mix=[UnitSpec(sqft=850, bedrooms=2, bathrooms=1)],
        )
        result = estimate_property(prop)
        assert len(result.risk_flags) > 0


# ---------------------------------------------------------------------------
# MCP tool — estimate_property_from_model
# ---------------------------------------------------------------------------

class TestMCPPropertyTool:
    def test_returns_dict(self):
        result = estimate_property_from_model({
            "property_id": "PROP001",
            "total_units": 10,
            "unit_mix": [
                {"sqft": 850, "bedrooms": 2, "bathrooms": 1, "count": 2},
            ],
        })
        assert isinstance(result, dict)
        assert result["property_id"] == "PROP001"
        assert result["total_units"] == 10
        assert result["units_needing_work"] == 2

    def test_full_property_dict(self):
        result = estimate_property_from_model({
            "property_id": "PROP001",
            "year_built": 1985,
            "property_class": "C",
            "market": "dallas",
            "total_units": 50,
            "building_type": "garden",
            "unit_mix": [
                {"sqft": 600, "bedrooms": 1, "bathrooms": 1, "count": 20},
                {"sqft": 850, "bedrooms": 2, "bathrooms": 1, "count": 20},
                {"sqft": 1050, "bedrooms": 3, "bathrooms": 2, "count": 10},
            ],
            "exterior_items": ["roof", "parking"],
        })
        assert result["units_needing_work"] == 50
        assert result["exterior_capex_high"] > 0
        assert result["total_renovation_high"] > 0

    def test_invalid_property_raises(self):
        # @_validated wraps the tool: bad input returns a ValidationProblem dict
        # instead of raising (prevents FastMCP TaskGroup swallowing raw exceptions).
        result = estimate_property_from_model({"total_units": 10})  # missing property_id
        assert isinstance(result, dict)
        assert result.get("error_type") in ("validation_error", "not_found", "value_error")


# ---------------------------------------------------------------------------
# Property JSON serialization
# ---------------------------------------------------------------------------

class TestPropertySerialization:
    def test_round_trip(self):
        prop = PropertyEstimateInput(
            property_id="PROP001",
            year_built=1985,
            property_class=PropertyClass.C,
            market="dallas",
            total_units=100,
            unit_mix=[
                UnitSpec(sqft=850, bedrooms=2, bathrooms=1, count=50),
            ],
            building_type="garden",
        )
        data = prop.model_dump()
        restored = PropertyEstimateInput(**data)
        assert restored.property_id == prop.property_id
        assert restored.year_built == prop.year_built
        assert restored.total_units == prop.total_units
        assert len(restored.unit_mix) == 1
        assert restored.unit_mix[0].count == 50

    def test_json_round_trip(self):
        import json
        prop = PropertyEstimateInput(
            property_id="PROP001",
            total_units=10,
            unit_mix=[UnitSpec(sqft=850, bedrooms=2, bathrooms=1)],
        )
        json_str = prop.model_dump_json()
        data = json.loads(json_str)
        restored = PropertyEstimateInput(**data)
        assert restored.property_id == "PROP001"
