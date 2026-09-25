"""Orchestration: ScopeRequest → ScopeEstimate.

Pure Python, no MCP. Wraps the existing estimator engine with the
canonical ScopeRequest interface, freezes a PricingSnapshot, persists
the resulting (request, estimate, snapshot) trio.
"""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import TypeAdapter

from plat_costmodel.bridge.deal_projection import project_deal
from plat_costmodel.bridge.uw_projection import project_estimate_to_renovation_program
from plat_costmodel.estimator import estimate_unit
from plat_costmodel.roi import check_roi
from plat_costmodel.schemas import (
    AmenityCohort,
    DeferredMaintenanceCohort,
    ExteriorCohort,
    PricingSnapshot,
    ProgramType,
    Property,
    ScenarioUnion,
    ScopeEstimate,
    ScopeRequest,
    UnitCohort,
    raise_problem,
)
from plat_costmodel.schemas.scenario import (
    AmenityScenario,
    DeferredMaintenanceScenario,
    ExteriorScenario,
    InteriorScenario,
)
from plat_costmodel.store.db import connect
from plat_costmodel.store.ids import resolve_floor_plan_by_dims, resolve_property
from plat_costmodel.store.repo import (
    EstimateRepo,
    PropertyRepo,
    ScopeRepo,
    SnapshotRepo,
)

# Knowledge-base path mirrors the layout in src/data/.
_KB_PATH = (
    Path(__file__).parent.parent / "data" / "knowledge_base.yaml"
)


def _kb_hash() -> str:
    """SHA256 of the active knowledge_base.yaml file.

    Raises a structured ValidationProblem (via ``raise_problem``) if the KB
    is missing. The MCP ``_validated`` decorator only catches
    ValidationError / ValueError / KeyError — a bare ``FileNotFoundError``
    would propagate naked from MCP tools, defeating the structured-error
    contract. Silently returning a sentinel hash is also wrong: it would
    create permanent dedup pollution in ``pricing_snapshots``.
    """
    if not _KB_PATH.exists():
        raise_problem(
            "value_error",
            f"knowledge base not found at {_KB_PATH}",
            hint="install the package or set the data dir before estimating",
        )
    return hashlib.sha256(_KB_PATH.read_bytes()).hexdigest()


def estimate_scope(
    req: ScopeRequest, conn: Optional[sqlite3.Connection] = None
) -> ScopeEstimate:
    """Compute a ScopeEstimate variant for a ScopeRequest, persisting both.

    Dispatches on req.cohort type. Each _estimate_* receives an already-open
    connection; estimate_scope owns the conn lifecycle (open if not provided,
    close if owned).
    """
    own_conn = conn is None
    conn = conn or connect()
    try:
        if isinstance(req.cohort, UnitCohort):
            return _estimate_interior(req, conn)
        if isinstance(req.cohort, ExteriorCohort):
            return _estimate_exterior(req, conn)
        if isinstance(req.cohort, AmenityCohort):
            return _estimate_amenity(req, conn)
        if isinstance(req.cohort, DeferredMaintenanceCohort):
            raise_problem(
                "not_implemented",
                "deferred-maintenance estimator not implemented; lands in slice B PR 5",
                hint="items=" + ",".join(req.cohort.items),
            )
        # Defensive — shouldn't reach here given CohortUnion is exhaustive.
        raise_problem(
            "validation_error",
            f"unsupported cohort scope_type={req.cohort.scope_type!r}",
        )
    finally:
        if own_conn:
            conn.close()


def _estimate_interior(req: ScopeRequest, conn: sqlite3.Connection) -> ScopeEstimate:
    """Slice-A interior estimator body, factored out unchanged.

    Receives an already-open connection. Caller owns the conn lifecycle.
    """
    prop_repo = PropertyRepo(conn)
    prop = prop_repo.get(req.property_id)
    if prop is None:
        raise_problem(
            "not_found", f"property {req.property_id} not found",
            field_errors=[{"loc": ["property_id"], "msg": "not found"}],
        )
    floor_plan = prop_repo.get_floor_plan(req.cohort.floor_plan_id)
    if floor_plan is None:
        raise_problem(
            "not_found",
            f"floor_plan {req.cohort.floor_plan_id} not found",
            field_errors=[{"loc": ["cohort", "floor_plan_id"], "msg": "not found"}],
        )

    snap = SnapshotRepo(conn).get_or_create_for_kb_hash(_kb_hash())

    # Estimate once for the cohort's FloorPlan + property context — every
    # unit produces an identical UnitEstimate apart from the unit_id label.
    # Replicating the template avoids N redundant estimator calls when N
    # may be 200+ for large Class B/C properties.
    template = estimate_unit(
        unit_sqft=floor_plan.sqft,
        bedrooms=floor_plan.bedrooms,
        bathrooms=floor_plan.bathrooms,
        scope_level=req.cohort.scope_level,
        finish_tier=req.cohort.finish_tier,
        year_built=prop.year_built,
        property_class=prop.property_class.value if prop.property_class else None,
        market=prop.market,
    )
    unit_estimates = [
        template.model_copy(update={"unit_id": f"{floor_plan.name}-{i + 1:03d}"})
        for i in range(req.cohort.unit_count)
    ]

    cohort_total_low = sum(ue.total_low for ue in unit_estimates)
    cohort_total_high = sum(ue.total_high for ue in unit_estimates)
    per_unit_low = cohort_total_low / req.cohort.unit_count
    per_unit_high = cohort_total_high / req.cohort.unit_count

    # ROI gate uses the conservative high cost. Line items come from the
    # first unit because every unit in a cohort shares the same FloorPlan
    # and so produces the same line items — only quantity differs.
    roi = check_roi(
        total_cost_high=per_unit_high,
        current_monthly_rent=req.cohort.current_monthly_rent,
        target_monthly_rent=req.cohort.target_monthly_rent,
        line_items=unit_estimates[0].line_items if unit_estimates else None,
    )

    # Aggregate risk flags. Dedup by (message, flag_type) so two flags
    # with the same wording but different types (e.g. lead_paint vs
    # asbestos worded similarly) both surface.
    seen: set[tuple[str, str]] = set()
    risk_flags = []
    for ue in unit_estimates:
        for rf in ue.risk_flags:
            key = (rf.message, rf.flag_type)
            if key not in seen:
                seen.add(key)
                risk_flags.append(rf)

    persisted_req = ScopeRepo(conn).create(req)
    est = ScopeEstimate(
        estimate_id="",
        scope_request_id=persisted_req.scope_request_id,
        property_id=prop.property_id,
        floor_plan_id=floor_plan.floor_plan_id,
        pricing_snapshot_id=snap.snapshot_id,
        unit_estimates=unit_estimates,
        cohort_total_low=cohort_total_low,
        cohort_total_high=cohort_total_high,
        per_unit_average_low=per_unit_low,
        per_unit_average_high=per_unit_high,
        roi_result=roi,
        risk_flags=risk_flags,
        sanity_flags=[],
        estimated_at=datetime.now(timezone.utc),
    )
    return EstimateRepo(conn).create(est)


def _estimate_exterior(req: ScopeRequest, conn: sqlite3.Connection) -> ScopeEstimate:
    """Compute and persist an ExteriorScopeEstimate for an ExteriorCohort request."""
    import yaml

    from plat_costmodel.exterior_estimator import estimate_exterior
    from plat_costmodel.risk import get_risk_flags
    from plat_costmodel.schemas import ExteriorScopeEstimate

    prop_repo = PropertyRepo(conn)
    prop = prop_repo.get(req.property_id)
    if prop is None:
        raise_problem(
            "not_found", f"property {req.property_id} not found",
            field_errors=[{"loc": ["property_id"], "msg": "not found"}],
        )

    snap = SnapshotRepo(conn).get_or_create_for_kb_hash(_kb_hash())

    with open(_KB_PATH) as f:
        kb = yaml.safe_load(f)

    components = estimate_exterior(req.cohort, kb)
    risk_flags = get_risk_flags(prop.year_built)

    persisted_req = ScopeRepo(conn).create(req)
    est = ExteriorScopeEstimate(
        estimate_id="",
        scope_request_id=persisted_req.scope_request_id,
        property_id=prop.property_id,
        pricing_snapshot_id=snap.snapshot_id,
        line_items=components["line_items"],
        total_low=components["total_low"],
        total_high=components["total_high"],
        per_unit_low=components["per_unit_low"],
        per_unit_high=components["per_unit_high"],
        payback_years_estimated=components["payback_years_estimated"],
        risk_flags=risk_flags,
        sanity_flags=[],
        estimated_at=datetime.now(timezone.utc),
    )
    return EstimateRepo(conn).create(est)


def _estimate_amenity(req: ScopeRequest, conn: sqlite3.Connection) -> ScopeEstimate:
    """Compute and persist an AmenityScopeEstimate for an AmenityCohort request."""
    import yaml

    from plat_costmodel.amenity_estimator import estimate_amenity
    from plat_costmodel.risk import get_risk_flags
    from plat_costmodel.schemas import AmenityScopeEstimate

    prop_repo = PropertyRepo(conn)
    prop = prop_repo.get(req.property_id)
    if prop is None:
        raise_problem(
            "not_found", f"property {req.property_id} not found",
            field_errors=[{"loc": ["property_id"], "msg": "not found"}],
        )

    snap = SnapshotRepo(conn).get_or_create_for_kb_hash(_kb_hash())

    with open(_KB_PATH) as f:
        kb = yaml.safe_load(f)

    components = estimate_amenity(req.cohort, kb)
    risk_flags = get_risk_flags(prop.year_built)

    persisted_req = ScopeRepo(conn).create(req)
    est = AmenityScopeEstimate(
        estimate_id="",
        scope_request_id=persisted_req.scope_request_id,
        property_id=prop.property_id,
        pricing_snapshot_id=snap.snapshot_id,
        amenity_type=req.cohort.amenity_type,
        install_cost_low=components["install_cost_low"],
        install_cost_high=components["install_cost_high"],
        annual_opex_low=components["annual_opex_low"],
        annual_opex_high=components["annual_opex_high"],
        expected_occupancy_lift_result=components["expected_occupancy_lift_result"],
        expected_rent_premium_result=components["expected_rent_premium_result"],
        risk_flags=risk_flags,
        sanity_flags=[],
        estimated_at=datetime.now(timezone.utc),
    )
    return EstimateRepo(conn).create(est)


def _build_scope_requests_from_projection(
    projection, prop: Property, repo: PropertyRepo
) -> list[ScopeRequest]:
    """Build a list of ScopeRequests from a DealProjection + resolved Property.

    Iterates over the projection's cohorts, resolves (or mints) the matching
    FloorPlan via ``resolve_floor_plan_by_dims``, and constructs a
    ``ScopeRequest`` for each cohort.

    .. deprecated::
        Only the legacy ``project_deal_to_scope_requests`` shim in
        ``bridge/deal_projection.py`` calls this helper.  ``estimate_from_deal``
        no longer delegates here — it uses ``_scenario_to_scope_request``
        directly.  This function will be removed in a future cleanup PR.

    Args:
        projection: A ``DealProjection`` returned by ``project_deal``.
        prop: The already-resolved ``Property`` row.
        repo: Open ``PropertyRepo`` for floor-plan look-up / creation.

    Returns:
        Index-aligned list of ``ScopeRequest`` objects (one per program).
    """
    requests: list[ScopeRequest] = []
    for c in projection.cohorts:
        fp = resolve_floor_plan_by_dims(
            repo, prop.property_id, c.sqft, c.bedrooms, c.bathrooms
        )
        requests.append(ScopeRequest(
            property_id=prop.property_id,
            program_type=c.program_type,
            cohort=UnitCohort(
                floor_plan_id=fp.floor_plan_id,
                unit_count=c.unit_count,
                scope_level=c.scope_level,
                finish_tier=c.finish_tier,
                current_monthly_rent=c.current_monthly_rent,
                target_monthly_rent=c.target_monthly_rent,
            ),
            schedule=c.schedule,
            requested_by="deal_projection",
        ))
    return requests


def _scenario_to_scope_request(
    scenario: ScenarioUnion,
    cohort_lookup: dict[str, dict],
    prop,
    prop_repo: PropertyRepo,
) -> ScopeRequest:
    """Project a single scenario onto a ScopeRequest using the deal's
    cohort lookup + the resolved Property + FloorPlan registry.

    Interior scenarios resolve their cohort dimensions from
    ``cohort_lookup[scenario.cohort_id]``; the other variants are
    property-scoped and ignore the lookup.
    """
    if isinstance(scenario, InteriorScenario):
        cohort_data = cohort_lookup.get(scenario.cohort_id)
        if cohort_data is None:
            raise_problem(
                "validation_error",
                f"InteriorScenario references unknown cohort_id={scenario.cohort_id!r}",
                field_errors=[{
                    "loc": ["scenarios", "cohort_id"],
                    "msg": f"cohort_id {scenario.cohort_id!r} not in deal.unit_cohorts",
                }],
                hint="cohort_id must match one of the deal's unit_cohorts entries.",
            )
        fp = resolve_floor_plan_by_dims(
            prop_repo, prop.property_id,
            float(cohort_data["avg_sqft"]),
            int(cohort_data["avg_bedrooms"]),
            int(cohort_data["avg_bathrooms"]),
        )
        current_rent = float(cohort_data["current_avg_rent"])
        return ScopeRequest(
            property_id=prop.property_id,
            program_type=ProgramType.INTERIOR_RENOVATION,
            cohort=UnitCohort(
                floor_plan_id=fp.floor_plan_id,
                unit_count=int(cohort_data["unit_count"]),
                scope_level=scenario.scope_level,
                finish_tier=scenario.finish_tier,
                current_monthly_rent=current_rent,
                target_monthly_rent=current_rent + scenario.rent_premium_monthly,
            ),
            schedule=scenario.schedule,
            requested_by="estimate_from_deal",
        )

    # Property-scoped scenarios. The cohorts produced here route to their
    # respective _estimate_* stubs via estimate_scope's per-type dispatch.
    if isinstance(scenario, ExteriorScenario):
        return ScopeRequest(
            property_id=prop.property_id,
            program_type=ProgramType.EXTERIOR_RENOVATION,
            cohort=ExteriorCohort(
                items=scenario.items,
                total_units=prop.total_units,
                expected_rent_class_shift=scenario.expected_rent_class_shift,
                payback_years_target=scenario.payback_years_target,
            ),
            schedule=scenario.schedule,
            requested_by="estimate_from_deal",
        )
    if isinstance(scenario, AmenityScenario):
        return ScopeRequest(
            property_id=prop.property_id,
            program_type=ProgramType.AMENITY_ADDITION,
            cohort=AmenityCohort(
                amenity_type=scenario.amenity_type,
                quantity=scenario.quantity,
                deluxe=scenario.deluxe,
                expected_occupancy_lift_pct=scenario.expected_occupancy_lift_pct,
                expected_rent_premium_monthly=scenario.expected_rent_premium_monthly,
            ),
            schedule=scenario.schedule,
            requested_by="estimate_from_deal",
        )
    if isinstance(scenario, DeferredMaintenanceScenario):
        return ScopeRequest(
            property_id=prop.property_id,
            program_type=ProgramType.DEFERRED_MAINTENANCE,
            cohort=DeferredMaintenanceCohort(
                items=scenario.items,
                total_units=prop.total_units,
                age_at_replacement_years=scenario.age_at_replacement_years,
                condition=scenario.condition,
            ),
            schedule=scenario.schedule,
            requested_by="estimate_from_deal",
        )
    raise_problem(
        "validation_error",
        f"unsupported scenario type: {type(scenario).__name__}",
    )


def estimate_from_deal(
    deal: dict,
    scenarios: list[ScenarioUnion],
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    """Project a deal + scenarios into per-scenario ScopeRequests, estimate each,
    project results back to renovation_program dicts.

    The returned ``estimates`` list is **index-aligned** with ``scenarios``:
    ``estimates[i]`` corresponds to ``scenarios[i]``. Successful runs return a
    ``ScopeEstimate`` variant per scenario. Interior, exterior (PR 3), and
    amenity (PR 4) scenarios produce real estimates; deferred-maintenance
    scenarios still surface as a ``dict`` carrying a ``not_implemented``
    error_type until per-type dispatch lands in slice B PR 5.
    Validation errors (e.g. unknown cohort_id) raise immediately and abort the
    run — successful estimates from earlier scenarios in the same list ARE
    persisted before the abort, leaving orphaned ScopeRequest + ScopeEstimate
    rows. This is by design (we want partial work preserved for audit) but a
    future PR should consider adding cleanup tooling.

    ``renovation_programs[i]`` is also index-aligned with ``scenarios[i]``: a
    ``ScopeEstimate`` slot has a populated dict; a not_implemented slot has ``None``.
    """
    own_conn = conn is None
    conn = conn or connect()
    try:
        adapter = TypeAdapter(list[ScenarioUnion])
        scenarios = adapter.validate_python(scenarios)

        projection = project_deal(deal)
        prop_repo = PropertyRepo(conn)
        prop = resolve_property(prop_repo, projection.property)

        estimates: list = []
        renovation_programs: list = []
        for scenario in scenarios:
            try:
                req = _scenario_to_scope_request(
                    scenario, projection.cohort_lookup, prop, prop_repo,
                )
                est = estimate_scope(req, conn=conn)
                estimates.append(est)
                renovation_programs.append(
                    project_estimate_to_renovation_program(est, scenario.schedule)
                )
            except ValueError as e:
                vp = getattr(e, "validation_problem", None)
                if vp is not None and getattr(vp, "error_type", None) == "not_implemented":
                    estimates.append(vp.model_dump(mode="json"))
                    renovation_programs.append(None)
                    continue
                raise

        return {"estimates": estimates, "renovation_programs": renovation_programs}
    finally:
        if own_conn:
            conn.close()
