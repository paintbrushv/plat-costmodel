"""Tests for EstimateRepo."""
from datetime import datetime, timezone

from plat_costmodel.models import (
    FinishTier, LineItem, ROIResult, ScopeLevel, SizeCategory, UnitEstimate,
)
from plat_costmodel.schemas import (
    AmenityCohort, AmenityScopeEstimate,
    DeferredMaintenanceCohort, DeferredMaintenanceEstimate,
    ExteriorCohort, ExteriorScopeEstimate,
    InteriorScopeEstimate,
    PricingSnapshot, ProgramSchedule, ProgramType, Property, ScopeEstimate,
    ScopeRequest, UnitCohort,
)
from plat_costmodel.store.repo import (
    EstimateRepo, PropertyRepo, ScopeRepo, SnapshotRepo,
)


def _seed(tmp_db):
    p = PropertyRepo(tmp_db).create(Property(property_id="", total_units=12))
    snap = SnapshotRepo(tmp_db).get_or_create_for_kb_hash("abc")
    req = ScopeRepo(tmp_db).create(ScopeRequest(
        property_id=p.property_id,
        program_type=ProgramType.INTERIOR_RENOVATION,
        cohort=UnitCohort(
            floor_plan_id="fp1", unit_count=12,
            scope_level=ScopeLevel.STANDARD_VALUE_ADD,
            finish_tier=FinishTier.BASIC,
            current_monthly_rent=850, target_monthly_rent=1050,
        ),
        schedule=ProgramSchedule(start_month="2026-06", monthly_pace=5),
    ))
    return p, snap, req


def _est(req_id: str, prop_id: str, snap_id: str) -> ScopeEstimate:
    ue = UnitEstimate(
        unit_id="u1", unit_sqft=850, bedrooms=2, bathrooms=1,
        scope_level=ScopeLevel.STANDARD_VALUE_ADD,
        finish_tier=FinishTier.BASIC,
        size_category=SizeCategory.MEDIUM,
        line_items=[LineItem(category="paint", low=800, high=1200)],
        subtotal_low=800, subtotal_high=1200,
        contingency_pct=0.10,
        contingency_low=80, contingency_high=120,
        total_low=880, total_high=1320,
        risk_flags=[],
    )
    roi = ROIResult(
        total_cost_high=15840, current_monthly_rent=850, target_monthly_rent=1050,
        monthly_rent_lift=200, annual_rent_lift=2400,
        roi_pct=15.15, clears_threshold=True,
    )
    return ScopeEstimate(
        estimate_id="", scope_request_id=req_id,
        property_id=prop_id, floor_plan_id="fp-default",
        pricing_snapshot_id=snap_id,
        unit_estimates=[ue],
        cohort_total_low=10560, cohort_total_high=15840,
        per_unit_average_low=880, per_unit_average_high=1320,
        roi_result=roi, risk_flags=[], sanity_flags=[],
        estimated_at=datetime.now(timezone.utc),
    )


def test_create_mints_id(tmp_db):
    p, snap, req = _seed(tmp_db)
    repo = EstimateRepo(tmp_db)
    saved = repo.create(_est(req.scope_request_id, p.property_id, snap.snapshot_id))
    assert len(saved.estimate_id) == 26


def test_round_trip(tmp_db):
    p, snap, req = _seed(tmp_db)
    repo = EstimateRepo(tmp_db)
    saved = repo.create(_est(req.scope_request_id, p.property_id, snap.snapshot_id))
    fetched = repo.get(saved.estimate_id)
    assert fetched is not None
    assert fetched.cohort_total_high == 15840
    assert fetched.unit_estimates[0].line_items[0].category == "paint"


def test_list_for_property(tmp_db):
    p, snap, req = _seed(tmp_db)
    repo = EstimateRepo(tmp_db)
    repo.create(_est(req.scope_request_id, p.property_id, snap.snapshot_id))
    repo.create(_est(req.scope_request_id, p.property_id, snap.snapshot_id))
    assert len(repo.list_for_property(p.property_id)) == 2


def test_list_for_request(tmp_db):
    p, snap, req = _seed(tmp_db)
    repo = EstimateRepo(tmp_db)
    repo.create(_est(req.scope_request_id, p.property_id, snap.snapshot_id))
    assert len(repo.list_for_request(req.scope_request_id)) == 1


def test_estimate_carries_floor_plan_id(tmp_db):
    p, snap, req = _seed(tmp_db)
    repo = EstimateRepo(tmp_db)
    est = _est(req.scope_request_id, p.property_id, snap.snapshot_id)
    est = est.model_copy(update={"floor_plan_id": "fp-test-123"})
    saved = repo.create(est)
    fetched = repo.get(saved.estimate_id)
    assert fetched.floor_plan_id == "fp-test-123"


def test_get_for_floor_plan(tmp_db):
    from datetime import timedelta

    p, snap, req = _seed(tmp_db)
    repo = EstimateRepo(tmp_db)
    e1 = _est(req.scope_request_id, p.property_id, snap.snapshot_id).model_copy(
        update={"floor_plan_id": "fp-A"}
    )
    e2 = _est(req.scope_request_id, p.property_id, snap.snapshot_id).model_copy(
        update={"floor_plan_id": "fp-B"}
    )
    repo.create(e1)
    repo.create(e2)
    plan_a = repo.get_for_floor_plan("fp-A")
    assert len(plan_a) == 1
    assert plan_a[0].floor_plan_id == "fp-A"
    plan_b = repo.get_for_floor_plan("fp-B")
    assert len(plan_b) == 1
    # since-filter covers nothing in the past
    nothing = repo.get_for_floor_plan("fp-A", since=datetime.now(timezone.utc) + timedelta(hours=1))
    assert nothing == []


# ---------------------------------------------------------------------------
# Helpers for polymorphic round-trip tests
# ---------------------------------------------------------------------------

def _seed_for_variant(tmp_db, scope_type: str):
    """Seed property + snapshot + scope_request for a non-interior variant."""
    program_type_map = {
        "unit": ProgramType.INTERIOR_RENOVATION,
        "exterior": ProgramType.EXTERIOR_RENOVATION,
        "amenity": ProgramType.AMENITY_ADDITION,
        "deferred": ProgramType.DEFERRED_MAINTENANCE,
    }
    cohort_map = {
        "unit": UnitCohort(
            floor_plan_id="fp1", unit_count=10,
            scope_level=ScopeLevel.STANDARD_VALUE_ADD,
            finish_tier=FinishTier.BASIC,
            current_monthly_rent=800, target_monthly_rent=1000,
        ),
        "exterior": ExteriorCohort(items=["roof"], total_units=50),
        "amenity": AmenityCohort(amenity_type="dog_park"),
        "deferred": DeferredMaintenanceCohort(items=["hvac"], total_units=50),
    }
    p = PropertyRepo(tmp_db).create(Property(property_id="", total_units=50))
    snap = SnapshotRepo(tmp_db).get_or_create_for_kb_hash(f"hash-{scope_type}")
    req = ScopeRepo(tmp_db).create(ScopeRequest(
        property_id=p.property_id,
        program_type=program_type_map[scope_type],
        cohort=cohort_map[scope_type],
        schedule=ProgramSchedule(start_month="2026-06", monthly_pace=5),
    ))
    return p, snap, req


# ---------------------------------------------------------------------------
# Slice-A interior round-trip via new JSON blob path (regression)
# ---------------------------------------------------------------------------

def test_interior_round_trip_via_json_blob(tmp_db):
    """InteriorScopeEstimate persists and reads back correctly via estimate_json."""
    p, snap, req = _seed(tmp_db)
    repo = EstimateRepo(tmp_db)
    saved = repo.create(_est(req.scope_request_id, p.property_id, snap.snapshot_id))
    rebuilt = repo.get(saved.estimate_id)
    assert isinstance(rebuilt, InteriorScopeEstimate)
    assert rebuilt.cohort_total_high == 15840
    assert rebuilt.unit_estimates[0].line_items[0].category == "paint"
    assert rebuilt.floor_plan_id == "fp-default"
    assert rebuilt.estimate_id == saved.estimate_id


# ---------------------------------------------------------------------------
# Exterior round-trip
# ---------------------------------------------------------------------------

def test_estimate_repo_round_trips_exterior_variant(tmp_db):
    """ExteriorScopeEstimate persists and reads back via TypeAdapter."""
    p, snap, req = _seed_for_variant(tmp_db, "exterior")
    est = ExteriorScopeEstimate(
        estimate_id="",
        scope_request_id=req.scope_request_id,
        property_id=p.property_id,
        pricing_snapshot_id=snap.snapshot_id,
        line_items=[LineItem(category="roof", low=120000, high=180000)],
        total_low=120000, total_high=180000,
        per_unit_low=1000, per_unit_high=1500,
        risk_flags=[], sanity_flags=[],
        estimated_at=datetime.now(timezone.utc),
    )
    saved = EstimateRepo(tmp_db).create(est)
    assert saved.estimate_id  # ULID minted
    rebuilt = EstimateRepo(tmp_db).get(saved.estimate_id)
    assert isinstance(rebuilt, ExteriorScopeEstimate)
    assert rebuilt.total_high == 180000
    assert rebuilt.line_items[0].category == "roof"
    assert rebuilt.estimate_id == saved.estimate_id
    # floor_plan_id column should be NULL for exterior
    row = tmp_db.execute(
        "SELECT floor_plan_id FROM scope_estimates WHERE estimate_id = ?",
        (saved.estimate_id,),
    ).fetchone()
    assert row["floor_plan_id"] is None


# ---------------------------------------------------------------------------
# Amenity round-trip
# ---------------------------------------------------------------------------

def test_estimate_repo_round_trips_amenity_variant(tmp_db):
    """AmenityScopeEstimate persists and reads back via TypeAdapter."""
    p, snap, req = _seed_for_variant(tmp_db, "amenity")
    est = AmenityScopeEstimate(
        estimate_id="",
        scope_request_id=req.scope_request_id,
        property_id=p.property_id,
        pricing_snapshot_id=snap.snapshot_id,
        amenity_type="dog_park",
        install_cost_low=25000, install_cost_high=40000,
        annual_opex_low=2000, annual_opex_high=5000,
        risk_flags=[], sanity_flags=[],
        estimated_at=datetime.now(timezone.utc),
    )
    saved = EstimateRepo(tmp_db).create(est)
    assert saved.estimate_id
    rebuilt = EstimateRepo(tmp_db).get(saved.estimate_id)
    assert isinstance(rebuilt, AmenityScopeEstimate)
    assert rebuilt.amenity_type == "dog_park"
    assert rebuilt.install_cost_high == 40000
    assert rebuilt.annual_opex_low == 2000
    assert rebuilt.estimate_id == saved.estimate_id


# ---------------------------------------------------------------------------
# Deferred maintenance round-trip
# ---------------------------------------------------------------------------

def test_estimate_repo_round_trips_deferred_variant(tmp_db):
    """DeferredMaintenanceEstimate persists and reads back via TypeAdapter."""
    p, snap, req = _seed_for_variant(tmp_db, "deferred")
    est = DeferredMaintenanceEstimate(
        estimate_id="",
        scope_request_id=req.scope_request_id,
        property_id=p.property_id,
        pricing_snapshot_id=snap.snapshot_id,
        line_items=[LineItem(category="hvac", low=3000, high=5000)],
        total_low=150000, total_high=250000,
        per_unit_low=3000, per_unit_high=5000,
        triggered_by="hvac eol age 22yr",
        risk_flags=[], sanity_flags=[],
        estimated_at=datetime.now(timezone.utc),
    )
    saved = EstimateRepo(tmp_db).create(est)
    assert saved.estimate_id
    rebuilt = EstimateRepo(tmp_db).get(saved.estimate_id)
    assert isinstance(rebuilt, DeferredMaintenanceEstimate)
    assert rebuilt.triggered_by == "hvac eol age 22yr"
    assert rebuilt.total_high == 250000
    assert rebuilt.line_items[0].category == "hvac"
    assert rebuilt.estimate_id == saved.estimate_id
