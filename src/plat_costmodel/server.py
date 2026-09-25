"""MCP tool server for plat-costmodel."""

import functools

from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from .bid_eval import evaluate_bid
from .bridge import prepare_renovation_program
from .estimator import estimate_property, estimate_unit
from .models import (
    BidLineItem,
    ContractorBid,
    FinishTier,
    PropertyEstimateInput,
    ScopeLevel,
    UnitSpec,
)
from .roi import check_roi
from .schemas import (
    Property,
    ScopeRequest,
    ValidationProblem,
)
from .scope_service import estimate_from_deal as _estimate_from_deal_service
from .scope_service import estimate_scope as _estimate_scope_service
from .sow import generate_sow
from .store.db import connect
from .store.ids import resolve_floor_plan_by_dims as _resolve_floor_plan_by_dims
from .store.ids import resolve_property as _resolve_property
from .store.repo import PropertyRepo


def _validated(handler):
    """Wrap an MCP tool handler so schema/value/key errors come back as
    structured ValidationProblem dicts instead of being swallowed by the
    FastMCP TaskGroup wrapper.

    Errors raised by service-layer code may carry a ``.validation_problem``
    attribute; we honor that shape verbatim.
    """
    @functools.wraps(handler)
    def wrapper(*args, **kwargs):
        try:
            return handler(*args, **kwargs)
        except ValidationError as e:
            return ValidationProblem(
                error_type="validation_error",
                message=f"{handler.__name__} input failed validation",
                field_errors=[
                    {"loc": list(err["loc"]), "msg": err["msg"]}
                    for err in e.errors()
                ],
                hint="See field_errors for fields that need correction.",
            ).model_dump()
        except ValueError as e:
            vp = getattr(e, "validation_problem", None)
            if isinstance(vp, ValidationProblem):
                return vp.model_dump()
            roi = getattr(e, "roi_result", None)
            return ValidationProblem(
                error_type="roi_failure" if roi else "value_error",
                message=str(e),
                hint=roi.note if roi else "",
            ).model_dump()
        except KeyError as e:
            return ValidationProblem(
                error_type="not_found",
                message=f"missing required key: {e}",
            ).model_dump()
    return wrapper

mcp = FastMCP("plat-costmodel")


@mcp.tool()
@_validated
def estimate(
    unit_sqft: float,
    bedrooms: int,
    bathrooms: int,
    scope_level: str = "standard_value_add",
    finish_tier: str = "basic",
    year_built: int | None = None,
    property_class: str | None = None,
    market: str | None = None,
    unit_id: str = "",
) -> dict:
    """Estimate per-unit renovation cost with line-item breakdown.

    Args:
        unit_sqft: Unit square footage (drives size category: <700 small, 700-950 medium, 950+ large)
        bedrooms: Number of bedrooms
        bathrooms: Number of bathrooms (bathroom costs multiply by this)
        scope_level: "light" ($3K-$5K) or "standard_value_add" ($12K-$18K)
        finish_tier: "basic" or "upgraded" (granite, backsplash, stainless)
        year_built: Property year built (triggers risk flags)
        property_class: "B" or "C"
        market: "dallas" or "birmingham"
        unit_id: Optional unit identifier
    """
    result = estimate_unit(
        unit_sqft=unit_sqft,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        scope_level=scope_level,
        finish_tier=finish_tier,
        year_built=year_built,
        property_class=property_class,
        market=market,
        unit_id=unit_id,
    )
    return result.model_dump()


@mcp.tool()
@_validated
def estimate_full_property(
    property_id: str,
    total_units: int,
    units: list[dict],
    year_built: int | None = None,
    property_class: str | None = None,
    market: str | None = None,
    exterior_items: list[str] | None = None,
) -> dict:
    """Property-level estimate rolling up unit costs + exterior CapEx.

    Args:
        property_id: Property identifier
        total_units: Total units at the property
        units: List of unit dicts with keys: unit_id, sqft, bedrooms, bathrooms, scope_level, finish_tier
        year_built: Property year built
        property_class: "B" or "C"
        market: "dallas" or "birmingham"
        exterior_items: Exterior CapEx categories to include (default: all). Options: roof, parking, hvac, siding_paint, fencing_gates, landscaping, signage_lighting
    """
    prop = PropertyEstimateInput(
        property_id=property_id,
        total_units=total_units,
        unit_mix=[
            UnitSpec(
                unit_id=u.get("unit_id", ""),
                sqft=u["sqft"],
                bedrooms=u["bedrooms"],
                bathrooms=u["bathrooms"],
                scope_level=u.get("scope_level", "standard_value_add"),
                finish_tier=u.get("finish_tier", "basic"),
            )
            for u in units
        ],
        year_built=year_built,
        property_class=property_class,
        market=market,
        exterior_items=exterior_items,
    )
    result = estimate_property(prop)
    return result.model_dump()


@mcp.tool()
@_validated
def estimate_property_from_model(
    property_data: dict,
) -> dict:
    """Property-level estimate using the Property entity model.

    Accepts a single property dict containing all property context and unit mix.
    This is the preferred API for Plat — replaces loose kwargs.

    Args:
        property_data: Dict with keys:
            - property_id (str, required)
            - total_units (int, required)
            - unit_mix (list of dicts with: sqft, bedrooms, bathrooms, scope_level, finish_tier, count)
            - year_built (int, optional)
            - property_class ("B" or "C", optional)
            - market (str, optional)
            - building_type (str, optional)
            - exterior_items (list of str, optional)
    """
    prop = PropertyEstimateInput(**property_data)
    result = estimate_property(prop)
    return result.model_dump()


@mcp.tool()
@_validated
def check_renovation_roi(
    total_cost_high: float,
    current_monthly_rent: float,
    target_monthly_rent: float,
    threshold_pct: float = 15.0,
) -> dict:
    """Check whether a renovation plan clears the minimum ROI threshold.

    Uses the HIGH cost estimate (conservative). Formula: (annual_rent_lift / total_cost_high) * 100.
    Default threshold is 15%.

    Args:
        total_cost_high: High-end total renovation cost estimate
        current_monthly_rent: Current monthly rent
        target_monthly_rent: Expected post-renovation monthly rent
        threshold_pct: Minimum ROI percentage (default 15%)
    """
    result = check_roi(total_cost_high, current_monthly_rent, target_monthly_rent, threshold_pct)
    return result.model_dump()


@mcp.tool()
@_validated
def generate_scope_of_work(
    unit_sqft: float,
    bedrooms: int,
    bathrooms: int,
    scope_level: str = "standard_value_add",
    finish_tier: str = "basic",
    property_address: str = "",
    unit_id: str = "",
) -> dict:
    """Generate a detailed scope of work (SOW) for contractor bidding.

    Produces a contractor-ready document with material specs, quantities, and quality standards.

    Args:
        unit_sqft: Unit square footage
        bedrooms: Number of bedrooms
        bathrooms: Number of bathrooms
        scope_level: "light" or "standard_value_add"
        finish_tier: "basic" or "upgraded"
        property_address: Property street address
        unit_id: Unit number/identifier
    """
    result = generate_sow(
        unit_sqft=unit_sqft,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        scope_level=scope_level,
        finish_tier=finish_tier,
        property_address=property_address,
        unit_id=unit_id,
    )
    return result.model_dump()


@mcp.tool()
@_validated
def evaluate_contractor_bid(
    contractor_name: str,
    bid_line_items: list[dict],
    bid_total: float,
    timeline_days: int | None,
    unit_sqft: float,
    bedrooms: int,
    bathrooms: int,
    scope_level: str = "standard_value_add",
    finish_tier: str = "basic",
    year_built: int | None = None,
) -> dict:
    """Evaluate a contractor bid against the internal cost estimate.

    Flags: inflated line items (30%+ above benchmark), vague lump sums,
    unrealistic timelines.

    Args:
        contractor_name: Name of the contractor
        bid_line_items: List of dicts with "description" and "amount" keys
        bid_total: Total bid amount
        timeline_days: Proposed timeline in days (None if not specified)
        unit_sqft: Unit square footage for generating comparison estimate
        bedrooms: Number of bedrooms
        bathrooms: Number of bathrooms
        scope_level: "light" or "standard_value_add"
        finish_tier: "basic" or "upgraded"
        year_built: Property year built
    """
    bid = ContractorBid(
        contractor_name=contractor_name,
        line_items=[BidLineItem(**item) for item in bid_line_items],
        total=bid_total,
        timeline_days=timeline_days,
    )
    est = estimate_unit(
        unit_sqft=unit_sqft,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        scope_level=scope_level,
        finish_tier=finish_tier,
        year_built=year_built,
    )
    result = evaluate_bid(bid, est)
    return result.model_dump()


@mcp.tool()
@_validated
def prepare_renovation_program_tool(
    unit_sqft: float,
    bedrooms: int,
    bathrooms: int,
    current_monthly_rent: float,
    target_monthly_rent: float,
    start_month: str,
    monthly_pace: int,
    scope_level: str = "standard_value_add",
    finish_tier: str = "basic",
    year_built: int | None = None,
    property_class: str | None = None,
    market: str | None = None,
    unit_id: str = "",
    downtime_days: int = 21,
    threshold_pct: float = 15.0,
) -> dict:
    """Estimate unit cost, validate ROI, and produce underwriting-ready renovation program input.

    Runs the full pipeline: estimate → ROI gate → bridge dict matching the
    multifamily-underwriting deal schema's renovation_program shape.

    Returns a dict with:
      - renovation_program: ready to splice into the deal JSON
      - roi_result: full ROI gate result for audit trail
      - ready_to_underwrite: True if ROI gate passed

    If the ROI gate fails, returns the result with ready_to_underwrite=False
    and the roi_result containing path_to_pass guidance.

    Args:
        unit_sqft: Unit square footage (drives size category)
        bedrooms: Number of bedrooms
        bathrooms: Number of bathrooms
        current_monthly_rent: Current monthly rent
        target_monthly_rent: Expected post-renovation monthly rent
        start_month: Renovation start month ("YYYY-MM")
        monthly_pace: Units renovated per month
        scope_level: "light" or "standard_value_add"
        finish_tier: "basic" or "upgraded"
        year_built: Property year built (triggers risk flags)
        property_class: "B" or "C"
        market: "dallas" or "birmingham"
        unit_id: Optional unit identifier
        downtime_days: Vacancy days per unit during renovation (default 21)
        threshold_pct: Minimum ROI percentage (default 15%)
    """
    try:
        result = prepare_renovation_program(
            unit_sqft=unit_sqft,
            bedrooms=bedrooms,
            bathrooms=bathrooms,
            current_monthly_rent=current_monthly_rent,
            target_monthly_rent=target_monthly_rent,
            start_month=start_month,
            monthly_pace=monthly_pace,
            scope_level=scope_level,
            finish_tier=finish_tier,
            year_built=year_built,
            property_class=property_class,
            market=market,
            unit_id=unit_id,
            downtime_days=downtime_days,
            threshold_pct=threshold_pct,
        )
        return result.model_dump()
    except ValueError as e:
        # ROI gate failed — return structured failure instead of crashing.
        # The legacy fields (renovation_program shell, roi_result, ready_to_underwrite)
        # are preserved for callers that depend on the deal-splice shape.
        # The ValidationProblem-compatible fields (error_type, message, hint,
        # field_errors) are also populated so callers using the standard
        # MCP error-detection contract (`if "error_type" in result`) work too.
        # This intentionally bypasses the @_validated wrapper because this
        # tool's failure shape is richer than ValidationProblem alone.
        roi_result = e.roi_result if hasattr(e, "roi_result") else None
        rent_premium = target_monthly_rent - current_monthly_rent
        return {
            "error_type": "roi_failure",
            "message": str(e),
            "field_errors": [],
            "hint": roi_result.note if roi_result else "",
            "renovation_program": {
                "renovation_cost_per_unit": None,
                "rent_premium_monthly": rent_premium,
                "downtime_days": downtime_days,
                "strategy": "renovation",
                "start_month": start_month,
                "monthly_pace": monthly_pace,
            },
            "roi_result": roi_result.model_dump() if roi_result else {"note": str(e)},
            "ready_to_underwrite": False,
        }


@mcp.tool()
@_validated
def register_property(property_data: dict) -> dict:
    """Idempotent property registration.

    Accepts a Property-shaped dict (and optional inline ``floor_plans``).
    Mints ``property_id`` if missing or returns the existing row when
    ``external_alias`` matches.

    Inline ``floor_plans`` are deduped by ``(sqft, bedrooms, bathrooms)``:
    an existing match is reused, otherwise a new FloorPlan is created. This
    means calling register_property twice with the same alias and a NEW
    floor plan in the payload correctly creates the new floor plan on the
    second call (the previous behavior silently dropped it).
    """
    conn = connect()
    try:
        repo = PropertyRepo(conn)
        saved = _resolve_property(repo, property_data)
        for fp_data in property_data.get("floor_plans", []):
            sqft = fp_data["sqft"]
            beds = fp_data["bedrooms"]
            baths = fp_data["bathrooms"]
            _resolve_floor_plan_by_dims(
                repo,
                saved.property_id,
                sqft,
                beds,
                baths,
                name=fp_data.get("name"),
                notes=fp_data.get("notes"),
                external_alias=fp_data.get("external_alias"),
            )
        full = repo.get(saved.property_id)
        return {
            "property_id": full.property_id,
            "floor_plans": [fp.model_dump() for fp in full.floor_plans],
        }
    finally:
        conn.close()


@mcp.tool()
@_validated
def estimate_scope(scope_request_dict: dict) -> dict:
    """Canonical entry point: estimate a ScopeRequest, persist (request, estimate).

    Returns the ScopeEstimate as a dict, or a ValidationProblem dict on error.
    """
    conn = connect()
    try:
        request = ScopeRequest.model_validate(scope_request_dict)
        estimate = _estimate_scope_service(request, conn=conn)
        return estimate.model_dump(mode="json")
    finally:
        conn.close()


@mcp.tool()
@_validated
def estimate_from_deal(deal_dict: dict, scenarios_list: list) -> dict:
    """Project deal + scenarios → per-scenario ScopeRequest(s), estimate each,
    project back to renovation_program dicts.

    Returns ``{estimates, renovation_programs}`` index-aligned with
    ``scenarios_list``. ``estimates[i]`` is a ScopeEstimate dict on success or a
    problem dict (``error_type``-bearing) when the scenario hits the
    not_implemented guard. Per-type dispatch lands in slice B PR 3.
    """
    conn = connect()
    try:
        result = _estimate_from_deal_service(deal_dict, scenarios_list, conn=conn)
        rendered_estimates = []
        for e in result["estimates"]:
            if hasattr(e, "model_dump"):
                rendered_estimates.append(e.model_dump(mode="json"))
            else:
                # already a dict (e.g. not_implemented problem)
                rendered_estimates.append(e)
        return {
            "estimates": rendered_estimates,
            "renovation_programs": result["renovation_programs"],
        }
    finally:
        conn.close()


@mcp.tool()
@_validated
def get_property_history(property_id: str) -> list:
    """Return all (scope_request, scope_estimate, actual_outcome) triples
    for a property as a list of dicts. Empty list if property has no history."""
    conn = connect()
    try:
        triples = PropertyRepo(conn).get_history(property_id)
        return [
            {
                "scope_request": t["scope_request"].model_dump(mode="json"),
                "scope_estimate": (
                    t["scope_estimate"].model_dump(mode="json")
                    if t["scope_estimate"] else None
                ),
                "actual_outcome": (
                    t["actual_outcome"].model_dump(mode="json")
                    if t["actual_outcome"] else None
                ),
            }
            for t in triples
        ]
    finally:
        conn.close()


def main():
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
