"""Core cost estimation engine for multifamily unit renovations."""

from pathlib import Path

import yaml

from .models import (
    FinishTier,
    LineItem,
    PropertyEstimateInput,
    PropertyClass,
    ScopeLevel,
    SizeCategory,
    UnitEstimate,
    PropertyEstimate,
    RiskFlag,
)
from .risk import get_risk_flags

_KB_PATH = Path(__file__).resolve().parent / "data" / "knowledge_base.yaml"


def _load_kb() -> dict:
    with open(_KB_PATH) as f:
        return yaml.safe_load(f)


def _get_size_category(sqft: float) -> SizeCategory:
    if sqft < 700:
        return SizeCategory.SMALL
    elif sqft <= 950:
        return SizeCategory.MEDIUM
    else:
        return SizeCategory.LARGE


def _scale_line_item(base_low: float, base_high: float, size_cat: SizeCategory) -> tuple[float, float]:
    """Scale a line item's range based on unit size category.

    Base ranges in the knowledge base are for a medium unit.
    Small units get ~85% of base, large units get ~115%.
    This produces the spread that maps line-item sums to the
    $12K-$14K (small) / $14K-$16K (medium) / $16K-$18K (large) totals.
    """
    factors = {
        SizeCategory.SMALL: 0.85,
        SizeCategory.MEDIUM: 1.0,
        SizeCategory.LARGE: 1.15,
    }
    f = factors[size_cat]
    return round(base_low * f), round(base_high * f)


def _apply_finish_tier(low: float, high: float, tier: FinishTier) -> tuple[float, float]:
    """Shift cost range based on finish tier.

    Basic tier uses the lower portion of the range.
    Upgraded tier uses the upper portion.
    """
    if tier == FinishTier.BASIC:
        return low, round(low + (high - low) * 0.6)
    else:  # upgraded
        return round(low + (high - low) * 0.4), high


def estimate_unit(
    unit_sqft: float,
    bedrooms: int,
    bathrooms: int,
    scope_level: ScopeLevel | str,
    finish_tier: FinishTier | str = FinishTier.BASIC,
    year_built: int | None = None,
    property_class: PropertyClass | str | None = None,
    market: str | None = None,
    unit_id: str = "",
) -> UnitEstimate:
    """Produce a per-unit cost estimate with line-item breakdown."""
    if unit_sqft <= 0:
        raise ValueError(f"unit_sqft must be positive, got {unit_sqft}")
    if bedrooms < 0:
        raise ValueError(f"bedrooms must be non-negative, got {bedrooms}")
    if bathrooms <= 0:
        raise ValueError(f"bathrooms must be positive, got {bathrooms}")

    scope_level = ScopeLevel(scope_level)
    finish_tier = FinishTier(finish_tier)
    if property_class is not None:
        property_class = PropertyClass(property_class)

    kb = _load_kb()
    scope_data = kb["scope_levels"][scope_level.value]
    size_cat = _get_size_category(unit_sqft)

    line_items: list[LineItem] = []

    if scope_level == ScopeLevel.LIGHT:
        # Light turn: flat line items, no size scaling or finish tier adjustment
        for cat_name, item_data in scope_data["line_items"].items():
            if cat_name == "contingency_pct":
                continue
            line_items.append(LineItem(
                category=cat_name,
                low=item_data["low"],
                high=item_data["high"],
                notes=item_data.get("notes", ""),
                material=item_data.get("material", ""),
            ))
        contingency_pct = scope_data["line_items"].get("contingency_pct", 10)

    else:
        # Standard value-add: scale by size, adjust by finish tier
        for cat_name, item_data in scope_data["line_items"].items():
            base_low = item_data["low"]
            base_high = item_data["high"]

            # Scale by unit size
            scaled_low, scaled_high = _scale_line_item(base_low, base_high, size_cat)

            # Apply finish tier (only for categories affected by finishes)
            finish_affected = {"flooring", "kitchen", "bathroom", "appliances", "fixtures_doors_trim"}
            if cat_name in finish_affected:
                scaled_low, scaled_high = _apply_finish_tier(scaled_low, scaled_high, finish_tier)

            # Multiply bathroom costs by bathroom count
            if item_data.get("per") == "bathroom":
                scaled_low *= bathrooms
                scaled_high *= bathrooms
                notes = f"{item_data.get('notes', '')} ({bathrooms} BA)"
            else:
                notes = item_data.get("notes", "")

            line_items.append(LineItem(
                category=cat_name,
                low=scaled_low,
                high=scaled_high,
                notes=notes,
                material=item_data.get("material", ""),
            ))

        # Contingency: use high end for conservative bias
        cont = scope_data["contingency_pct"]
        contingency_pct = cont["high"] if isinstance(cont, dict) else cont

    subtotal_low = sum(li.low for li in line_items)
    subtotal_high = sum(li.high for li in line_items)
    total_low = round(subtotal_low * (1 + contingency_pct / 100))
    total_high = round(subtotal_high * (1 + contingency_pct / 100))

    risk_flags = get_risk_flags(year_built)

    return UnitEstimate(
        unit_id=unit_id,
        unit_sqft=unit_sqft,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        scope_level=scope_level,
        finish_tier=finish_tier,
        size_category=size_cat,
        line_items=line_items,
        subtotal_low=subtotal_low,
        subtotal_high=subtotal_high,
        contingency_pct=contingency_pct,
        total_low=total_low,
        total_high=total_high,
        risk_flags=risk_flags,
        year_built=year_built,
        property_class=property_class,
        market=market,
    )


def _is_value_add_signal(year_built: int | None, property_class: PropertyClass | str | None) -> bool:
    """Return True iff the property profile matches the canonical value-add trigger.

    Per knowledge_base.yaml + Wave 2 fix-plan Q4 (user-confirmed):
    properties built in or before 1990 AND classified Class C are presumed to
    require a full value-add scope, NOT a light cosmetic turn. This prevents
    the federation from silently routing 1980s class-C value-add candidates
    through the degenerate light-scope branch (which produces a flat
    ~$3,850/unit regardless of size or finish).
    """
    if year_built is None or property_class is None:
        return False
    pc = property_class if isinstance(property_class, PropertyClass) else PropertyClass(property_class)
    return year_built <= 1990 and pc == PropertyClass.C


def estimate_property(property: PropertyEstimateInput) -> PropertyEstimate:
    """Property-level estimate rolling up unit estimates + exterior CapEx.

    Args:
        property: A PropertyEstimateInput model carrying all property-level
                  context and the unit mix to estimate.

    Returns:
        PropertyEstimate with per-unit breakdowns and exterior CapEx.

    Scope-level defaulting rule (Wave 2 Bug 2.2 fix):
      * If a unit's ``scope_level`` arrives unset (i.e. the to_unit_dicts entry
        lacks a 'scope_level' key — backwards-compat path), and the property
        matches the value-add signal (year_built <= 1990 + property_class C),
        the per-unit scope defaults to ``standard_value_add``. Without this
        guard, the cost-bridge silently produced a flat $3,850/unit on 1980s
        class-C deals, masking ROI failures.
      * If a unit's ``scope_level`` is explicitly ``light`` AND the property
        matches the value-add signal, the scope is RESPECTED (analyst override)
        but a sanity flag of the form
        ``"vintage_class_scope_anomaly: <unit_id> got light scope on
        <year>s class-C property"``
        is emitted onto the PropertyEstimate so downstream reviewers can audit
        the choice.

    Per-unit-average denominators (Wave 2 Bug 2.6 fix):
      * ``interior_per_unit_average_*`` uses ``units_needing_work`` (the cohort
        actually receiving interior work) as denominator.
      * ``exterior_per_unit_average_*`` uses ``total_units`` (exterior touches
        the whole property — roof, parking, landscape, signage).
      * The legacy ``per_unit_average_*`` divides TOTAL by ``total_units`` and
        is preserved for back-compat only.
    """
    kb = _load_kb()

    is_value_add_signal = _is_value_add_signal(property.year_built, property.property_class)
    sanity_flags: list[str] = []

    unit_estimates = []
    for u in property.to_unit_dicts():
        # Resolve scope_level. Two-stage policy per Wave 2 Q4:
        #   1. If the unit dict carries an explicit ``scope_level``, start from
        #      it; otherwise default to STANDARD_VALUE_ADD (matching legacy
        #      UnitSpec.scope_level field default and conservative-bias policy).
        #   2. Vintage-class override: when the value-add signal fires
        #      (year_built ≤ 1990 + property_class C), LIGHT scope is OVERRIDDEN
        #      to STANDARD_VALUE_ADD. The Stage 2 audit (Bug 2.2) found ALL 179
        #      the audited property's units came back as flat $3,850/unit because the
        #      cost-bridge-analyst was passing scope_level=light explicitly on
        #      a 1982 class-C property. Respecting that choice produced an
        #      indefensibly-low cost basis. Per project policy ("Conservative
        #      bias: underestimating renovation costs is far worse than
        #      overestimating", CLAUDE.md), the override is mandatory: vintage
        #      class-C deals MUST be priced at standard_value_add minimum.
        #   3. Override emits a stable sanity_flag so downstream consumers
        #      (memo composer, RedIQ workbook) see that the override happened.
        if "scope_level" in u and u["scope_level"] is not None:
            requested_scope = ScopeLevel(u["scope_level"])
        else:
            requested_scope = ScopeLevel.STANDARD_VALUE_ADD

        if requested_scope == ScopeLevel.LIGHT and is_value_add_signal:
            resolved_scope = ScopeLevel.STANDARD_VALUE_ADD
            unit_label = u.get("unit_id") or "<unknown>"
            decade = (property.year_built // 10) * 10
            sanity_flags.append(
                f"vintage_class_light_scope_overridden: {unit_label} requested "
                f"light scope on {decade}s class-C property "
                f"(year_built={property.year_built}); overridden to "
                f"standard_value_add per conservative-bias policy"
            )
        else:
            resolved_scope = requested_scope

        est = estimate_unit(
            unit_sqft=u["sqft"],
            bedrooms=u["bedrooms"],
            bathrooms=u["bathrooms"],
            scope_level=resolved_scope,
            finish_tier=u.get("finish_tier", FinishTier.BASIC),
            year_built=property.year_built,
            property_class=property.property_class,
            market=property.market,
            unit_id=u.get("unit_id", ""),
        )
        unit_estimates.append(est)

    # Exterior CapEx — applies to every unit on the property (not just the
    # renovation cohort). Denominator for the exterior per-unit average is
    # therefore ``total_units``.
    ext_data = kb["exterior_capex"]["items"]
    items_to_include = property.exterior_items or list(ext_data.keys())
    ext_low = sum(ext_data[item]["per_unit_low"] for item in items_to_include if item in ext_data) * property.total_units
    ext_high = sum(ext_data[item]["per_unit_high"] for item in items_to_include if item in ext_data) * property.total_units

    # Interior cost rolls up only across units that actually received interior
    # work (i.e. the unit_estimates list = units_needing_work). Denominator
    # for the interior per-unit average is therefore ``units_needing_work``.
    total_interior_low = sum(e.total_low for e in unit_estimates)
    total_interior_high = sum(e.total_high for e in unit_estimates)

    total_low = total_interior_low + ext_low
    total_high = total_interior_high + ext_high

    units_needing_work = len(unit_estimates)
    interior_per_unit_low = round(total_interior_low / units_needing_work) if units_needing_work > 0 else 0
    interior_per_unit_high = round(total_interior_high / units_needing_work) if units_needing_work > 0 else 0
    exterior_per_unit_low = round(ext_low / property.total_units) if property.total_units > 0 else 0
    exterior_per_unit_high = round(ext_high / property.total_units) if property.total_units > 0 else 0

    risk_flags = get_risk_flags(property.year_built)

    return PropertyEstimate(
        property_id=property.property_id,
        total_units=property.total_units,
        units_needing_work=units_needing_work,
        unit_estimates=unit_estimates,
        exterior_capex_low=ext_low,
        exterior_capex_high=ext_high,
        total_renovation_low=total_low,
        total_renovation_high=total_high,
        per_unit_average_low=round(total_low / property.total_units) if property.total_units > 0 else 0,
        per_unit_average_high=round(total_high / property.total_units) if property.total_units > 0 else 0,
        interior_per_unit_average_low=interior_per_unit_low,
        interior_per_unit_average_high=interior_per_unit_high,
        exterior_per_unit_average_low=exterior_per_unit_low,
        exterior_per_unit_average_high=exterior_per_unit_high,
        risk_flags=risk_flags,
        sanity_flags=sanity_flags,
    )
