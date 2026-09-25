"""Tests for the scope_service orchestration layer (pure Python, no MCP)."""
import pytest

from plat_costmodel.models import FinishTier, ScopeLevel
from plat_costmodel.schemas import (
    FloorPlan, ProgramSchedule, ProgramType, Property, ScopeRequest,
    UnitCohort,
)
from plat_costmodel.scope_service import estimate_scope
from plat_costmodel.store.repo import EstimateRepo, PropertyRepo


def _seed(tmp_db) -> tuple[Property, FloorPlan]:
    repo = PropertyRepo(tmp_db)
    p = repo.create(Property(
        property_id="", total_units=12, year_built=1985,
        address="1 Main St",
    ))
    fp = repo.create_floor_plan(FloorPlan(
        floor_plan_id="", property_id=p.property_id,
        name="A", sqft=850, bedrooms=2, bathrooms=1,
    ))
    return p, fp


def test_estimate_scope_persists_request_estimate_and_snapshot(tmp_db):
    p, fp = _seed(tmp_db)
    req = ScopeRequest(
        property_id=p.property_id,
        program_type=ProgramType.INTERIOR_RENOVATION,
        cohort=UnitCohort(
            floor_plan_id=fp.floor_plan_id, unit_count=12,
            scope_level=ScopeLevel.STANDARD_VALUE_ADD,
            finish_tier=FinishTier.BASIC,
            current_monthly_rent=850, target_monthly_rent=1050,
        ),
        schedule=ProgramSchedule(start_month="2026-06", monthly_pace=5),
    )
    est = estimate_scope(req, conn=tmp_db)
    assert est.estimate_id != ""
    assert est.scope_request_id != ""
    assert est.property_id == p.property_id
    assert est.cohort_total_high > 0
    assert len(est.unit_estimates) == 12
    assert est.pricing_snapshot_id != ""
    # And it's persisted:
    fetched = EstimateRepo(tmp_db).get(est.estimate_id)
    assert fetched is not None


def test_estimate_scope_returns_clears_threshold_when_roi_passes(tmp_db):
    p, fp = _seed(tmp_db)
    req = ScopeRequest(
        property_id=p.property_id,
        program_type=ProgramType.INTERIOR_RENOVATION,
        cohort=UnitCohort(
            floor_plan_id=fp.floor_plan_id, unit_count=12,
            scope_level=ScopeLevel.STANDARD_VALUE_ADD,
            finish_tier=FinishTier.BASIC,
            current_monthly_rent=850, target_monthly_rent=1100,
        ),
        schedule=ProgramSchedule(start_month="2026-06", monthly_pace=5),
    )
    est = estimate_scope(req, conn=tmp_db)
    assert est.roi_result.clears_threshold


def test_estimate_scope_calls_estimate_unit_once_per_cohort(tmp_db, monkeypatch):
    """Performance regression guard: estimate_unit() is called once for the
    cohort's FloorPlan, not once per unit."""
    from plat_costmodel import scope_service
    from plat_costmodel.estimator import estimate_unit as real_estimate_unit

    call_count = 0

    def counting_estimate_unit(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return real_estimate_unit(*args, **kwargs)

    monkeypatch.setattr(scope_service, "estimate_unit", counting_estimate_unit)

    p, fp = _seed(tmp_db)  # use the existing _seed helper
    req = ScopeRequest(
        property_id=p.property_id,
        program_type=ProgramType.INTERIOR_RENOVATION,
        cohort=UnitCohort(
            floor_plan_id=fp.floor_plan_id, unit_count=50,  # large cohort
            scope_level=ScopeLevel.STANDARD_VALUE_ADD,
            finish_tier=FinishTier.BASIC,
            current_monthly_rent=850, target_monthly_rent=1100,
        ),
        schedule=ProgramSchedule(start_month="2026-06", monthly_pace=10),
    )
    est = estimate_scope(req, conn=tmp_db)

    assert call_count == 1, f"expected 1 estimate_unit call, got {call_count}"
    # And every unit in the resulting estimate has a distinct unit_id:
    unit_ids = [ue.unit_id for ue in est.unit_estimates]
    assert len(unit_ids) == 50
    assert len(set(unit_ids)) == 50  # all distinct


def test_estimate_scope_raises_when_floor_plan_not_found(tmp_db):
    p, _ = _seed(tmp_db)
    req = ScopeRequest(
        property_id=p.property_id,
        program_type=ProgramType.INTERIOR_RENOVATION,
        cohort=UnitCohort(
            floor_plan_id="does-not-exist", unit_count=12,
            scope_level=ScopeLevel.STANDARD_VALUE_ADD,
            finish_tier=FinishTier.BASIC,
            current_monthly_rent=850, target_monthly_rent=1050,
        ),
        schedule=ProgramSchedule(start_month="2026-06", monthly_pace=5),
    )
    with pytest.raises(ValueError) as exc:
        estimate_scope(req, conn=tmp_db)
    vp = exc.value.validation_problem  # type: ignore[attr-defined]
    assert vp.error_type == "not_found"
    assert any(
        fe.get("loc") == ["cohort", "floor_plan_id"] for fe in vp.field_errors
    )


def test_estimate_scope_raises_when_property_not_found(tmp_db):
    """Code-review followup: the property-not-found branch was previously
    untested. A future refactor that broke the property lookup would have
    slipped through."""
    req = ScopeRequest(
        property_id="DOES-NOT-EXIST",
        program_type=ProgramType.INTERIOR_RENOVATION,
        cohort=UnitCohort(
            floor_plan_id="any", unit_count=1,
            scope_level=ScopeLevel.STANDARD_VALUE_ADD,
            finish_tier=FinishTier.BASIC,
            current_monthly_rent=1, target_monthly_rent=1,
        ),
        schedule=ProgramSchedule(start_month="2026-06", monthly_pace=1),
    )
    with pytest.raises(ValueError) as exc:
        estimate_scope(req, conn=tmp_db)
    vp = exc.value.validation_problem  # type: ignore[attr-defined]
    assert vp.error_type == "not_found"
    assert any(fe.get("loc") == ["property_id"] for fe in vp.field_errors)


def test_estimate_scope_unit_count_one_boundary(tmp_db):
    """unit_count=1 must produce exactly 1 UnitEstimate and consistent aggregates.

    Specifically:
      - len(unit_estimates) == 1
      - cohort_total_high == unit_estimates[0].total_high
      - per_unit_average_high == cohort_total_high  (division by 1 is a no-op)
    """
    p, fp = _seed(tmp_db)
    req = ScopeRequest(
        property_id=p.property_id,
        program_type=ProgramType.INTERIOR_RENOVATION,
        cohort=UnitCohort(
            floor_plan_id=fp.floor_plan_id,
            unit_count=1,
            scope_level=ScopeLevel.STANDARD_VALUE_ADD,
            finish_tier=FinishTier.BASIC,
            current_monthly_rent=850,
            target_monthly_rent=1050,
        ),
        schedule=ProgramSchedule(start_month="2026-06", monthly_pace=1),
    )
    est = estimate_scope(req, conn=tmp_db)
    assert len(est.unit_estimates) == 1
    assert est.cohort_total_high == est.unit_estimates[0].total_high
    assert est.per_unit_average_high == est.cohort_total_high


def test_estimate_scope_rejects_exterior_cohort_with_unknown_property():
    """Regression guard: exterior cohort with an unknown property_id raises a
    structured not_found error (Task 3 replaced the not_implemented stub with
    the real estimator; it now routes through PropertyRepo.get)."""
    from plat_costmodel.schemas import (
        ExteriorCohort,
        ProgramSchedule,
        ProgramType,
        ScopeRequest,
    )
    from plat_costmodel.scope_service import estimate_scope

    req = ScopeRequest(
        property_id="p-does-not-need-to-exist",
        program_type=ProgramType.EXTERIOR_RENOVATION,
        cohort=ExteriorCohort(items=["roof"], total_units=10),
        schedule=ProgramSchedule(start_month="2026-06", monthly_pace=1),
    )
    with pytest.raises(ValueError) as exc:
        estimate_scope(req)
    vp = exc.value.validation_problem  # type: ignore[attr-defined]
    assert vp.error_type == "not_found"
    assert any(fe.get("loc") == ["property_id"] for fe in vp.field_errors)


def test_estimate_scope_dispatches_unit_cohort_to_interior_estimator(tmp_db):
    """Slice-A unit path still works after dispatch refactor — sanity regression."""
    from plat_costmodel.schemas import InteriorScopeEstimate

    p, fp = _seed(tmp_db)
    req = ScopeRequest(
        property_id=p.property_id,
        program_type=ProgramType.INTERIOR_RENOVATION,
        cohort=UnitCohort(
            floor_plan_id=fp.floor_plan_id, unit_count=5,
            scope_level=ScopeLevel.STANDARD_VALUE_ADD,
            finish_tier=FinishTier.BASIC,
            current_monthly_rent=850, target_monthly_rent=1050,
        ),
        schedule=ProgramSchedule(start_month="2026-06", monthly_pace=2),
    )
    result = estimate_scope(req, conn=tmp_db)
    assert isinstance(result, InteriorScopeEstimate)


def test_estimate_scope_amenity_produces_persisted_estimate(tmp_db):
    """Full path: AmenityCohort → estimate_scope → persisted AmenityScopeEstimate."""
    from plat_costmodel.schemas import (
        AmenityCohort, AmenityScopeEstimate, ProgramSchedule,
        ProgramType, ScopeRequest,
    )

    p, _ = _seed(tmp_db)
    req = ScopeRequest(
        property_id=p.property_id,
        program_type=ProgramType.AMENITY_ADDITION,
        cohort=AmenityCohort(
            amenity_type="pool",
            expected_occupancy_lift_pct=1.0,  # KB pool typical=1.5; gate clears
        ),
        schedule=ProgramSchedule(start_month="2026-06", monthly_pace=1),
    )
    est = estimate_scope(req, conn=tmp_db)
    assert isinstance(est, AmenityScopeEstimate)
    assert est.amenity_type == "pool"
    assert est.install_cost_high == 150000  # KB value, qty=1
    assert est.annual_opex_high == 15000
    assert est.expected_occupancy_lift_result is not None
    assert est.expected_occupancy_lift_result.clears_threshold is True
    assert est.expected_rent_premium_result is None  # no target supplied
    # Round-trip via repo
    rebuilt = EstimateRepo(tmp_db).get(est.estimate_id)
    assert isinstance(rebuilt, AmenityScopeEstimate)
    assert rebuilt.install_cost_high == 150000


def test_estimate_scope_amenity_unknown_type_raises_structured_error(tmp_db):
    """amenity_type must exist in KB amenity_catalog."""
    from plat_costmodel.schemas import (
        AmenityCohort, ProgramSchedule, ProgramType, ScopeRequest,
    )

    p, _ = _seed(tmp_db)
    req = ScopeRequest(
        property_id=p.property_id,
        program_type=ProgramType.AMENITY_ADDITION,
        cohort=AmenityCohort(amenity_type="moonbase"),
        schedule=ProgramSchedule(start_month="2026-06", monthly_pace=1),
    )
    with pytest.raises(ValueError) as exc:
        estimate_scope(req, conn=tmp_db)
    vp = exc.value.validation_problem  # type: ignore[attr-defined]
    assert vp.error_type == "validation_error"
    assert "moonbase" in str(exc.value)


def test_estimate_scope_dispatches_deferred_cohort_to_not_implemented(tmp_db):
    """DeferredMaintenanceCohort surfaces not_implemented (PR 5 lands the estimator)."""
    from plat_costmodel.schemas import DeferredMaintenanceCohort, ProgramSchedule, ProgramType, ScopeRequest

    p, _ = _seed(tmp_db)
    req = ScopeRequest(
        property_id=p.property_id,
        program_type=ProgramType.DEFERRED_MAINTENANCE,
        cohort=DeferredMaintenanceCohort(items=["roof_full_replacement"], total_units=10),
        schedule=ProgramSchedule(start_month="2026-06", monthly_pace=1),
    )
    with pytest.raises(ValueError) as exc:
        estimate_scope(req, conn=tmp_db)
    vp = exc.value.validation_problem  # type: ignore[attr-defined]
    assert vp.error_type == "not_implemented"
    assert "deferred" in vp.message.lower() or "PR 5" in vp.message


def test_estimate_scope_dispatches_exterior_cohort_to_estimator(tmp_db):
    """Exterior cohort routes to _estimate_exterior and produces a real
    ExteriorScopeEstimate (Task 3 replaced the not_implemented stub)."""
    from plat_costmodel.schemas import ExteriorCohort, ExteriorScopeEstimate, ProgramSchedule, ProgramType, ScopeRequest

    p, _ = _seed(tmp_db)
    req = ScopeRequest(
        property_id=p.property_id,
        program_type=ProgramType.EXTERIOR_RENOVATION,
        cohort=ExteriorCohort(items=["roof"], total_units=50),
        schedule=ProgramSchedule(start_month="2026-06", monthly_pace=1),
    )
    result = estimate_scope(req, conn=tmp_db)
    assert isinstance(result, ExteriorScopeEstimate)


def _good_deal() -> dict:
    return {
        "schema_version": "0.1",
        "property": {
            "external_alias": "deal-prop", "total_units": 12,
            "address": "1 Main St", "year_built": 1985,
        },
        "unit_cohorts": [
            {"avg_sqft": 850, "avg_bedrooms": 2, "avg_bathrooms": 1,
             "unit_count": 12, "current_avg_rent": 850},
        ],
        "renovation_programs": [
            {"cohort_index": 0, "scope_level": "standard_value_add",
             "finish_tier": "basic", "rent_premium_monthly": 250,
             "start_month": "2026-06", "monthly_pace": 5, "downtime_days": 21},
        ],
    }


def test_estimate_scope_raises_when_kb_missing(tmp_db, monkeypatch):
    """Code-review followup: when the knowledge_base.yaml is missing, raise
    a structured ValidationProblem (via raise_problem). A bare
    FileNotFoundError would propagate naked from MCP tools because
    @_validated only catches ValidationError/ValueError/KeyError."""
    from plat_costmodel import scope_service
    from pathlib import Path

    p, fp = _seed(tmp_db)
    monkeypatch.setattr(scope_service, "_KB_PATH", Path("/nonexistent/kb.yaml"))
    req = ScopeRequest(
        property_id=p.property_id,
        program_type=ProgramType.INTERIOR_RENOVATION,
        cohort=UnitCohort(
            floor_plan_id=fp.floor_plan_id, unit_count=1,
            scope_level=ScopeLevel.STANDARD_VALUE_ADD,
            finish_tier=FinishTier.BASIC,
            current_monthly_rent=850, target_monthly_rent=1100,
        ),
        schedule=ProgramSchedule(start_month="2026-06", monthly_pace=1),
    )
    with pytest.raises(ValueError) as exc:
        estimate_scope(req, conn=tmp_db)
    vp = exc.value.validation_problem  # type: ignore[attr-defined]
    assert vp.error_type == "value_error"
    assert "knowledge base not found" in vp.message


def test_estimate_from_deal_two_arg_interior_scenario_round_trips(tmp_db):
    """Two-arg form: pass scenarios alongside the deal."""
    from plat_costmodel.schemas import InteriorScenario, ProgramSchedule
    from plat_costmodel.models import FinishTier, ScopeLevel
    from plat_costmodel.scope_service import estimate_from_deal

    deal = _good_deal()
    scenarios = [
        InteriorScenario(
            cohort_id="cohort_0",
            scope_level=ScopeLevel.STANDARD_VALUE_ADD,
            finish_tier=FinishTier.BASIC,
            rent_premium_monthly=200.0,
            schedule=ProgramSchedule(start_month="2026-06", monthly_pace=5),
        ),
    ]
    out = estimate_from_deal(deal, scenarios)
    assert len(out["estimates"]) == 1
    assert out["estimates"][0].scope_type == "unit"
    assert len(out["renovation_programs"]) == 1


def test_estimate_from_deal_index_aligned_with_scenarios(tmp_db):
    """estimates[i] / renovation_programs[i] correspond to scenarios[i].
    Interior, exterior, and amenity all produce real estimates as of PR 4;
    deferred remains not_implemented until PR 5."""
    from plat_costmodel.schemas import (
        AmenityScenario, AmenityScopeEstimate,
        ExteriorScenario, ExteriorScopeEstimate,
        InteriorScenario, InteriorScopeEstimate,
        ProgramSchedule,
    )
    from plat_costmodel.models import FinishTier, ScopeLevel
    from plat_costmodel.scope_service import estimate_from_deal

    deal = _good_deal()
    scenarios = [
        InteriorScenario(
            cohort_id="cohort_0",
            scope_level=ScopeLevel.STANDARD_VALUE_ADD,
            finish_tier=FinishTier.BASIC,
            rent_premium_monthly=200.0,
            schedule=ProgramSchedule(start_month="2026-06", monthly_pace=5),
        ),
        ExteriorScenario(
            items=["roof"],
            schedule=ProgramSchedule(start_month="2026-09", monthly_pace=1),
        ),
        AmenityScenario(
            amenity_type="pool",
            schedule=ProgramSchedule(start_month="2026-11", monthly_pace=1),
            expected_occupancy_lift_pct=1.0,  # KB pool typical=1.5; gate clears
        ),
    ]
    out = estimate_from_deal(deal, scenarios)
    assert len(out["estimates"]) == 3
    # Slot 0: interior succeeded.
    assert isinstance(out["estimates"][0], InteriorScopeEstimate)
    assert out["estimates"][0].scope_type == "unit"
    # Slot 1: exterior now produces a real estimate (not a not_implemented dict).
    assert isinstance(out["estimates"][1], ExteriorScopeEstimate)
    assert out["estimates"][1].scope_type == "exterior"
    assert out["estimates"][1].total_high > 0
    # renovation_programs[1] is now non-None.
    assert out["renovation_programs"][1] is not None
    # Slot 2: amenity now produces a real estimate — confirms the full path
    # AmenityScenario → _scenario_to_scope_request amenity branch →
    # AmenityCohort → estimate_scope → AmenityScopeEstimate →
    # project_estimate_to_renovation_program works end-to-end.
    assert isinstance(out["estimates"][2], AmenityScopeEstimate)
    amenity_est = out["estimates"][2]
    assert amenity_est.amenity_type == "pool"
    assert amenity_est.install_cost_high == 150000  # KB qty=1
    assert amenity_est.expected_occupancy_lift_result.clears_threshold is True
    # All three renovation_programs are non-None (no not_implemented slots).
    assert all(rp is not None for rp in out["renovation_programs"])


def test_estimate_from_deal_single_arg_form_raises_clear_error():
    from plat_costmodel.scope_service import estimate_from_deal

    with pytest.raises(TypeError) as exc:
        estimate_from_deal(_good_deal())  # missing scenarios
    assert "scenarios" in str(exc.value)


def test_estimate_from_deal_unknown_cohort_id_returns_validation_error(tmp_db):
    """Scenario.cohort_id must reference a real cohort in the deal."""
    from plat_costmodel.schemas import InteriorScenario, ProgramSchedule
    from plat_costmodel.models import FinishTier, ScopeLevel
    from plat_costmodel.scope_service import estimate_from_deal

    deal = _good_deal()
    scenarios = [
        InteriorScenario(
            cohort_id="ghost",
            scope_level=ScopeLevel.STANDARD_VALUE_ADD,
            finish_tier=FinishTier.BASIC,
            rent_premium_monthly=200.0,
            schedule=ProgramSchedule(start_month="2026-06", monthly_pace=5),
        ),
    ]
    with pytest.raises(ValueError) as exc:
        estimate_from_deal(deal, scenarios)
    assert "ghost" in str(exc.value) or "cohort_id" in str(exc.value)


def test_estimate_from_deal_empty_scenarios_returns_empty_lists(tmp_db):
    """Empty scenarios list is a contract hole if undocumented; assert the
    return shape so future refactors can't silently break it."""
    from plat_costmodel.scope_service import estimate_from_deal

    deal = _good_deal()
    out = estimate_from_deal(deal, [])
    assert out == {"estimates": [], "renovation_programs": []}


def test_estimate_scope_exterior_produces_persisted_estimate(tmp_db):
    """Full path: ExteriorCohort → estimate_scope → persisted ExteriorScopeEstimate.
    Round-trip through the new TypeAdapter-based EstimateRepo._row."""
    from plat_costmodel.schemas import ExteriorCohort, ExteriorScopeEstimate, ProgramSchedule, ProgramType, ScopeRequest
    from plat_costmodel.scope_service import estimate_scope

    p, _ = _seed(tmp_db)
    req = ScopeRequest(
        property_id=p.property_id,
        program_type=ProgramType.EXTERIOR_RENOVATION,
        cohort=ExteriorCohort(items=["roof", "siding_paint"], total_units=100),
        schedule=ProgramSchedule(start_month="2026-06", monthly_pace=1),
    )
    est = estimate_scope(req, conn=tmp_db)
    assert isinstance(est, ExteriorScopeEstimate)
    assert est.total_low > 0
    assert est.total_high > est.total_low
    assert len(est.line_items) == 2
    assert est.payback_years_estimated is None
    # Round-trip via repo confirms the new persistence path actually persisted.
    rebuilt = EstimateRepo(tmp_db).get(est.estimate_id)
    assert isinstance(rebuilt, ExteriorScopeEstimate)
    assert rebuilt.total_high == est.total_high
    assert {li.category for li in rebuilt.line_items} == {"roof", "siding_paint"}
