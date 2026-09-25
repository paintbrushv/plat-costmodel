"""multifamily-underwriting deal JSON → plat-costmodel ScopeRequest(s).

The deal schema (schema_version 0.1) carries a ``unit_cohorts`` array and
a ``renovation_programs`` array. Each program references a cohort by
index.

``project_deal`` is a **pure function** — it reads the deal dict and returns
a ``DealProjection`` describing the property payload and per-program cohort
intents, with no database access. Callers (``scope_service``) own the
resolution of those intents into Property + FloorPlan rows.

FloorPlan join key in v1: ``(sqft, bedrooms, bathrooms)``. If no match,
the resolver will mint a new FloorPlan named
``auto:<sqft>sf-<beds>x<baths>``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

from plat_costmodel.models import FinishTier, ScopeLevel
from plat_costmodel.schemas import (
    ProgramSchedule,
    ProgramType,
    ScopeRequest,
    UnitCohort,
    raise_problem,
)

if TYPE_CHECKING:
    # `sqlite3` and `store.*` are only used by the deprecated shim
    # ``project_deal_to_scope_requests``. Keeping them out of the module-
    # level import block preserves bridge-layer purity: importing
    # ``plat_costmodel.bridge`` no longer pulls in the persistence layer.
    import sqlite3  # noqa: F401


class CohortProjection(BaseModel):
    """Per-program intent — fields a caller needs to mint floor_plan + build ScopeRequest."""

    cohort_id: str
    sqft: float
    bedrooms: int
    bathrooms: int
    unit_count: int
    scope_level: ScopeLevel
    finish_tier: FinishTier
    current_monthly_rent: float
    target_monthly_rent: float
    schedule: ProgramSchedule
    program_type: ProgramType


class DealProjection(BaseModel):
    """Pure-projection result: describes Property to resolve and per-program
    cohorts, no side effects. Caller (scope_service) does the resolution."""

    property: dict  # ready for resolve_property
    cohorts: list[CohortProjection]
    cohort_lookup: dict[str, dict]  # id → raw cohort dict (backfilled + explicit)


def project_deal(deal: dict) -> DealProjection:
    """Translate a deal dict into a pure DealProjection.

    No database access. Returns a description of the property to resolve and
    per-program cohort intents. The caller (scope_service) is responsible for
    calling resolve_property / resolve_floor_plan_by_dims and building the
    final ScopeRequests.
    """
    _validate_top_level(deal)

    cohorts_raw = deal.get("unit_cohorts", [])
    programs = deal.get("renovation_programs", [])

    # Build a parallel id-keyed lookup. Existing fixtures use cohort_index only;
    # canonical id form is the explicit string when provided, else cohort_<i>.
    cohort_lookup: dict[str, dict] = {}
    indexed_cohorts: list[dict] = []  # parallel to cohorts_raw, with cohort_id present
    for i, c in enumerate(cohorts_raw):
        if "cohort_id" not in c:
            cid = f"cohort_{i}"
        else:
            raw_cid = c["cohort_id"]
            if not isinstance(raw_cid, str) or not raw_cid:
                raise_problem(
                    "validation_error",
                    f"unit_cohorts[{i}].cohort_id must be a non-empty string when present",
                    field_errors=[{
                        "loc": ["unit_cohorts", i, "cohort_id"],
                        "msg": "must be a non-empty string when present",
                    }],
                    hint="Omit cohort_id to auto-backfill, or provide a non-empty string identifier.",
                )
            cid = raw_cid
        c_with_id = {**c, "cohort_id": cid}
        cohort_lookup[cid] = c_with_id
        indexed_cohorts.append(c_with_id)

    cohort_projections: list[CohortProjection] = []
    for prog_idx, prog in enumerate(programs):
        cohort_idx = prog.get("cohort_index")
        if cohort_idx is None:
            raise_problem(
                "validation_error",
                f"renovation_programs[{prog_idx}] missing cohort_index",
                field_errors=[{
                    "loc": ["renovation_programs", prog_idx, "cohort_index"],
                    "msg": "field required",
                }],
                hint="Each renovation_program must reference a cohort by index.",
            )
        if cohort_idx >= len(indexed_cohorts):
            raise_problem(
                "validation_error",
                f"cohort_index {cohort_idx} out of range",
                field_errors=[{
                    "loc": ["renovation_programs", prog_idx, "cohort_index"],
                    "msg": f"index out of range (have {len(indexed_cohorts)} cohorts)",
                }],
            )
        cohort = indexed_cohorts[cohort_idx]
        sqft = float(cohort["avg_sqft"])
        beds = int(cohort["avg_bedrooms"])
        baths = int(cohort["avg_bathrooms"])
        current_rent = float(cohort["current_avg_rent"])
        rent_premium = float(prog["rent_premium_monthly"])
        cohort_projections.append(CohortProjection(
            cohort_id=cohort["cohort_id"],
            sqft=sqft,
            bedrooms=beds,
            bathrooms=baths,
            unit_count=int(cohort["unit_count"]),
            scope_level=ScopeLevel(prog.get("scope_level", "standard_value_add")),
            finish_tier=FinishTier(prog.get("finish_tier", "basic")),
            current_monthly_rent=current_rent,
            target_monthly_rent=current_rent + rent_premium,
            schedule=ProgramSchedule(
                start_month=prog["start_month"],
                monthly_pace=int(prog["monthly_pace"]),
                downtime_days=int(prog.get("downtime_days", 21)),
            ),
            program_type=ProgramType.INTERIOR_RENOVATION,
        ))

    return DealProjection(
        property=deal["property"],
        cohorts=cohort_projections,
        cohort_lookup=cohort_lookup,
    )


def project_deal_to_scope_requests(deal: dict, conn) -> list[ScopeRequest]:
    """DEPRECATED: prefer ``project_deal`` + ``scope_service.estimate_from_deal``.

    Kept as a thin shim that does the resolve-then-build steps the bridge
    used to do internally. New code should call project_deal() and let
    scope_service own the writes.

    ``conn`` is a ``sqlite3.Connection``; the type is left untyped here so
    the bridge module does not need to import ``sqlite3`` at module scope
    (preserves bridge-layer purity — importing ``plat_costmodel.bridge``
    must not pull in the persistence layer).
    """
    # Local imports so this module's top-level stays bridge-pure. The
    # deprecated shim is the only path that needs the store.
    from plat_costmodel.scope_service import _build_scope_requests_from_projection
    from plat_costmodel.store.ids import resolve_property
    from plat_costmodel.store.repo import PropertyRepo

    projection = project_deal(deal)
    repo = PropertyRepo(conn)
    prop = resolve_property(repo, projection.property)
    return _build_scope_requests_from_projection(projection, prop, repo)


def _validate_top_level(deal: dict) -> None:
    if not isinstance(deal, dict):
        raise_problem("validation_error", "deal must be a dict")
    if "property" not in deal:
        raise_problem(
            "validation_error", "deal missing 'property'",
            field_errors=[{"loc": ["property"], "msg": "field required"}],
        )
    if "unit_cohorts" not in deal:
        raise_problem(
            "validation_error", "deal missing 'unit_cohorts'",
            field_errors=[{"loc": ["unit_cohorts"], "msg": "field required"}],
        )
    if "renovation_programs" not in deal:
        raise_problem(
            "validation_error", "deal missing 'renovation_programs'",
            field_errors=[{"loc": ["renovation_programs"], "msg": "field required"}],
        )
    # An empty programs list silently returns {"estimates": []} downstream,
    # which masks the realistic upstream-agent mistake of forgetting to
    # populate the array. Treat as an explicit validation error.
    if not deal["renovation_programs"]:
        raise_problem(
            "validation_error", "deal has empty renovation_programs",
            field_errors=[{"loc": ["renovation_programs"], "msg": "must be non-empty"}],
            hint="A deal with no renovation programs has nothing to estimate.",
        )
