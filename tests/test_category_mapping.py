"""Tests for category_mapping module.

Covers:
  - GL exact code → internal category
  - GL code range → internal category
  - Description keyword → internal category
  - Category name field → internal category
  - Priority order (GL > category name > description > fallback)
  - Normalisation of GL codes (decimals, dashes, leading zeros)
  - CategoryMapper.register_gl_code() custom extension
  - MappingResult fields and properties
  - Module-level convenience functions
  - Integration with ingest.parse_yardi_csv (mapping_source/confidence columns)
"""

import io

import pytest

from plat_costmodel.category_mapping import (
    ALL_CATEGORIES,
    EXTERIOR_CAPEX_CATEGORIES,
    INTERIOR_UNIT_CATEGORIES,
    SYSTEMS_CATEGORIES,
    CategoryMapper,
    MappingResult,
    get_all_categories,
    get_exterior_categories,
    get_interior_categories,
    get_systems_categories,
    map_yardi_entry,
)
from plat_costmodel.ingest import parse_yardi_csv


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_csv(rows: list[str]) -> io.StringIO:
    return io.StringIO("\n".join(rows))


# ---------------------------------------------------------------------------
# MappingResult
# ---------------------------------------------------------------------------

class TestMappingResult:
    def test_is_classified_true(self):
        r = MappingResult("flooring", "gl_exact", "high", "5305")
        assert r.is_classified is True

    def test_is_classified_false_for_other(self):
        r = MappingResult("other", "fallback", "low", "")
        assert r.is_classified is False

    def test_fields_accessible(self):
        r = MappingResult("kitchen", "description", "medium", "cabinet")
        assert r.internal_category == "kitchen"
        assert r.source == "description"
        assert r.confidence == "medium"
        assert r.match_key == "cabinet"


# ---------------------------------------------------------------------------
# GL exact code matching
# ---------------------------------------------------------------------------

class TestGLExactMapping:
    def setup_method(self):
        self.mapper = CategoryMapper()

    def test_flooring_exact(self):
        r = self.mapper.map(gl_code="5305")
        assert r.internal_category == "flooring"
        assert r.source == "gl_exact"
        assert r.confidence == "high"

    def test_kitchen_exact(self):
        r = self.mapper.map(gl_code="5310")
        assert r.internal_category == "kitchen"

    def test_bathroom_exact(self):
        r = self.mapper.map(gl_code="5315")
        assert r.internal_category == "bathroom"

    def test_appliances_exact(self):
        r = self.mapper.map(gl_code="5320")
        assert r.internal_category == "appliances"
        assert r.source == "gl_exact"

    def test_hvac_exact(self):
        r = self.mapper.map(gl_code="5325")
        assert r.internal_category == "hvac"

    def test_plumbing_exact(self):
        r = self.mapper.map(gl_code="5330")
        assert r.internal_category == "plumbing"

    def test_electrical_exact(self):
        r = self.mapper.map(gl_code="5335")
        assert r.internal_category == "electrical"

    def test_roof_capex_exact(self):
        r = self.mapper.map(gl_code="5350")
        assert r.internal_category == "roof"

    def test_parking_exact(self):
        r = self.mapper.map(gl_code="5355")
        assert r.internal_category == "parking"

    def test_siding_paint_exact(self):
        r = self.mapper.map(gl_code="5365")
        assert r.internal_category == "siding_paint"

    def test_fencing_exact(self):
        r = self.mapper.map(gl_code="5370")
        assert r.internal_category == "fencing_gates"

    def test_landscaping_exact(self):
        r = self.mapper.map(gl_code="5375")
        assert r.internal_category == "landscaping"

    def test_signage_exact(self):
        r = self.mapper.map(gl_code="5380")
        assert r.internal_category == "signage_lighting"

    def test_turnover_cleaning_exact(self):
        r = self.mapper.map(gl_code="5005")
        assert r.internal_category == "cleaning"

    def test_turnover_painting_exact(self):
        r = self.mapper.map(gl_code="5015")
        assert r.internal_category == "paint"

    def test_rm_plumbing_exact(self):
        r = self.mapper.map(gl_code="5105")
        assert r.internal_category == "plumbing"

    def test_rm_hvac_exact(self):
        r = self.mapper.map(gl_code="5115")
        assert r.internal_category == "hvac"

    def test_rm_electrical_exact(self):
        r = self.mapper.map(gl_code="5110")
        assert r.internal_category == "electrical"

    def test_4xxx_flooring_exact(self):
        r = self.mapper.map(gl_code="4300")
        assert r.internal_category == "flooring"

    def test_4xxx_roof_exact(self):
        r = self.mapper.map(gl_code="4350")
        assert r.internal_category == "roof"


# ---------------------------------------------------------------------------
# GL code normalisation
# ---------------------------------------------------------------------------

class TestGLCodeNormalisation:
    def setup_method(self):
        self.mapper = CategoryMapper()

    def test_decimal_suffix_stripped(self):
        r = self.mapper.map(gl_code="5320.00")
        assert r.internal_category == "appliances"
        assert r.source == "gl_exact"

    def test_sub_account_suffix_stripped(self):
        r = self.mapper.map(gl_code="5320-001")
        assert r.internal_category == "appliances"

    def test_leading_zeros_stripped(self):
        r = self.mapper.map(gl_code="05320")
        assert r.internal_category == "appliances"

    def test_whitespace_stripped(self):
        r = self.mapper.map(gl_code=" 5320 ")
        assert r.internal_category == "appliances"

    def test_non_numeric_gl_code_falls_through(self):
        # Non-numeric GL code should not match via GL path
        r = self.mapper.map(gl_code="FLOOR-01")
        # Shouldn't crash; should fall through to description/fallback
        assert r.source in ("description", "fallback")


# ---------------------------------------------------------------------------
# GL range matching
# ---------------------------------------------------------------------------

class TestGLRangeMapping:
    def setup_method(self):
        self.mapper = CategoryMapper()

    def test_range_5100_general_repair(self):
        r = self.mapper.map(gl_code="5101")
        # Not in exact map, should hit range 5100-5104 → patch_repair
        assert r.internal_category == "patch_repair"
        assert r.source == "gl_range"
        assert r.confidence == "high"

    def test_range_5125_flooring_rm(self):
        r = self.mapper.map(gl_code="5125")
        # 5125 → flooring R&M range
        assert r.internal_category in ("flooring", "appliances")  # 5125 is in appliances range

    def test_range_5200_cleaning_contract(self):
        r = self.mapper.map(gl_code="5201")
        assert r.internal_category == "cleaning"
        assert r.source == "gl_range"

    def test_range_produces_high_confidence(self):
        r = self.mapper.map(gl_code="5302")  # In 5300-5304 → patch_repair
        assert r.confidence == "high"


# ---------------------------------------------------------------------------
# Description keyword matching
# ---------------------------------------------------------------------------

class TestDescriptionKeywordMapping:
    def setup_method(self):
        self.mapper = CategoryMapper()

    def test_lvp_flooring(self):
        r = self.mapper.map(description="LVP installation throughout unit")
        assert r.internal_category == "flooring"
        assert r.source == "description"

    def test_carpet_replacement(self):
        r = self.mapper.map(description="Carpet replacement in bedrooms")
        assert r.internal_category == "carpet"

    def test_carpet_clean_is_cleaning(self):
        r = self.mapper.map(description="Carpet cleaning and shampoo")
        assert r.internal_category == "cleaning"

    def test_cabinet_paint_kitchen(self):
        r = self.mapper.map(description="Cabinet paint and countertop install")
        assert r.internal_category == "kitchen"

    def test_vanity_bathroom(self):
        r = self.mapper.map(description="New vanity and mirror install")
        assert r.internal_category == "bathroom"

    def test_tub_resurface_bathroom(self):
        r = self.mapper.map(description="Tub resurfacing")
        assert r.internal_category == "bathroom"

    def test_interior_paint(self):
        r = self.mapper.map(description="Interior 2-coat painting")
        assert r.internal_category == "paint"

    def test_exterior_paint_siding_paint(self):
        r = self.mapper.map(description="Exterior paint full building")
        assert r.internal_category == "siding_paint"

    def test_full_appliance_package(self):
        r = self.mapper.map(description="Full appliance package stainless")
        assert r.internal_category == "appliances"

    def test_refrigerator_appliances(self):
        r = self.mapper.map(description="Refrigerator replacement")
        assert r.internal_category == "appliances"

    def test_dishwasher_appliances(self):
        r = self.mapper.map(description="Dishwasher installation")
        assert r.internal_category == "appliances"

    def test_light_fixture(self):
        r = self.mapper.map(description="New light fixture install")
        assert r.internal_category == "fixtures_doors_trim"

    def test_deep_clean(self):
        r = self.mapper.map(description="Deep clean move-out")
        assert r.internal_category == "cleaning"

    def test_drywall_patch(self):
        r = self.mapper.map(description="Drywall patch and repair")
        assert r.internal_category == "patch_repair"

    def test_make_ready(self):
        r = self.mapper.map(description="Make-ready labor")
        assert r.internal_category == "patch_repair"

    def test_hvac_mini_split(self):
        r = self.mapper.map(description="Mini split installation")
        assert r.internal_category == "hvac"

    def test_water_heater_plumbing(self):
        r = self.mapper.map(description="Water heater replacement")
        assert r.internal_category == "plumbing"

    def test_electrical_panel_upgrade(self):
        r = self.mapper.map(description="Electrical panel upgrade")
        assert r.internal_category == "electrical"

    def test_roof_replacement(self):
        r = self.mapper.map(description="Roof replacement Building A")
        assert r.internal_category == "roof"

    def test_parking_lot_resurface(self):
        r = self.mapper.map(description="Parking lot resurface and striping")
        assert r.internal_category == "parking"

    def test_asphalt_reseal(self):
        r = self.mapper.map(description="Asphalt reseal")
        assert r.internal_category == "parking"

    def test_siding_replacement(self):
        r = self.mapper.map(description="Siding replacement north elevation")
        assert r.internal_category == "siding_paint"

    def test_fence_replacement(self):
        r = self.mapper.map(description="Fence replacement perimeter")
        assert r.internal_category == "fencing_gates"

    def test_landscaping(self):
        r = self.mapper.map(description="Landscaping overhaul and sod install")
        assert r.internal_category == "landscaping"

    def test_monument_sign(self):
        r = self.mapper.map(description="Monument sign installation")
        assert r.internal_category == "signage_lighting"

    def test_galvanized_pipe_plumbing(self):
        r = self.mapper.map(description="Galvanized pipe replacement")
        assert r.internal_category == "plumbing"

    def test_unknown_description_fallback(self):
        r = self.mapper.map(description="Legal fee retainer")
        assert r.internal_category == "other"
        assert r.source == "fallback"
        assert r.confidence == "low"


# ---------------------------------------------------------------------------
# Category name field matching
# ---------------------------------------------------------------------------

class TestCategoryNameMapping:
    def setup_method(self):
        self.mapper = CategoryMapper()

    def test_exact_internal_name(self):
        r = self.mapper.map(category_name="flooring")
        assert r.internal_category == "flooring"
        assert r.confidence == "high"

    def test_exact_internal_name_case_insensitive(self):
        r = self.mapper.map(category_name="Flooring")
        assert r.internal_category == "flooring"

    def test_hvac_category_name(self):
        r = self.mapper.map(category_name="HVAC")
        assert r.internal_category == "hvac"

    def test_partial_keyword_in_category_name(self):
        r = self.mapper.map(category_name="Kitchen Renovation")
        assert r.internal_category == "kitchen"

    def test_bathroom_in_category_name(self):
        r = self.mapper.map(category_name="Bathroom Update")
        assert r.internal_category == "bathroom"

    def test_roof_in_category_name(self):
        r = self.mapper.map(category_name="Roof Replacement")
        assert r.internal_category == "roof"


# ---------------------------------------------------------------------------
# Priority ordering
# ---------------------------------------------------------------------------

class TestMappingPriority:
    def setup_method(self):
        self.mapper = CategoryMapper()

    def test_gl_exact_beats_description(self):
        # GL says appliances (5320), description says flooring
        r = self.mapper.map(gl_code="5320", description="LVP flooring install")
        assert r.internal_category == "appliances"
        assert r.source == "gl_exact"

    def test_gl_exact_beats_category_name(self):
        # GL says roof (5350), category name says kitchen
        r = self.mapper.map(gl_code="5350", category_name="Kitchen")
        assert r.internal_category == "roof"
        assert r.source == "gl_exact"

    def test_category_name_beats_description(self):
        # category_name says kitchen, description says roof
        # (no GL code)
        r = self.mapper.map(category_name="Kitchen", description="Roof replacement")
        assert r.internal_category == "kitchen"

    def test_description_used_when_no_gl_or_category(self):
        r = self.mapper.map(description="LVP flooring install")
        assert r.internal_category == "flooring"
        assert r.source == "description"

    def test_fallback_when_nothing_matches(self):
        r = self.mapper.map(description="Accounting software license")
        assert r.internal_category == "other"
        assert r.source == "fallback"

    def test_gl_range_beats_description(self):
        r = self.mapper.map(gl_code="5201", description="LVP flooring")
        assert r.internal_category == "cleaning"
        assert r.source == "gl_range"


# ---------------------------------------------------------------------------
# CategoryMapper.register_gl_code
# ---------------------------------------------------------------------------

class TestRegisterGLCode:
    def test_register_custom_code(self):
        mapper = CategoryMapper()
        mapper.register_gl_code("5999", "flooring")
        r = mapper.map(gl_code="5999")
        assert r.internal_category == "flooring"
        assert r.source == "gl_exact"

    def test_register_overrides_default(self):
        mapper = CategoryMapper()
        # 5350 defaults to roof — override to electrical
        mapper.register_gl_code("5350", "electrical")
        r = mapper.map(gl_code="5350")
        assert r.internal_category == "electrical"

    def test_register_invalid_category_raises(self):
        mapper = CategoryMapper()
        with pytest.raises(ValueError, match="Unknown internal category"):
            mapper.register_gl_code("5999", "invalid_category")

    def test_extra_gl_codes_in_constructor(self):
        mapper = CategoryMapper(extra_gl_codes={"6001": "roof"})
        r = mapper.map(gl_code="6001")
        assert r.internal_category == "roof"

    def test_extra_keywords_in_constructor_take_priority(self):
        # Add a custom keyword that would otherwise map to "other"
        mapper = CategoryMapper(extra_keywords=[("pickleball", "landscaping")])
        r = mapper.map(description="Pickleball court installation")
        assert r.internal_category == "landscaping"


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

class TestModuleLevelFunctions:
    def test_map_yardi_entry_flooring(self):
        r = map_yardi_entry(gl_code="5305")
        assert r.internal_category == "flooring"

    def test_map_yardi_entry_description_only(self):
        r = map_yardi_entry(description="Vanity replacement")
        assert r.internal_category == "bathroom"

    def test_get_all_categories(self):
        cats = get_all_categories()
        assert "flooring" in cats
        assert "other" in cats
        assert "roof" in cats

    def test_get_interior_categories(self):
        cats = get_interior_categories()
        assert "flooring" in cats
        assert "kitchen" in cats
        assert "roof" not in cats

    def test_get_exterior_categories(self):
        cats = get_exterior_categories()
        assert "roof" in cats
        assert "parking" in cats
        assert "flooring" not in cats

    def test_get_systems_categories(self):
        cats = get_systems_categories()
        assert "hvac" in cats
        assert "plumbing" in cats
        assert "flooring" not in cats

    def test_all_categories_union(self):
        all_cats = get_all_categories()
        expected = (
            get_interior_categories()
            | get_exterior_categories()
            | get_systems_categories()
            | {"other"}
        )
        assert all_cats == expected


# ---------------------------------------------------------------------------
# Integration with ingest.parse_yardi_csv
# ---------------------------------------------------------------------------

class TestIngestIntegration:
    def test_mapping_source_column_present(self):
        csv = make_csv([
            "Date,Unit,Category,Amount,Description,GL Account",
            "2025-01-15,101,Flooring,$2100.00,LVP install,5305",
        ])
        records = parse_yardi_csv(csv, "PROP1")
        assert "mapping_source" in records[0]
        assert "mapping_confidence" in records[0]

    def test_gl_code_mapped_high_confidence(self):
        csv = make_csv([
            "Date,Unit,Category,Amount,Description,GL Account",
            "2025-01-15,101,Flooring,$2100.00,LVP install,5305",
        ])
        records = parse_yardi_csv(csv, "PROP1")
        assert records[0]["internal_category"] == "flooring"
        assert records[0]["mapping_source"] == "gl_exact"
        assert records[0]["mapping_confidence"] == "high"

    def test_description_fallback_when_no_gl(self):
        csv = make_csv([
            "Date,Unit,Category,Amount,Description",
            "2025-01-15,101,Renovation,$2100.00,LVP flooring install",
        ])
        records = parse_yardi_csv(csv, "PROP1")
        assert records[0]["internal_category"] == "flooring"
        assert records[0]["mapping_source"] == "description"

    def test_unknown_maps_to_other(self):
        csv = make_csv([
            "Date,Unit,Category,Amount,Description",
            "2025-01-15,101,Legal fees,$500.00,Attorney retainer",
        ])
        records = parse_yardi_csv(csv, "PROP1")
        assert records[0]["internal_category"] == "other"
        assert records[0]["mapping_confidence"] == "low"

    def test_hvac_gl_code_in_csv(self):
        csv = make_csv([
            "Date,Unit,Category,Amount,Description,GL Account",
            "2025-02-05,102,HVAC,$3500.00,Mini split install,5325",
        ])
        records = parse_yardi_csv(csv, "PROP1")
        assert records[0]["internal_category"] == "hvac"

    def test_exterior_roof_no_unit(self):
        csv = make_csv([
            "Date,Unit,Category,Amount,Description,GL Account",
            "2025-02-10,,Roof,$45000.00,Building A full replacement,5350",
        ])
        records = parse_yardi_csv(csv, "PROP1")
        assert records[0]["internal_category"] == "roof"
        assert records[0]["unit_id"] == ""

    def test_gl_code_column_stored_in_record(self):
        csv = make_csv([
            "Date,Unit,Category,Amount,Description,GL Account",
            "2025-01-15,101,Appliances,$2200.00,Full package,5320",
        ])
        records = parse_yardi_csv(csv, "PROP1")
        assert records[0]["gl_code"] == "5320"

    def test_multiple_rows_different_categories(self):
        csv = make_csv([
            "Date,Unit,Category,Amount,Description,GL Account",
            "2025-01-15,101,Flooring,$2100.00,LVP,5305",
            "2025-01-15,101,Kitchen,$1800.00,Cabinets,5310",
            "2025-01-20,101,Bathroom,$2500.00,Vanity,5315",
            "2025-01-22,101,Paint,$950.00,2-coat interior,5345",
            "2025-01-25,101,Appliances,$2200.00,Full pkg,5320",
        ])
        records = parse_yardi_csv(csv, "PROP1")
        assert len(records) == 5
        categories = [r["internal_category"] for r in records]
        assert "flooring" in categories
        assert "kitchen" in categories
        assert "bathroom" in categories
        assert "paint" in categories
        assert "appliances" in categories

    def test_custom_mapper_injected(self):
        custom_mapper = CategoryMapper(extra_gl_codes={"9999": "flooring"})
        csv = make_csv([
            "Date,Unit,Category,Amount,Description,GL Account",
            "2025-01-15,101,Reno,$2100.00,Flooring work,9999",
        ])
        records = parse_yardi_csv(csv, "PROP1", mapper=custom_mapper)
        assert records[0]["internal_category"] == "flooring"

    def test_category_name_used_when_no_gl(self):
        """Category column (without GL code) drives mapping via keyword match."""
        csv = make_csv([
            "Date,Unit,Category,Amount,Description",
            "2025-01-15,101,Bathroom,$2500.00,Vanity and tub",
        ])
        records = parse_yardi_csv(csv, "PROP1")
        assert records[0]["internal_category"] == "bathroom"

    def test_backward_compat_no_gl_column(self):
        """CSV without GL Account column should not crash."""
        csv = make_csv([
            "Date,Unit,Category,Amount,Description",
            "2025-01-15,101,Flooring,$2100.00,LVP",
            "2025-01-15,101,Kitchen,$1800.00,Cabinets",
        ])
        records = parse_yardi_csv(csv, "PROP1")
        assert len(records) == 2
        # Falls back to category/description matching
        assert records[0]["internal_category"] == "flooring"
        assert records[1]["internal_category"] == "kitchen"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def setup_method(self):
        self.mapper = CategoryMapper()

    def test_none_inputs_returns_fallback(self):
        r = self.mapper.map(gl_code=None, description=None, category_name=None)
        assert r.internal_category == "other"
        assert r.source == "fallback"

    def test_empty_string_inputs_return_fallback(self):
        r = self.mapper.map(gl_code="", description="", category_name="")
        assert r.internal_category == "other"

    def test_very_long_description(self):
        desc = "LVP flooring installation throughout entire unit " * 20
        r = self.mapper.map(description=desc)
        assert r.internal_category == "flooring"

    def test_all_gl_exact_codes_produce_valid_category(self):
        from plat_costmodel.category_mapping import _GL_EXACT
        mapper = CategoryMapper()
        for code, expected_cat in _GL_EXACT.items():
            r = mapper.map(gl_code=code)
            assert r.internal_category in ALL_CATEGORIES, \
                f"GL code {code} mapped to invalid category '{r.internal_category}'"

    def test_all_mapped_categories_are_valid(self):
        """Every category referenced in the mappings is in ALL_CATEGORIES."""
        from plat_costmodel.category_mapping import _GL_RANGES, _DESCRIPTION_KEYWORDS
        for _low, _high, cat in _GL_RANGES:
            assert cat in ALL_CATEGORIES, f"Range category '{cat}' not in ALL_CATEGORIES"
        for _kw, cat in _DESCRIPTION_KEYWORDS:
            assert cat in ALL_CATEGORIES, f"Keyword category '{cat}' not in ALL_CATEGORIES"

    def test_whitespace_only_gl_code(self):
        """Whitespace-only GL code should fall through to description/fallback."""
        r = self.mapper.map(gl_code="   ", description="LVP flooring")
        assert r.internal_category == "flooring"
        assert r.source == "description"

    def test_whitespace_only_all_fields(self):
        r = self.mapper.map(gl_code="   ", description="   ", category_name="   ")
        assert r.internal_category == "other"
        assert r.source == "fallback"

    def test_description_keyword_case_insensitive(self):
        """Keyword matching should be case-insensitive for descriptions."""
        upper = self.mapper.map(description="LVP FLOORING INSTALL")
        lower = self.mapper.map(description="lvp flooring install")
        mixed = self.mapper.map(description="Lvp Flooring Install")
        assert upper.internal_category == "flooring"
        assert lower.internal_category == "flooring"
        assert mixed.internal_category == "flooring"

    def test_description_case_insensitive_hvac(self):
        assert self.mapper.map(description="HVAC REPLACEMENT").internal_category == "hvac"
        assert self.mapper.map(description="hvac replacement").internal_category == "hvac"

    def test_other_never_returns_none(self):
        """Fallback should always return 'other', never None."""
        garbage_inputs = [
            "xyzzy gibberish 12345",
            "!@#$%^&*()",
            "a",
            " ",
            "the quick brown fox",
            "invoice #12345 misc charges",
        ]
        for desc in garbage_inputs:
            r = self.mapper.map(description=desc)
            assert r.internal_category is not None, f"Got None for '{desc}'"
            assert isinstance(r.internal_category, str)
            # Must be a valid category
            assert r.internal_category in ALL_CATEGORIES, (
                f"'{desc}' → '{r.internal_category}' not in ALL_CATEGORIES"
            )

    def test_no_args_returns_other(self):
        """Calling map() with no arguments should return 'other' fallback."""
        r = self.mapper.map()
        assert r.internal_category == "other"
        assert r.source == "fallback"


# ---------------------------------------------------------------------------
# Hardening: map_yardi_row convenience method
# ---------------------------------------------------------------------------

class TestMapYardiRow:
    def setup_method(self):
        self.mapper = CategoryMapper()

    def test_standard_yardi_columns(self):
        row = {
            "GL Account": "5305",
            "Category": "Flooring",
            "Description": "LVP install",
        }
        r = self.mapper.map_yardi_row(row)
        assert r.internal_category == "flooring"
        assert r.source == "gl_exact"

    def test_alternative_gl_column_names(self):
        """Should recognize 'GL Code', 'Account Code', 'Account #'."""
        for col in ["GL Code", "Account Code", "Account #", "Account"]:
            row = {col: "5320", "Description": "Appliance pkg"}
            r = self.mapper.map_yardi_row(row)
            assert r.internal_category == "appliances", f"Failed for column '{col}'"

    def test_alternative_description_columns(self):
        for col in ["Description", "Memo", "Notes"]:
            row = {col: "LVP flooring install"}
            r = self.mapper.map_yardi_row(row)
            assert r.internal_category == "flooring", f"Failed for column '{col}'"

    def test_alternative_category_columns(self):
        for col in ["Category", "Expense Category", "GL Description"]:
            row = {col: "Bathroom"}
            r = self.mapper.map_yardi_row(row)
            assert r.internal_category == "bathroom", f"Failed for column '{col}'"

    def test_empty_row_returns_fallback(self):
        r = self.mapper.map_yardi_row({})
        assert r.internal_category == "other"

    def test_row_with_numeric_gl_code(self):
        """Some CSVs parse GL codes as integers, not strings."""
        row = {"GL Account": 5305, "Description": "Flooring work"}
        r = self.mapper.map_yardi_row(row)
        assert r.internal_category == "flooring"


# ---------------------------------------------------------------------------
# Hardening: priority tier isolation
# ---------------------------------------------------------------------------

class TestPriorityTierIsolation:
    """Test each priority tier independently by providing only that field."""

    def setup_method(self):
        self.mapper = CategoryMapper()

    def test_gl_exact_alone(self):
        r = self.mapper.map(gl_code="5305")
        assert r.source == "gl_exact"
        assert r.confidence == "high"

    def test_gl_range_alone(self):
        """GL code not in exact map but in range → gl_range."""
        r = self.mapper.map(gl_code="5302")
        assert r.source == "gl_range"
        assert r.confidence == "high"

    def test_category_name_alone(self):
        r = self.mapper.map(category_name="Bathroom")
        assert r.internal_category == "bathroom"

    def test_description_alone(self):
        r = self.mapper.map(description="LVP flooring install")
        assert r.source == "description"

    def test_fallback_alone(self):
        r = self.mapper.map(description="something completely unrelated to renovation")
        # "repair" would match patch_repair, so use truly unrelated text
        r = self.mapper.map(description="quarterly tax filing")
        assert r.source == "fallback"
        assert r.internal_category == "other"
