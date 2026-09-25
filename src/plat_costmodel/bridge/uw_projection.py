"""ScopeEstimate → multifamily-underwriting renovation_program dict.

Also hosts the legacy per-unit projection that ``bridge.py`` shipped in v1
(``build_renovation_program_input``, ``prepare_renovation_program``,
``validate_against_roi``, ``BridgeResult``). The legacy API is re-exported
from ``plat_costmodel.bridge`` for backwards compatibility.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from pydantic import BaseModel, Field

from plat_costmodel.estimator import estimate_unit
from plat_costmodel.models import FinishTier, ScopeLevel, UnitEstimate
from plat_costmodel.roi import check_roi, ROIResult
from plat_costmodel.schemas import ProgramSchedule, ScopeEstimate


def _q2(value: float) -> float:
    """Quantize a float to 2dp without binary-float drift.

    Per audit Bug 2.3 + Family F (Float vs Decimal coercion), all currency
    written into the federation boundary is quantized to 2dp here.
    """
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


class BridgeResult(BaseModel):
    """Output of the bridge: underwriting-ready renovation program + ROI validation."""

    renovation_program: dict = Field(
        description="Dict matching the underwriting deal schema renovation_program shape.",
    )
    roi_result: ROIResult
    ready_to_underwrite: bool


def validate_against_roi(
    estimate: UnitEstimate,
    current_monthly_rent: float,
    target_monthly_rent: float,
    threshold_pct: float = 15.0,
) -> ROIResult:
    """Run the ROI gate on an estimate and return the full result."""
    return check_roi(
        total_cost_high=estimate.total_high,
        current_monthly_rent=current_monthly_rent,
        target_monthly_rent=target_monthly_rent,
        threshold_pct=threshold_pct,
        line_items=estimate.line_items,
    )


def build_renovation_program_input(
    estimate: UnitEstimate,
    current_monthly_rent: float,
    target_monthly_rent: float,
    start_month: str,
    monthly_pace: int,
    downtime_days: int = 21,
    threshold_pct: float = 15.0,
) -> BridgeResult:
    """Build a renovation program dict for the underwriting engine.

    Uses ``estimate.total_high`` as ``renovation_cost_per_unit`` (conservative).
    Validates the ROI gate before producing the output.

    Raises:
        ValueError: If the ROI gate fails. The exception message includes the
            ROI result note, and the full :class:`ROIResult` is attached as
            ``exception.roi_result`` for callers that want to surface
            path-to-pass guidance to the user.
    """
    roi_result = validate_against_roi(
        estimate=estimate,
        current_monthly_rent=current_monthly_rent,
        target_monthly_rent=target_monthly_rent,
        threshold_pct=threshold_pct,
    )

    rent_premium = _q2(target_monthly_rent - current_monthly_rent)
    renovation_cost_per_unit = _q2(estimate.total_high)

    renovation_program = {
        "renovation_cost_per_unit": renovation_cost_per_unit,
        "rent_premium_monthly": rent_premium,
        "downtime_days": downtime_days,
        "strategy": "renovation",
        "start_month": start_month,
        "monthly_pace": monthly_pace,
    }

    if not roi_result.clears_threshold:
        err = ValueError(
            f"ROI gate failed: {roi_result.roi_pct:.1f}% < {threshold_pct:.0f}% threshold. "
            f"{roi_result.note}"
        )
        err.roi_result = roi_result
        raise err

    return BridgeResult(
        renovation_program=renovation_program,
        roi_result=roi_result,
        ready_to_underwrite=True,
    )


def prepare_renovation_program(
    unit_sqft: float,
    bedrooms: int,
    bathrooms: int,
    current_monthly_rent: float,
    target_monthly_rent: float,
    start_month: str,
    monthly_pace: int,
    scope_level: ScopeLevel | str = ScopeLevel.STANDARD_VALUE_ADD,
    finish_tier: FinishTier | str = FinishTier.BASIC,
    year_built: int | None = None,
    property_class: str | None = None,
    market: str | None = None,
    unit_id: str = "",
    downtime_days: int = 21,
    threshold_pct: float = 15.0,
) -> BridgeResult:
    """End-to-end: estimate a unit, validate ROI, and produce underwriting input."""
    estimate = estimate_unit(
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
    return build_renovation_program_input(
        estimate=estimate,
        current_monthly_rent=current_monthly_rent,
        target_monthly_rent=target_monthly_rent,
        start_month=start_month,
        monthly_pace=monthly_pace,
        downtime_days=downtime_days,
        threshold_pct=threshold_pct,
    )


def project_estimate_to_renovation_program(
    estimate,
    schedule: ProgramSchedule,
) -> dict:
    """Project a ScopeEstimate variant into the underwriting renovation_program shape.

    Uses the conservative per-unit high cost. Returns a plain dict ready to
    splice into the deal JSON's ``renovation_programs[]``.

    Interior estimates: ``per_unit_average_high`` for cost; rent_premium_monthly
    derived from ``roi_result.target_monthly_rent - current_monthly_rent``.

    Non-interior variants (exterior, deferred): ``per_unit_high`` for cost;
    ``rent_premium_monthly`` is ``None`` because these programs do not encode a
    per-unit rent delta. Downstream consumers must guard against None on this
    field.

    For amenity estimates: ``install_cost_high`` is mapped to
    ``renovation_cost_per_unit`` as a property-level cost (amenity costs are not
    per-unit). ``rent_premium_monthly`` comes from the
    ``expected_rent_premium_result.projected_premium_monthly`` if the gate was
    computed, else None. Downstream consumers must be aware that amenity rows
    aren't per-unit math and must guard against None.
    """
    from plat_costmodel.schemas import AmenityScopeEstimate, InteriorScopeEstimate

    # isinstance — not hasattr — so a future variant adding a like-named
    # attribute can't silently route into the interior branch, and a non-
    # interior variant missing per_unit_high (e.g. AmenityScopeEstimate uses
    # install_cost_*) raises a clear type error rather than a deferred
    # AttributeError.
    if isinstance(estimate, InteriorScopeEstimate):
        rent_premium = _q2(
            estimate.roi_result.target_monthly_rent
            - estimate.roi_result.current_monthly_rent
        )
        per_unit_cost = _q2(estimate.per_unit_average_high)
    elif isinstance(estimate, AmenityScopeEstimate):
        # Amenity costs are per-installation (install_cost_high), not per-unit.
        # The renovation_program shape's renovation_cost_per_unit field is interior-
        # centric; map install_cost_high there with the understanding that downstream
        # consumers must treat amenity rows as property-level rather than per-unit.
        # rent_premium_monthly comes from the rent-premium gate result if computed.
        rent_premium = (
            _q2(estimate.expected_rent_premium_result.projected_premium_monthly)
            if estimate.expected_rent_premium_result is not None else None
        )
        per_unit_cost = _q2(estimate.install_cost_high)
    else:
        # Exterior, deferred — uses per_unit_high
        rent_premium = None
        per_unit_cost = _q2(estimate.per_unit_high)

    return {
        "renovation_cost_per_unit": per_unit_cost,
        "rent_premium_monthly": rent_premium,
        "downtime_days": schedule.downtime_days,
        "strategy": "renovation",
        "start_month": schedule.start_month,
        "monthly_pace": schedule.monthly_pace,
    }
