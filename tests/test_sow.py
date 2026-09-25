"""Tests for scope of work generation."""

from plat_costmodel.sow import generate_sow
from plat_costmodel.models import ScopeLevel, FinishTier


class TestSOWGeneration:
    def test_standard_basic_has_all_categories(self):
        sow = generate_sow(850, 2, 1, "standard_value_add", "basic")
        categories = {li.category for li in sow.line_items}
        assert "flooring" in categories
        assert "kitchen" in categories
        assert "bathroom" in categories
        assert "paint" in categories
        assert "appliances" in categories
        assert "fixtures_doors_trim" in categories

    def test_standard_upgraded_has_granite(self):
        sow = generate_sow(850, 2, 1, "standard_value_add", "upgraded")
        kitchen = next(li for li in sow.line_items if li.category == "kitchen")
        assert "granite" in kitchen.material_spec.lower()

    def test_standard_basic_has_butcher_block(self):
        sow = generate_sow(850, 2, 1, "standard_value_add", "basic")
        kitchen = next(li for li in sow.line_items if li.category == "kitchen")
        assert "butcher block" in kitchen.material_spec.lower() or "laminate" in kitchen.material_spec.lower()

    def test_upgraded_appliances_stainless(self):
        sow = generate_sow(850, 2, 1, "standard_value_add", "upgraded")
        appl = next(li for li in sow.line_items if li.category == "appliances")
        assert "stainless" in appl.material_spec.lower()

    def test_basic_appliances_black(self):
        sow = generate_sow(850, 2, 1, "standard_value_add", "basic")
        appl = next(li for li in sow.line_items if li.category == "appliances")
        assert "black" in appl.material_spec.lower()

    def test_bathroom_quantity_notes(self):
        sow = generate_sow(850, 2, 2, "standard_value_add")
        bath = next(li for li in sow.line_items if li.category == "bathroom")
        assert "2 bathroom" in bath.quantity_notes

    def test_light_scope_has_items(self):
        sow = generate_sow(850, 2, 1, "light")
        assert len(sow.line_items) >= 3
        categories = {li.category for li in sow.line_items}
        assert "paint" in categories
        assert "cleaning" in categories

    def test_general_conditions_present(self):
        sow = generate_sow(850, 2, 1, "standard_value_add")
        assert "dumpster" in sow.general_conditions.lower()
        assert "warranty" in sow.general_conditions.lower()

    def test_all_items_have_material_spec(self):
        sow = generate_sow(850, 2, 1, "standard_value_add", "upgraded")
        for li in sow.line_items:
            assert li.material_spec, f"{li.category} missing material_spec"

    def test_all_items_have_quality_standard(self):
        sow = generate_sow(850, 2, 1, "standard_value_add", "basic")
        for li in sow.line_items:
            assert li.quality_standard, f"{li.category} missing quality_standard"

    def test_property_address_carried_through(self):
        sow = generate_sow(850, 2, 1, "standard_value_add", property_address="123 Main St")
        assert sow.property_address == "123 Main St"
