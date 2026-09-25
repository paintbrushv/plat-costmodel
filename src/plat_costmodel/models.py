"""Pydantic data models for plat-costmodel."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ScopeLevel(str, Enum):
    LIGHT = "light"
    STANDARD_VALUE_ADD = "standard_value_add"


class SizeCategory(str, Enum):
    SMALL = "small"    # <700 sf
    MEDIUM = "medium"  # 700-950 sf
    LARGE = "large"    # 950+ sf


class FinishTier(str, Enum):
    BASIC = "basic"
    UPGRADED = "upgraded"


class PropertyClass(str, Enum):
    B = "B"
    C = "C"


class LineItem(BaseModel):
    """A single cost line item in an estimate."""
    category: str
    low: float
    high: float
    notes: str = ""
    material: str = ""


class RiskFlag(BaseModel):
    """An age/condition-based risk warning."""
    message: str
    flag_type: str = ""       # e.g. "lead_paint", "asbestos", "galvanized_pipe"
    severity: str = "warning"  # warning, critical
    triggered_by: str = ""    # e.g. "year_built in [0, 1978]"
    recommended_action: str = ""  # specific mitigation step with cost guidance


class UnitEstimate(BaseModel):
    """Per-unit renovation cost estimate with line-item breakdown."""
    unit_id: str = ""
    unit_sqft: float
    bedrooms: int
    bathrooms: int
    scope_level: ScopeLevel
    finish_tier: FinishTier
    size_category: SizeCategory

    line_items: list[LineItem]
    subtotal_low: float
    subtotal_high: float
    contingency_pct: float
    contingency_low: float = 0.0   # dollar amount of contingency on low estimate
    contingency_high: float = 0.0  # dollar amount of contingency on high estimate
    total_low: float
    total_high: float
    risk_flags: list[RiskFlag]

    # Property context
    year_built: Optional[int] = None
    property_class: Optional[PropertyClass] = None
    market: Optional[str] = None


class ROIPathItem(BaseModel):
    """A specific actionable step to clear the ROI threshold."""
    action_type: str  # "cut_cost" | "increase_rent"
    description: str
    current_value: float
    required_value: float
    delta: float  # absolute change needed (always positive)


class ROIResult(BaseModel):
    """ROI threshold check result."""
    total_cost_high: float
    current_monthly_rent: float
    target_monthly_rent: float
    monthly_rent_lift: float
    annual_rent_lift: float
    roi_pct: float
    threshold_pct: float = 15.0
    clears_threshold: bool
    note: str = ""

    # Path-to-pass fields (populated on failure)
    cost_reduction_needed: float | None = None   # reduce cost by this $ to pass at current target rent
    rent_increase_needed: float | None = None    # raise target rent by this $/mo to pass at current cost
    path_to_pass: list[str] = []                 # human-readable ordered suggestions
    line_item_suggestions: list[ROIPathItem] = []  # per-line-item cut candidates


class BidLineItem(BaseModel):
    """A line item from a contractor bid."""
    description: str
    amount: float


class ContractorBid(BaseModel):
    """A contractor's bid for evaluation."""
    contractor_name: str
    line_items: list[BidLineItem]
    total: float
    timeline_days: Optional[int] = None


class BidFlag(BaseModel):
    """A flag raised during bid evaluation."""
    flag_type: str  # "inflated", "vague", "timeline"
    severity: str  # "warning", "critical"
    message: str
    line_item: Optional[str] = None
    expected_range: Optional[str] = None
    bid_amount: Optional[float] = None


class BidEvaluation(BaseModel):
    """Result of evaluating a contractor bid."""
    contractor_name: str
    bid_total: float
    internal_estimate_low: float
    internal_estimate_high: float
    flags: list[BidFlag]
    overall_assessment: str  # "reasonable", "concerns", "reject"


class SOWLineItem(BaseModel):
    """A line item in a scope of work."""
    category: str
    description: str
    material_spec: str
    quantity_notes: str
    quality_standard: str


class ScopeOfWork(BaseModel):
    """Generated scope of work document."""
    property_address: str = ""
    unit_id: str = ""
    scope_level: ScopeLevel
    finish_tier: FinishTier
    line_items: list[SOWLineItem]
    general_conditions: str = ""
    notes: str = ""


class UnitSpec(BaseModel):
    """Specification for a unit type within a property.

    Represents one or more identical units. Use ``count`` > 1 to describe
    multiple units with the same configuration (e.g. "12 units of 2BR/1BA 850sf").
    """
    unit_id: str = ""
    sqft: float = Field(gt=0)
    bedrooms: int = Field(ge=0)
    bathrooms: int = Field(ge=1)
    scope_level: ScopeLevel = ScopeLevel.STANDARD_VALUE_ADD
    finish_tier: FinishTier = FinishTier.BASIC
    count: int = Field(default=1, ge=1, description="Number of units of this type")


class PropertyEstimateInput(BaseModel):
    """Estimator input shape — unit_mix + property context.

    Carries all property-level context needed by estimate_property() to
    produce a PropertyEstimate. This is NOT the persisted-entity model;
    for that, see plat_costmodel.schemas.Property.

    Replaces scattered year_built / property_class / market kwargs across
    estimate_property(), sampling, and risk modules. One object carries
    all property-level context needed by every tool in the pipeline.
    """
    property_id: str
    year_built: Optional[int] = None
    property_class: Optional[PropertyClass] = None
    market: Optional[str] = None
    total_units: int = Field(ge=0)
    unit_mix: list[UnitSpec] = Field(default_factory=list)
    building_type: str = ""  # "garden", "mid-rise", "high-rise", etc.
    exterior_items: Optional[list[str]] = None  # CapEx categories to include

    @property
    def units_in_mix(self) -> int:
        """Total units described by the unit_mix (sum of all spec counts)."""
        return sum(spec.count for spec in self.unit_mix)

    def to_unit_dicts(self) -> list[dict]:
        """Convert unit_mix to the list[dict] format used by estimate_property().

        Expands count > 1 specs into individual unit dicts with sequential IDs.
        """
        result: list[dict] = []
        idx = 0
        for spec in self.unit_mix:
            for i in range(spec.count):
                uid = spec.unit_id if spec.count == 1 and spec.unit_id else f"U{idx + 1:03d}"
                result.append({
                    "unit_id": uid,
                    "sqft": spec.sqft,
                    "bedrooms": spec.bedrooms,
                    "bathrooms": spec.bathrooms,
                    "scope_level": spec.scope_level.value,
                    "finish_tier": spec.finish_tier.value,
                })
                idx += 1
        return result


class PropertyEstimate(BaseModel):
    """Property-level estimate rolling up all units + exterior.

    Per-unit averages are intentionally split by interior/exterior because the
    two have different denominators (Bug 2.6 in stage_2_costmodel audit):

      * ``interior_per_unit_average_*`` divides interior cost by
        ``units_needing_work`` (the cohort actually receiving interior work).
      * ``exterior_per_unit_average_*`` divides exterior CapEx by
        ``total_units`` (exterior touches roof/parking/landscape — the whole
        property, including units NOT in the renovation program).

    The legacy ``per_unit_average_low/high`` fields are preserved for
    backwards-compat and divide TOTAL (interior + exterior) by ``total_units``,
    which mixes denominators and should be considered deprecated for any new
    consumer that wants to compare against per-unit benchmarks.

    ``sanity_flags`` carries soft warnings emitted by the estimator that should
    surface to downstream reviewers (e.g. cost-bridge-analyst output, memo
    composer). They never block the estimate; they tag suspicious combinations
    such as a 1980s class-C property running through the light-scope branch.
    """
    property_id: str
    total_units: int
    units_needing_work: int
    unit_estimates: list[UnitEstimate]
    exterior_capex_low: float
    exterior_capex_high: float
    total_renovation_low: float
    total_renovation_high: float
    per_unit_average_low: float
    per_unit_average_high: float
    interior_per_unit_average_low: float = 0.0
    interior_per_unit_average_high: float = 0.0
    exterior_per_unit_average_low: float = 0.0
    exterior_per_unit_average_high: float = 0.0
    risk_flags: list[RiskFlag]
    sanity_flags: list[str] = []
