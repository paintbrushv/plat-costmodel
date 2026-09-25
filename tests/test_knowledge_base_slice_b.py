"""Smoke tests for slice B knowledge-base sections.

These verify the YAML structure exists and has the expected keys/types.
Estimator-side consumption lands in slice B PRs 3-5.
"""
from pathlib import Path

import pytest
import yaml


@pytest.fixture(scope="module")
def kb() -> dict:
    path = (
        Path(__file__).resolve().parents[1]
        / "src" / "plat_costmodel" / "data" / "knowledge_base.yaml"
    )
    with path.open() as f:
        return yaml.safe_load(f)


def test_exterior_capex_items_unchanged(kb):
    """Slice A section must not regress."""
    items = kb["exterior_capex"]["items"]
    assert "roof" in items
    assert "siding_paint" in items
    assert items["roof"]["per_unit_low"] == 1000


def test_exterior_capex_bundles_section_exists(kb):
    bundles = kb["exterior_capex"]["bundles"]
    assert "envelope_refresh" in bundles
    assert "full_envelope" in bundles


def test_envelope_refresh_bundle_shape(kb):
    b = kb["exterior_capex"]["bundles"]["envelope_refresh"]
    assert isinstance(b["includes"], list)
    assert "siding_paint" in b["includes"]
    assert "signage_lighting" in b["includes"]
    assert "landscaping" in b["includes"]
    assert b["class_shift_to"] == "B"


def test_full_envelope_bundle_shape(kb):
    b = kb["exterior_capex"]["bundles"]["full_envelope"]
    assert "roof" in b["includes"]
    assert b["class_shift_to"] == "B+"


def test_bundle_includes_reference_real_items(kb):
    """Every item referenced by a bundle must exist in exterior_capex.items."""
    items = set(kb["exterior_capex"]["items"].keys())
    for bundle_name, bundle in kb["exterior_capex"]["bundles"].items():
        for item in bundle["includes"]:
            assert item in items, (
                f"bundle {bundle_name!r} references unknown item {item!r}"
            )


def test_amenity_catalog_section_exists(kb):
    catalog = kb["amenity_catalog"]
    assert isinstance(catalog, dict)
    for required in [
        "pool", "dog_park", "ev_chargers", "package_room",
        "fitness_buildout", "pickleball_court",
    ]:
        assert required in catalog, f"amenity_catalog missing {required!r}"


def test_amenity_catalog_entries_have_install_cost_range(kb):
    for name, entry in kb["amenity_catalog"].items():
        assert "install_low" in entry, f"{name} missing install_low"
        assert "install_high" in entry, f"{name} missing install_high"
        assert entry["install_low"] <= entry["install_high"], (
            f"{name} has inverted install cost range"
        )


def test_amenity_pool_specifics(kb):
    pool = kb["amenity_catalog"]["pool"]
    assert pool["install_low"] == 80000
    assert pool["install_high"] == 150000
    assert pool["annual_opex_low"] == 8000
    assert pool["typical_occupancy_lift_pct"] == 1.5


def test_deferred_maintenance_section_exists(kb):
    dm = kb["deferred_maintenance"]
    for required in [
        "roof_full_replacement", "parking_reconstruction",
        "hvac_unit_replacement", "galvanized_pipe_repipe",
        "electrical_panel_upgrade",
    ]:
        assert required in dm, f"deferred_maintenance missing {required!r}"


def test_deferred_maintenance_entries_have_per_unit_range(kb):
    for name, entry in kb["deferred_maintenance"].items():
        assert "per_unit_low" in entry, f"{name} missing per_unit_low"
        assert "per_unit_high" in entry, f"{name} missing per_unit_high"
        assert entry["per_unit_low"] <= entry["per_unit_high"], (
            f"{name} has inverted per-unit cost range"
        )


def test_deferred_roof_replacement_more_expensive_than_overlay(kb):
    """Full replacement should cost more than the slice-A overlay number."""
    overlay_high = kb["exterior_capex"]["items"]["roof"]["per_unit_high"]
    replacement_low = kb["deferred_maintenance"]["roof_full_replacement"]["per_unit_low"]
    assert replacement_low > overlay_high, (
        "deferred-maintenance full replacement should price above value-add overlay"
    )
