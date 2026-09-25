"""Tests for deal JSON → ScopeRequest projection."""
import pytest

from plat_costmodel.bridge.deal_projection import (
    project_deal_to_scope_requests,
)
from plat_costmodel.schemas import (
    Property, ProgramType, ScopeRequest,
)
from plat_costmodel.store.repo import PropertyRepo


def _seed_property_with_floor_plan(tmp_db):
    repo = PropertyRepo(tmp_db)
    p = repo.create(Property(
        property_id="", external_alias="123-main-st",
        total_units=12, address="123 Main St",
    ))
    from plat_costmodel.schemas import FloorPlan
    repo.create_floor_plan(FloorPlan(
        floor_plan_id="", property_id=p.property_id,
        name="auto:850sf-2x1", sqft=850, bedrooms=2, bathrooms=1,
    ))
    return p


def _good_deal(property_alias: str) -> dict:
    return {
        "schema_version": "0.1",
        "property": {
            "external_alias": property_alias,
            "total_units": 12,
            "address": "123 Main St",
        },
        "unit_cohorts": [
            {
                "avg_sqft": 850,
                "avg_bedrooms": 2,
                "avg_bathrooms": 1,
                "unit_count": 12,
                "current_avg_rent": 850,
            }
        ],
        "renovation_programs": [
            {
                "cohort_index": 0,
                "scope_level": "standard_value_add",
                "finish_tier": "basic",
                "rent_premium_monthly": 200,
                "start_month": "2026-06",
                "monthly_pace": 5,
                "downtime_days": 21,
            }
        ],
    }


def test_project_returns_one_request_per_program(tmp_db):
    p = _seed_property_with_floor_plan(tmp_db)
    deal = _good_deal(p.external_alias)
    requests = project_deal_to_scope_requests(deal, conn=tmp_db)
    assert len(requests) == 1
    req = requests[0]
    assert isinstance(req, ScopeRequest)
    assert req.property_id == p.property_id
    assert req.program_type == ProgramType.INTERIOR_RENOVATION
    assert req.cohort.unit_count == 12
    assert req.cohort.current_monthly_rent == 850
    assert req.cohort.target_monthly_rent == 1050  # 850 + 200
    assert req.schedule.start_month == "2026-06"


def test_project_mints_floor_plan_when_no_match(tmp_db):
    """If no FloorPlan matches (sqft, beds, baths), mint a new one named
    auto:<sqft>sf-<beds>x<baths>."""
    repo = PropertyRepo(tmp_db)
    p = repo.create(Property(property_id="", external_alias="222-elm",
                             total_units=8, address="222 Elm"))
    deal = _good_deal("222-elm")
    requests = project_deal_to_scope_requests(deal, conn=tmp_db)
    fp_id = requests[0].cohort.floor_plan_id
    fp = repo.get_floor_plan(fp_id)
    assert fp.name == "auto:850sf-2x1"


def test_project_resolves_property_by_alias(tmp_db):
    p = _seed_property_with_floor_plan(tmp_db)
    deal = _good_deal(p.external_alias)
    requests = project_deal_to_scope_requests(deal, conn=tmp_db)
    # Must reuse the existing property, not mint a new one.
    assert requests[0].property_id == p.property_id


def test_project_creates_property_when_unknown(tmp_db):
    deal = _good_deal("brand-new-prop")
    requests = project_deal_to_scope_requests(deal, conn=tmp_db)
    assert requests[0].property_id != ""
    p = PropertyRepo(tmp_db).get_by_alias("brand-new-prop")
    assert p is not None
    assert p.address == "123 Main St"


def test_project_raises_on_empty_renovation_programs(tmp_db):
    """Followup: deal with renovation_programs=[] silently produced an empty
    estimates list. Now must raise so upstream-agent bugs are caught."""
    from plat_costmodel.schemas import ValidationProblem
    deal = _good_deal("empty-progs")
    deal["renovation_programs"] = []
    with pytest.raises(ValueError) as exc:
        project_deal_to_scope_requests(deal, conn=tmp_db)
    vp = exc.value.validation_problem
    assert isinstance(vp, ValidationProblem)
    assert vp.error_type == "validation_error"
    assert any(
        fe.get("loc") == ["renovation_programs"] for fe in vp.field_errors
    )


def test_project_raises_validationproblem_on_missing_cohort_index(tmp_db):
    from plat_costmodel.schemas import ValidationProblem
    deal = _good_deal("p")
    deal["renovation_programs"][0].pop("cohort_index")
    with pytest.raises(ValueError) as exc:
        project_deal_to_scope_requests(deal, conn=tmp_db)
    assert hasattr(exc.value, "validation_problem")
    vp = exc.value.validation_problem  # type: ignore[attr-defined]
    assert isinstance(vp, ValidationProblem)
    assert vp.error_type == "validation_error"
    assert any("cohort_index" in str(fe.get("loc", "")) for fe in vp.field_errors)


def test_project_deal_is_pure_no_db_writes(tmp_db):
    """project_deal must NOT write to the store. The bridge layer is
    pure projection; scope_service owns the writes."""
    from plat_costmodel.bridge.deal_projection import project_deal
    from plat_costmodel.store.repo import PropertyRepo

    deal = _good_deal("pure-test-prop")
    projection = project_deal(deal)  # no conn parameter!
    # Assert no Property was created:
    assert PropertyRepo(tmp_db).get_by_alias("pure-test-prop") is None
    # But the projection has the right shape:
    assert projection.property["external_alias"] == "pure-test-prop"
    assert len(projection.cohorts) == 1
    cohort = projection.cohorts[0]
    assert cohort.sqft == 850
    assert cohort.unit_count == 12
    assert cohort.target_monthly_rent == 1050  # 850 + 200


def test_project_deal_backfills_cohort_id_when_absent():
    """Existing fixtures use cohort_index only — bridge should backfill ids."""
    from plat_costmodel.bridge.deal_projection import project_deal

    deal = {
        "property": {"external_alias": "p", "total_units": 12,
                     "address": "1 Main", "year_built": 1985},
        "unit_cohorts": [
            {"avg_sqft": 850, "avg_bedrooms": 2, "avg_bathrooms": 1,
             "unit_count": 12, "current_avg_rent": 850},
            {"avg_sqft": 1100, "avg_bedrooms": 3, "avg_bathrooms": 2,
             "unit_count": 4, "current_avg_rent": 1200},
        ],
        "renovation_programs": [
            {"cohort_index": 0, "scope_level": "standard_value_add",
             "finish_tier": "basic", "rent_premium_monthly": 200,
             "start_month": "2026-06", "monthly_pace": 5},
        ],
    }
    proj = project_deal(deal)
    assert proj.cohorts[0].cohort_id == "cohort_0"


def test_project_deal_preserves_explicit_cohort_id():
    from plat_costmodel.bridge.deal_projection import project_deal

    deal = {
        "property": {"external_alias": "p", "total_units": 12,
                     "address": "1 Main", "year_built": 1985},
        "unit_cohorts": [
            {"cohort_id": "studio_north", "avg_sqft": 600, "avg_bedrooms": 1,
             "avg_bathrooms": 1, "unit_count": 8, "current_avg_rent": 700},
        ],
        "renovation_programs": [
            {"cohort_index": 0, "scope_level": "standard_value_add",
             "finish_tier": "basic", "rent_premium_monthly": 100,
             "start_month": "2026-06", "monthly_pace": 5},
        ],
    }
    proj = project_deal(deal)
    assert proj.cohorts[0].cohort_id == "studio_north"


def test_project_deal_exposes_cohort_id_lookup_on_projection():
    """Beyond the per-program list, scope_service needs an id-keyed lookup
    so scenarios can reference cohorts by id, not by index."""
    from plat_costmodel.bridge.deal_projection import project_deal

    deal = {
        "property": {"external_alias": "p", "total_units": 16,
                     "address": "1 Main", "year_built": 1985},
        "unit_cohorts": [
            {"cohort_id": "C1", "avg_sqft": 850, "avg_bedrooms": 2,
             "avg_bathrooms": 1, "unit_count": 12, "current_avg_rent": 850},
            {"avg_sqft": 1100, "avg_bedrooms": 3, "avg_bathrooms": 2,
             "unit_count": 4, "current_avg_rent": 1200},
        ],
        "renovation_programs": [
            {"cohort_index": 0, "scope_level": "standard_value_add",
             "finish_tier": "basic", "rent_premium_monthly": 200,
             "start_month": "2026-06", "monthly_pace": 5},
        ],
    }
    proj = project_deal(deal)
    assert "C1" in proj.cohort_lookup
    assert "cohort_1" in proj.cohort_lookup
    assert proj.cohort_lookup["C1"]["avg_sqft"] == 850


def test_project_deal_rejects_empty_cohort_id():
    """An explicit empty cohort_id must surface as validation_error, not be
    silently backfilled — that would mask upstream agent bugs."""
    from plat_costmodel.bridge.deal_projection import project_deal

    deal = {
        "property": {"external_alias": "p", "total_units": 12,
                     "address": "1 Main", "year_built": 1985},
        "unit_cohorts": [
            {"cohort_id": "", "avg_sqft": 850, "avg_bedrooms": 2,
             "avg_bathrooms": 1, "unit_count": 12, "current_avg_rent": 850},
        ],
        "renovation_programs": [
            {"cohort_index": 0, "scope_level": "standard_value_add",
             "finish_tier": "basic", "rent_premium_monthly": 200,
             "start_month": "2026-06", "monthly_pace": 5},
        ],
    }
    with pytest.raises(ValueError) as exc:
        project_deal(deal)
    assert "cohort_id" in str(exc.value)


def test_project_deal_rejects_null_cohort_id():
    """Same as empty string: explicit null is a bug, not an opt-in to backfill."""
    from plat_costmodel.bridge.deal_projection import project_deal

    deal = {
        "property": {"external_alias": "p", "total_units": 12,
                     "address": "1 Main", "year_built": 1985},
        "unit_cohorts": [
            {"cohort_id": None, "avg_sqft": 850, "avg_bedrooms": 2,
             "avg_bathrooms": 1, "unit_count": 12, "current_avg_rent": 850},
        ],
        "renovation_programs": [
            {"cohort_index": 0, "scope_level": "standard_value_add",
             "finish_tier": "basic", "rent_premium_monthly": 200,
             "start_month": "2026-06", "monthly_pace": 5},
        ],
    }
    with pytest.raises(ValueError) as exc:
        project_deal(deal)
    assert "cohort_id" in str(exc.value)
