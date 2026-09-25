"""Phase 1 sample selection logic for property inspection planning.

Produces a statistically defensible representative sample of units for
walk-through inspection before generating property-level renovation budgets.

Stratification dimensions
-------------------------
  FloorTier    — GROUND / MID / TOP (moisture/pest vs. baseline vs. roof risk)
  ConditionTier — RENT_READY / DATED / DEFERRED / DISTRESSED / UNKNOWN

Sampling rules
--------------
  Small property (≤ 20 units)  : 30 % minimum; at least 5 if available
  Medium property (21–100 units): 20 % minimum; at least 6 if available
  Large property (101+ units)  : 15 % minimum; at least 15 if available

  ALWAYS guarantee at least 1 unit per represented (unit_type × floor_tier)
  stratum — the proportional fill comes afterwards.

Inspection recording
--------------------
  InspectionRecord captures condition-tier, scope recommendation, and
  trade-by-trade observations.  The record serialises to JSON so it can be
  stored, reviewed, and forwarded to estimate_unit().

Design notes
------------
  - All models use Pydantic BaseModel (plat_costmodel layer — not the
    lab/plat/rehab dataclass layer).
  - PEP 604 X | Y union syntax throughout (Python ≥ 3.10 per pyproject.toml).
  - No hardcoded market adjustment factors; no internet required.
  - Conservative bias: when unsure which stratum a unit belongs to, it is
    treated as UNKNOWN and sampled MORE aggressively, not less.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from enum import Enum
from typing import Sequence

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class FloorTier(str, Enum):
    """
    Vertical risk stratum for a unit.

    GROUND (1st floor):
        Elevated moisture / pest / drainage risk.  Inspect sub-floor,
        baseboards, window wells, and sliding-door thresholds.

    TOP (highest occupied floor):
        Roof leak / HVAC condensate / water-heater-in-attic risk.
        Inspect ceiling at exterior walls, around skylights, HVAC closets.

    MID (all other floors):
        Baseline risk profile.  Standard inspection scope applies.

    UNKNOWN:
        Floor number was not supplied.  Treated like MID for sampling
        allocation, but a warning is raised in the SamplePlan.
    """

    GROUND = "ground"
    MID = "mid"
    TOP = "top"
    UNKNOWN = "unknown"


class ConditionTier(str, Enum):
    """
    Observed or Yardi-derived condition of the unit before renovation.

    Maps 1-to-1 to PropertyCondition in the lab/plat/rehab layer.
    Drives scope_recommendation and contingency_pct in InspectionRecord.

    UNKNOWN:
        No prior data.  Treated conservatively — sample more units from
        this tier and assume DATED for budget purposes until inspected.
    """

    RENT_READY = "rent_ready"       # Normal wear-and-tear only
    DATED = "dated"                 # Functional but 10-20 yrs behind market
    DEFERRED = "deferred"           # Significant deferred maintenance
    DISTRESSED = "distressed"       # Extensive damage / abandonment
    UNKNOWN = "unknown"             # No prior info — inspect before estimating


class TradeCondition(str, Enum):
    """Observed condition rating for a single trade."""

    GOOD = "good"          # No work needed or minor touch-up only
    FAIR = "fair"          # Will need attention in this renovation
    POOR = "poor"          # Needs full replacement / remediation
    FAILED = "failed"      # Non-functional; immediate risk to occupant
    NOT_ASSESSED = "not_assessed"


# ---------------------------------------------------------------------------
# Input model — unit roster
# ---------------------------------------------------------------------------


class UnitRosterEntry(BaseModel):
    """
    One unit in the property roster submitted for sample selection.

    All fields except unit_id are optional to support progressive enrichment:
    minimal input (unit_id only) works but generates more UNKNOWN strata
    and wider sample coverage to compensate.

    Sources: Yardi Voyager unit CSV, manual spreadsheet, or MCP call.
    """

    unit_id: str = Field(..., description="Unique unit identifier, e.g. '101A'")

    # Unit configuration
    unit_type: str = Field(
        "unknown",
        description=(
            "Bedroom/bath type: 'studio', '1br', '2br_1ba', '2br_2ba', "
            "'3br_plus', or 'unknown'."
        ),
    )
    sqft: float | None = Field(None, gt=0, description="Unit square footage")
    bedrooms: int | None = Field(None, ge=0)
    bathrooms: float | None = Field(None, gt=0)

    # Vertical position
    floor: int | None = Field(None, ge=1, description="Floor number (1 = ground)")
    floor_tier: FloorTier | None = Field(
        None,
        description=(
            "Pre-classified floor tier.  If None and floor is supplied, "
            "classify_floor_tier() will compute it."
        ),
    )

    # Known condition (from Yardi work-order history or prior inspection)
    condition_tier: ConditionTier = Field(
        ConditionTier.UNKNOWN,
        description="Known condition tier; defaults to UNKNOWN until inspected.",
    )

    # Occupancy and renovation history
    currently_occupied: bool = False
    last_renovation_year: int | None = Field(
        None,
        ge=1950,
        le=2030,
        description="Year of last documented major renovation.",
    )

    # Free-form notes (Yardi memo field, owner notes, etc.)
    notes: str = ""


# ---------------------------------------------------------------------------
# Sampling configuration
# ---------------------------------------------------------------------------


class SamplingConfig(BaseModel):
    """
    Configurable sampling parameters.

    Defaults reflect the operator's house practice — conservative
    coverage with predictable inspector time commitment.
    """

    # Minimum sample sizes by portfolio tier
    small_property_min_pct: float = Field(
        0.30, ge=0.0, le=1.0,
        description="Minimum sample fraction for properties ≤ small_threshold.",
    )
    medium_property_min_pct: float = Field(
        0.20, ge=0.0, le=1.0,
        description="Minimum sample fraction for medium properties.",
    )
    large_property_min_pct: float = Field(
        0.15, ge=0.0, le=1.0,
        description="Minimum sample fraction for large properties.",
    )

    # Property size thresholds (total units)
    small_threshold: int = Field(
        20,
        description="Properties at or below this unit count use small_property_min_pct.",
    )
    large_threshold: int = Field(
        100,
        description="Properties above this unit count use large_property_min_pct.",
    )

    # Absolute floor — never inspect fewer than this many units
    absolute_min_small: int = Field(
        5,
        description="Absolute minimum units to inspect for small properties.",
    )
    absolute_min_medium: int = Field(
        6,
        description="Absolute minimum units to inspect for medium properties.",
    )
    absolute_min_large: int = Field(
        15,
        description="Absolute minimum units to inspect for large properties.",
    )

    # Stratum guarantee — always inspect at least this many per stratum
    min_per_stratum: int = Field(
        1,
        ge=1,
        description=(
            "Guaranteed minimum selections per (unit_type × floor_tier) stratum. "
            "Strata with fewer total units than this are fully sampled."
        ),
    )

    # Conservative bias: UNKNOWN condition units are oversampled
    unknown_condition_oversample_factor: float = Field(
        1.5, ge=1.0,
        description=(
            "Units with UNKNOWN condition_tier count as this multiple when "
            "computing stratum quota.  Conservative — inspect more uncertain units."
        ),
    )

    # Reproducible random selection when units within a stratum are equivalent
    random_seed: int | None = Field(
        None,
        description=(
            "Seed for random selection within strata.  Set to an integer for "
            "reproducible plans (useful in tests and audit trails)."
        ),
    )


# ---------------------------------------------------------------------------
# Output models — sample plan
# ---------------------------------------------------------------------------


class StratumSummary(BaseModel):
    """Sampling outcome for a single (unit_type × floor_tier) stratum."""

    unit_type: str
    floor_tier: FloorTier
    condition_tier_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Count of units per ConditionTier in this stratum.",
    )
    total_units: int
    sampled_count: int
    sampled_ids: list[str]
    fully_sampled: bool = Field(
        False,
        description="True when sampled_count == total_units (entire stratum inspected).",
    )


class SamplePlan(BaseModel):
    """
    Complete Phase 1 inspection sample plan for a property.

    Produced by select_sample().  Contains all information needed to
    schedule inspections: who to visit, which strata they represent,
    and any data-quality warnings.
    """

    property_id: str
    total_units: int
    sample_size: int
    sample_pct: float = Field(description="Fraction of total units selected (0–1).")
    sampled_unit_ids: list[str]
    strata: list[StratumSummary]

    selection_rationale: str = Field(
        description=(
            "Plain-English explanation of the sampling rules applied — "
            "suitable for due-diligence documentation."
        )
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Data-quality warnings that may affect sample representativeness.",
    )

    # Config snapshot for auditability
    config_snapshot: dict = Field(
        default_factory=dict,
        description="Key sampling parameters used for this plan.",
    )


# ---------------------------------------------------------------------------
# Output models — inspection records
# ---------------------------------------------------------------------------


class InspectionRecord(BaseModel):
    """
    Per-unit inspection result captured during Phase 1 walk-through.

    The inspector fills this out on-site (or from photos) for each
    sampled unit.  Downstream, the condition_tier and trade observations
    flow into estimate_unit() via the scope_recommendation and any
    observed deficiency notes.

    Conservative defaults: all trade conditions default to NOT_ASSESSED
    rather than GOOD — forcing the inspector to actively affirm a clean
    unit rather than defaulting to optimism.
    """

    unit_id: str
    property_id: str

    # When and who
    inspected_date: str = Field(
        description="ISO-8601 date, e.g. '2026-03-23'.  Filled on inspection day.",
    )
    inspector_name: str = ""

    # --- Condition summary ---
    condition_tier: ConditionTier = Field(
        ...,
        description="Inspector's overall condition assessment for this unit.",
    )
    scope_recommendation: str = Field(
        ...,
        description="'light' or 'standard_value_add' — inspector's recommended scope.",
    )

    # --- Trade-by-trade condition ratings ---
    flooring: TradeCondition = TradeCondition.NOT_ASSESSED
    paint: TradeCondition = TradeCondition.NOT_ASSESSED
    kitchen: TradeCondition = TradeCondition.NOT_ASSESSED
    bathroom: TradeCondition = TradeCondition.NOT_ASSESSED
    hvac: TradeCondition = TradeCondition.NOT_ASSESSED
    plumbing: TradeCondition = TradeCondition.NOT_ASSESSED
    electrical: TradeCondition = TradeCondition.NOT_ASSESSED
    appliances: TradeCondition = TradeCondition.NOT_ASSESSED
    doors_hardware: TradeCondition = TradeCondition.NOT_ASSESSED
    windows_blinds: TradeCondition = TradeCondition.NOT_ASSESSED

    # --- Risk observations (boolean flags) ---
    moisture_intrusion_visible: bool = False
    mold_visible: bool = False
    pest_evidence: bool = False
    plumbing_active_leak: bool = False
    electrical_safety_concern: bool = False
    structural_concern: bool = False

    # --- Photos and documentation ---
    photos_taken: int = Field(default=0, ge=0)
    photo_ids: list[str] = Field(
        default_factory=list,
        description="File names or storage keys for photos taken.",
    )

    # --- Free-form notes ---
    notes: str = ""

    # --- Derived fields (computed or overridden by inspector) ---
    # cost_condition_multiplier: scalar applied to base estimate for this unit.
    # Conservative bias: DEFERRED → 1.15, DISTRESSED → 1.25, else 1.0.
    cost_condition_multiplier: float = Field(
        1.0,
        ge=0.5,
        le=2.0,
        description=(
            "Cost multiplier applied to the base estimate to reflect this unit's "
            "specific condition.  Conservative defaults by condition tier are applied "
            "if the inspector does not override."
        ),
    )

    @model_validator(mode="after")
    def _set_conservative_multiplier_default(self) -> "InspectionRecord":
        """
        Apply conservative default multiplier if the caller left it at 1.0
        and the condition tier warrants a premium.

        Conservative philosophy: if the inspector saw DEFERRED or DISTRESSED
        but did not explicitly set a multiplier, err on the high side.
        """
        defaults = {
            ConditionTier.RENT_READY: 1.00,
            ConditionTier.DATED: 1.00,
            ConditionTier.DEFERRED: 1.15,
            ConditionTier.DISTRESSED: 1.25,
            ConditionTier.UNKNOWN: 1.10,  # Assume something bad is hiding
        }
        if self.cost_condition_multiplier == 1.0:
            self.cost_condition_multiplier = defaults.get(self.condition_tier, 1.0)
        return self

    @property
    def risk_flag_count(self) -> int:
        """Number of boolean risk flags that were observed."""
        return sum([
            self.moisture_intrusion_visible,
            self.mold_visible,
            self.pest_evidence,
            self.plumbing_active_leak,
            self.electrical_safety_concern,
            self.structural_concern,
        ])

    @property
    def deficiency_notes(self) -> list[str]:
        """
        Machine-readable list of observed deficiencies for passing to
        estimate_unit() as observed_deficiencies or UnitProfile.observed_deficiencies.
        """
        deficiencies: list[str] = []

        # Boolean flags
        if self.moisture_intrusion_visible:
            deficiencies.append("moisture_intrusion")
        if self.mold_visible:
            deficiencies.append("mold_visible")
        if self.pest_evidence:
            deficiencies.append("pest_evidence")
        if self.plumbing_active_leak:
            deficiencies.append("plumbing_active_leak")
        if self.electrical_safety_concern:
            deficiencies.append("electrical_safety_concern")
        if self.structural_concern:
            deficiencies.append("structural_concern")

        # Trade conditions
        trade_map = {
            "flooring": self.flooring,
            "paint": self.paint,
            "kitchen": self.kitchen,
            "bathroom": self.bathroom,
            "hvac": self.hvac,
            "plumbing": self.plumbing,
            "electrical": self.electrical,
            "appliances": self.appliances,
        }
        for trade, condition in trade_map.items():
            if condition in (TradeCondition.POOR, TradeCondition.FAILED):
                deficiencies.append(f"{trade}_{condition.value}")

        return deficiencies


class InspectionSummary(BaseModel):
    """
    Property-level rollup after all Phase 1 inspections are recorded.

    Aggregates condition distribution, scope breakdown, and typical
    cost multipliers to inform the property-level budget estimate.
    """

    property_id: str
    total_inspected: int

    # Condition distribution across inspected units
    condition_distribution: dict[str, int] = Field(
        default_factory=dict,
        description="Count of units per ConditionTier among inspected units.",
    )

    # Scope recommendation distribution
    scope_distribution: dict[str, int] = Field(
        default_factory=dict,
        description="Count of 'light' vs 'standard_value_add' recommendations.",
    )

    # Cost multiplier stats
    avg_cost_multiplier: float
    max_cost_multiplier: float
    units_with_risk_flags: int

    # Which units had boolean risk flags
    flagged_unit_ids: list[str] = Field(default_factory=list)

    # Aggregate deficiency list (de-duplicated)
    observed_deficiency_types: list[str] = Field(
        default_factory=list,
        description="Unique deficiency types seen across all inspected units.",
    )

    # Any units that weren't inspected from the plan
    uninspected_unit_ids: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def classify_floor_tier(floor: int | None, total_floors: int | None) -> FloorTier:
    """
    Map a unit's floor number to its risk stratum.

    Args:
        floor: The unit's floor number (1 = ground).  None → UNKNOWN.
        total_floors: The maximum floor count in the building.  When None,
            any floor > 1 is treated as MID (conservative — avoids tagging
            top-floor units as MID and missing roof-risk inspection).

    Returns:
        FloorTier enum value.

    Conservative rule:
        When total_floors is unknown, floor 1 → GROUND, floor > 1 → MID.
        This means top-floor units may be under-identified as TOP when
        building height is unknown — a known limitation surfaced as a
        SamplePlan.warnings entry by select_sample().
    """
    if floor is None:
        return FloorTier.UNKNOWN

    if floor == 1:
        return FloorTier.GROUND

    if total_floors is not None and floor == total_floors:
        return FloorTier.TOP

    return FloorTier.MID


def compute_target_sample_size(total_units: int, config: SamplingConfig) -> int:
    """
    Calculate the target number of units to inspect.

    Applies the property-size-tier rules from SamplingConfig and enforces
    absolute minimums.  The result is capped at total_units (can never
    exceed the full population).

    Args:
        total_units: Total number of units in the property.
        config: SamplingConfig controlling thresholds and percentages.

    Returns:
        Target sample size as an integer (≥ 1, ≤ total_units).
    """
    if total_units <= 0:
        return 0

    if total_units <= config.small_threshold:
        pct = config.small_property_min_pct
        abs_min = config.absolute_min_small
    elif total_units <= config.large_threshold:
        pct = config.medium_property_min_pct
        abs_min = config.absolute_min_medium
    else:
        pct = config.large_property_min_pct
        abs_min = config.absolute_min_large

    pct_based = math.ceil(total_units * pct)
    target = max(pct_based, abs_min, 1)

    # Never exceed the full population
    return min(target, total_units)


def select_sample(
    roster: Sequence[UnitRosterEntry],
    property_id: str,
    config: SamplingConfig | None = None,
) -> SamplePlan:
    """
    Select a representative sample of units for Phase 1 inspection.

    Algorithm (in order):
      1. Resolve floor tiers for all units where possible.
      2. Group units into strata: (unit_type, floor_tier).
      3. Guarantee min_per_stratum selections from every represented stratum.
      4. Fill the remaining quota proportionally from the largest strata,
         preferring strata with UNKNOWN condition (conservative bias).
      5. Return SamplePlan with unit IDs, stratum breakdown, and warnings.

    Args:
        roster: All units in the property roster.
        property_id: Property identifier for plan labelling.
        config: Sampling configuration.  Defaults to SamplingConfig() defaults.

    Returns:
        SamplePlan ready to hand to the inspector team.

    Raises:
        ValueError: If roster is empty.
    """
    if not roster:
        raise ValueError("roster must contain at least one unit")

    cfg = config or SamplingConfig()
    rng = random.Random(cfg.random_seed)

    units = list(roster)
    total = len(units)
    target = compute_target_sample_size(total, cfg)

    # -----------------------------------------------------------------------
    # Step 1: Resolve floor tiers
    # -----------------------------------------------------------------------
    known_floors = [u.floor for u in units if u.floor is not None]
    total_floors: int | None = max(known_floors) if known_floors else None

    warnings: list[str] = []
    if total_floors is None:
        warnings.append(
            "No floor numbers supplied — all units classified as UNKNOWN floor tier. "
            "Ground-floor (moisture/pest) and top-floor (roof/HVAC) strata cannot "
            "be guaranteed.  Supply floor numbers for stratified coverage."
        )

    resolved: list[tuple[UnitRosterEntry, FloorTier]] = []
    for u in units:
        if u.floor_tier is not None:
            ft = u.floor_tier
        else:
            ft = classify_floor_tier(u.floor, total_floors)
        resolved.append((u, ft))

    # -----------------------------------------------------------------------
    # Step 2: Group into strata
    # -----------------------------------------------------------------------
    # strata_map: {(unit_type, FloorTier): [UnitRosterEntry]}
    strata_map: dict[tuple[str, FloorTier], list[UnitRosterEntry]] = defaultdict(list)
    for u, ft in resolved:
        strata_map[(u.unit_type, ft)].append(u)

    # -----------------------------------------------------------------------
    # Step 3: Guaranteed minimum per stratum
    # -----------------------------------------------------------------------
    selected_ids: set[str] = set()
    stratum_selections: dict[tuple[str, FloorTier], list[str]] = defaultdict(list)

    for key, stratum_units in sorted(strata_map.items()):  # deterministic order
        take = min(cfg.min_per_stratum, len(stratum_units))
        # Prefer UNKNOWN condition units first (conservative bias)
        ordered = _sort_by_condition_priority(stratum_units, rng)
        for u in ordered[:take]:
            if u.unit_id not in selected_ids:
                selected_ids.add(u.unit_id)
                stratum_selections[key].append(u.unit_id)

    # -----------------------------------------------------------------------
    # Step 4: Proportional fill to reach target
    # -----------------------------------------------------------------------
    if len(selected_ids) < target:
        remaining_quota = target - len(selected_ids)
        # Build pool of unselected units, sorted by desirability
        pool = _build_fill_pool(resolved, selected_ids, cfg, rng)
        for u in pool:
            if remaining_quota <= 0:
                break
            if u.unit_id not in selected_ids:
                selected_ids.add(u.unit_id)
                ft_key = _floor_tier_for_unit(u, resolved)
                stratum_selections[(u.unit_type, ft_key)].append(u.unit_id)
                remaining_quota -= 1

    # -----------------------------------------------------------------------
    # Step 5: Build StratumSummary objects
    # -----------------------------------------------------------------------
    stratum_summaries: list[StratumSummary] = []
    for (ut, ft), stratum_units in sorted(strata_map.items()):
        cond_counts: dict[str, int] = defaultdict(int)
        for u in stratum_units:
            cond_counts[u.condition_tier.value] += 1

        s_ids = stratum_selections.get((ut, ft), [])
        stratum_summaries.append(
            StratumSummary(
                unit_type=ut,
                floor_tier=ft,
                condition_tier_counts=dict(cond_counts),
                total_units=len(stratum_units),
                sampled_count=len(s_ids),
                sampled_ids=s_ids,
                fully_sampled=len(s_ids) == len(stratum_units),
            )
        )

    # -----------------------------------------------------------------------
    # Step 6: Warnings
    # -----------------------------------------------------------------------
    n_unknown_type = sum(1 for u in units if u.unit_type == "unknown")
    if n_unknown_type > 0:
        warnings.append(
            f"{n_unknown_type} unit(s) have unknown unit_type — they are grouped "
            "in the 'unknown' unit-type stratum.  Supply bedroom/bath data from "
            "Yardi for accurate scope differentiation."
        )

    n_occupied = sum(1 for u in units if u.currently_occupied)
    if n_occupied > 0:
        n_occupied_sampled = sum(
            1 for uid in selected_ids
            for u in units
            if u.unit_id == uid and u.currently_occupied
        )
        if n_occupied_sampled > 0:
            warnings.append(
                f"{n_occupied_sampled} sampled unit(s) are currently occupied. "
                "Coordinate 24-hour notice with property management before inspection."
            )

    # -----------------------------------------------------------------------
    # Step 7: Rationale text
    # -----------------------------------------------------------------------
    actual_pct = len(selected_ids) / total if total > 0 else 0.0

    if total <= cfg.small_threshold:
        tier_label = f"small (≤ {cfg.small_threshold} units)"
        pct_label = f"{cfg.small_property_min_pct:.0%}"
    elif total <= cfg.large_threshold:
        tier_label = f"medium ({cfg.small_threshold + 1}–{cfg.large_threshold} units)"
        pct_label = f"{cfg.medium_property_min_pct:.0%}"
    else:
        tier_label = f"large (> {cfg.large_threshold} units)"
        pct_label = f"{cfg.large_property_min_pct:.0%}"

    rationale = (
        f"Property classified as {tier_label} ({total} total units). "
        f"Minimum sample rate: {pct_label}. "
        f"Stratified across {len(strata_map)} stratum/strata "
        f"({len(set(u.unit_type for u in units))} unit type(s) × "
        f"{len(set(ft for _, ft in resolved))} floor tier(s)). "
        f"Guaranteed ≥ {cfg.min_per_stratum} unit(s) per stratum. "
        f"Selected {len(selected_ids)} of {total} units ({actual_pct:.0%}) for inspection."
    )

    config_snapshot = {
        "small_property_min_pct": cfg.small_property_min_pct,
        "medium_property_min_pct": cfg.medium_property_min_pct,
        "large_property_min_pct": cfg.large_property_min_pct,
        "small_threshold": cfg.small_threshold,
        "large_threshold": cfg.large_threshold,
        "min_per_stratum": cfg.min_per_stratum,
        "random_seed": cfg.random_seed,
    }

    return SamplePlan(
        property_id=property_id,
        total_units=total,
        sample_size=len(selected_ids),
        sample_pct=round(actual_pct, 4),
        sampled_unit_ids=sorted(selected_ids),
        strata=stratum_summaries,
        selection_rationale=rationale,
        warnings=warnings,
        config_snapshot=config_snapshot,
    )


def record_inspection(
    unit_id: str,
    property_id: str,
    inspected_date: str,
    condition_tier: ConditionTier | str,
    scope_recommendation: str,
    *,
    inspector_name: str = "",
    flooring: TradeCondition | str = TradeCondition.NOT_ASSESSED,
    paint: TradeCondition | str = TradeCondition.NOT_ASSESSED,
    kitchen: TradeCondition | str = TradeCondition.NOT_ASSESSED,
    bathroom: TradeCondition | str = TradeCondition.NOT_ASSESSED,
    hvac: TradeCondition | str = TradeCondition.NOT_ASSESSED,
    plumbing: TradeCondition | str = TradeCondition.NOT_ASSESSED,
    electrical: TradeCondition | str = TradeCondition.NOT_ASSESSED,
    appliances: TradeCondition | str = TradeCondition.NOT_ASSESSED,
    doors_hardware: TradeCondition | str = TradeCondition.NOT_ASSESSED,
    windows_blinds: TradeCondition | str = TradeCondition.NOT_ASSESSED,
    moisture_intrusion_visible: bool = False,
    mold_visible: bool = False,
    pest_evidence: bool = False,
    plumbing_active_leak: bool = False,
    electrical_safety_concern: bool = False,
    structural_concern: bool = False,
    photos_taken: int = 0,
    photo_ids: list[str] | None = None,
    notes: str = "",
    cost_condition_multiplier: float = 1.0,
) -> InspectionRecord:
    """
    Factory function to create an InspectionRecord with validated inputs.

    Accepts both enum values and plain strings for condition/trade fields
    to allow flexible input from CLI, JSON, or MCP tool calls.

    Args:
        unit_id: Unit identifier matching UnitRosterEntry.unit_id.
        property_id: Property identifier.
        inspected_date: ISO-8601 date string (YYYY-MM-DD).
        condition_tier: Overall condition — ConditionTier enum or string value.
        scope_recommendation: 'light' or 'standard_value_add'.
        inspector_name: Inspector name for record keeping.
        flooring … windows_blinds: Trade-level condition ratings.
        moisture_intrusion_visible … structural_concern: Boolean risk flags.
        photos_taken: Number of photos captured.
        photo_ids: List of photo file names or storage keys.
        notes: Inspector free-text notes.
        cost_condition_multiplier: Override for the conservative default.

    Returns:
        Validated InspectionRecord.

    Raises:
        ValueError: If scope_recommendation is not 'light' or 'standard_value_add'.
    """
    valid_scopes = {"light", "standard_value_add"}
    if scope_recommendation not in valid_scopes:
        raise ValueError(
            f"scope_recommendation must be one of {valid_scopes}, "
            f"got '{scope_recommendation}'"
        )

    return InspectionRecord(
        unit_id=unit_id,
        property_id=property_id,
        inspected_date=inspected_date,
        inspector_name=inspector_name,
        condition_tier=ConditionTier(condition_tier),
        scope_recommendation=scope_recommendation,
        flooring=TradeCondition(flooring),
        paint=TradeCondition(paint),
        kitchen=TradeCondition(kitchen),
        bathroom=TradeCondition(bathroom),
        hvac=TradeCondition(hvac),
        plumbing=TradeCondition(plumbing),
        electrical=TradeCondition(electrical),
        appliances=TradeCondition(appliances),
        doors_hardware=TradeCondition(doors_hardware),
        windows_blinds=TradeCondition(windows_blinds),
        moisture_intrusion_visible=moisture_intrusion_visible,
        mold_visible=mold_visible,
        pest_evidence=pest_evidence,
        plumbing_active_leak=plumbing_active_leak,
        electrical_safety_concern=electrical_safety_concern,
        structural_concern=structural_concern,
        photos_taken=photos_taken,
        photo_ids=photo_ids or [],
        notes=notes,
        cost_condition_multiplier=cost_condition_multiplier,
    )


def summarize_inspections(
    records: list[InspectionRecord],
    sample_plan: SamplePlan | None = None,
) -> InspectionSummary:
    """
    Aggregate completed InspectionRecords into a property-level summary.

    This summary is the bridge between Phase 1 (inspection) and Phase 2
    (property-level budget estimate).  It surfaces:
      - Condition distribution across inspected units
      - Scope recommendation breakdown (light vs. full value-add)
      - Average and maximum cost multipliers (conservative bias preserved)
      - Any units with boolean risk flags
      - Uninspected units (present in plan but not yet inspected)

    Args:
        records: List of InspectionRecord objects from completed inspections.
        sample_plan: The SamplePlan that produced the inspection list.  When
            supplied, uninspected_unit_ids is populated from the plan minus
            the completed records.

    Returns:
        InspectionSummary ready for the property-level estimator.
    """
    if not records:
        property_id = sample_plan.property_id if sample_plan else ""
        return InspectionSummary(
            property_id=property_id,
            total_inspected=0,
            avg_cost_multiplier=1.0,
            max_cost_multiplier=1.0,
            units_with_risk_flags=0,
        )

    property_id = records[0].property_id

    # Condition distribution
    cond_dist: dict[str, int] = defaultdict(int)
    scope_dist: dict[str, int] = defaultdict(int)
    multipliers: list[float] = []
    flagged: list[str] = []
    all_deficiencies: set[str] = set()

    for rec in records:
        cond_dist[rec.condition_tier.value] += 1
        scope_dist[rec.scope_recommendation] += 1
        multipliers.append(rec.cost_condition_multiplier)
        if rec.risk_flag_count > 0:
            flagged.append(rec.unit_id)
        all_deficiencies.update(rec.deficiency_notes)

    avg_mult = round(sum(multipliers) / len(multipliers), 4)
    max_mult = max(multipliers)

    # Uninspected units
    uninspected: list[str] = []
    if sample_plan is not None:
        inspected_ids = {r.unit_id for r in records}
        uninspected = [
            uid for uid in sample_plan.sampled_unit_ids
            if uid not in inspected_ids
        ]

    return InspectionSummary(
        property_id=property_id,
        total_inspected=len(records),
        condition_distribution=dict(cond_dist),
        scope_distribution=dict(scope_dist),
        avg_cost_multiplier=avg_mult,
        max_cost_multiplier=max_mult,
        units_with_risk_flags=len(flagged),
        flagged_unit_ids=sorted(flagged),
        observed_deficiency_types=sorted(all_deficiencies),
        uninspected_unit_ids=sorted(uninspected),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sort_by_condition_priority(
    units: list[UnitRosterEntry], rng: random.Random
) -> list[UnitRosterEntry]:
    """
    Return units ordered so UNKNOWN and DISTRESSED conditions come first.

    Conservative bias: when choosing which unit to guarantee-sample from a
    stratum, prefer units where the condition is most uncertain or worst.
    Units within the same priority bucket are shuffled to avoid systematic
    selection of unit IDs with similar patterns.
    """
    priority = {
        ConditionTier.UNKNOWN: 0,
        ConditionTier.DISTRESSED: 1,
        ConditionTier.DEFERRED: 2,
        ConditionTier.DATED: 3,
        ConditionTier.RENT_READY: 4,
    }
    # Shuffle first for randomness within same priority
    shuffled = list(units)
    rng.shuffle(shuffled)
    return sorted(shuffled, key=lambda u: priority.get(u.condition_tier, 0))


def _build_fill_pool(
    resolved: list[tuple[UnitRosterEntry, FloorTier]],
    already_selected: set[str],
    cfg: SamplingConfig,
    rng: random.Random,
) -> list[UnitRosterEntry]:
    """
    Build the fill pool for proportional fill in Step 4 of select_sample().

    Units with UNKNOWN condition are weighted higher via the oversample
    factor — they appear multiple times in an effective priority queue.
    """
    pool: list[UnitRosterEntry] = []
    for u, _ in resolved:
        if u.unit_id in already_selected:
            continue
        # UNKNOWN condition units appear oversample_factor times
        weight = (
            int(cfg.unknown_condition_oversample_factor)
            if u.condition_tier == ConditionTier.UNKNOWN
            else 1
        )
        pool.extend([u] * weight)

    # Shuffle for diversity; units that appeared multiple times now have
    # proportionally more chance of being selected.
    rng.shuffle(pool)
    # Deduplicate while preserving shuffled order
    seen: set[str] = set()
    deduped: list[UnitRosterEntry] = []
    for u in pool:
        if u.unit_id not in seen:
            seen.add(u.unit_id)
            deduped.append(u)
    return deduped


def _floor_tier_for_unit(
    unit: UnitRosterEntry,
    resolved: list[tuple[UnitRosterEntry, FloorTier]],
) -> FloorTier:
    """Return the already-resolved FloorTier for a given unit."""
    for u, ft in resolved:
        if u.unit_id == unit.unit_id:
            return ft
    return FloorTier.UNKNOWN
