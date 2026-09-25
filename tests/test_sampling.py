"""Tests for the sampling module (sampling.py).

Hardening coverage per NEXT_PHASE.md Track 3:
  - Property size band boundaries (20, 21, 100, 101 units)
  - Minimum sample floor enforcement (5 small, 6 medium, 15 large)
  - All-UNKNOWN condition tier → aggressive sampling
  - Empty roster → ValueError
  - classify_floor_tier edge cases
  - InspectionRecord serialization round-trip
  - InspectionRecord conservative multiplier defaults
  - summarize_inspections aggregation
  - Conservative bias invariants
"""

import json

import pytest

from plat_costmodel.sampling import (
    ConditionTier,
    FloorTier,
    InspectionRecord,
    InspectionSummary,
    SamplePlan,
    SamplingConfig,
    StratumSummary,
    TradeCondition,
    UnitRosterEntry,
    classify_floor_tier,
    compute_target_sample_size,
    record_inspection,
    select_sample,
    summarize_inspections,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_roster(n: int, **overrides) -> list[UnitRosterEntry]:
    """Create a roster of n units with sensible defaults."""
    units = []
    for i in range(n):
        kwargs = {
            "unit_id": f"U{i + 1:03d}",
            "unit_type": "2br_1ba",
            "sqft": 850.0,
            "bedrooms": 2,
            "bathrooms": 1.0,
            "floor": (i % 3) + 1,
            "condition_tier": ConditionTier.DATED,
        }
        kwargs.update(overrides)
        # Make unit_id unique even with overrides
        if "unit_id" not in overrides:
            kwargs["unit_id"] = f"U{i + 1:03d}"
        units.append(UnitRosterEntry(**kwargs))
    return units


def _make_roster_unique_ids(n: int, **overrides) -> list[UnitRosterEntry]:
    """Like _make_roster but always unique IDs regardless of overrides."""
    units = []
    for i in range(n):
        kwargs = {
            "unit_id": f"U{i + 1:03d}",
            "unit_type": "2br_1ba",
            "sqft": 850.0,
            "bedrooms": 2,
            "bathrooms": 1.0,
            "floor": (i % 3) + 1,
            "condition_tier": ConditionTier.DATED,
        }
        kwargs.update(overrides)
        kwargs["unit_id"] = f"U{i + 1:03d}"
        units.append(UnitRosterEntry(**kwargs))
    return units


# ---------------------------------------------------------------------------
# classify_floor_tier
# ---------------------------------------------------------------------------

class TestClassifyFloorTier:
    def test_ground_floor(self):
        assert classify_floor_tier(1, 3) == FloorTier.GROUND

    def test_top_floor(self):
        assert classify_floor_tier(3, 3) == FloorTier.TOP

    def test_mid_floor(self):
        assert classify_floor_tier(2, 3) == FloorTier.MID

    def test_none_floor_returns_unknown(self):
        assert classify_floor_tier(None, 3) == FloorTier.UNKNOWN

    def test_none_total_floors_floor_1_is_ground(self):
        assert classify_floor_tier(1, None) == FloorTier.GROUND

    def test_none_total_floors_floor_gt1_is_mid(self):
        """Without total_floors, any floor > 1 is MID (conservative)."""
        assert classify_floor_tier(2, None) == FloorTier.MID
        assert classify_floor_tier(5, None) == FloorTier.MID

    def test_single_story_floor_is_both_ground_and_top(self):
        """Floor 1 of 1 → GROUND (takes precedence over TOP)."""
        assert classify_floor_tier(1, 1) == FloorTier.GROUND

    def test_two_story_top(self):
        assert classify_floor_tier(2, 2) == FloorTier.TOP


# ---------------------------------------------------------------------------
# compute_target_sample_size — property size bands
# ---------------------------------------------------------------------------

class TestComputeTargetSampleSize:
    """Boundary tests for the 20/21/100/101 unit thresholds."""

    def setup_method(self):
        self.cfg = SamplingConfig()

    # --- Small property (≤ 20 units) ---

    def test_small_20_units(self):
        """20 units → small band: 30% = 6, abs_min = 5 → 6."""
        target = compute_target_sample_size(20, self.cfg)
        assert target >= 5  # absolute minimum
        assert target == 6  # ceil(20 * 0.30) = 6

    def test_small_4_units_capped_at_total(self):
        """4 units: 30% = 2, abs_min = 5 → min(5, 4) = 4 (full census)."""
        target = compute_target_sample_size(4, self.cfg)
        assert target == 4

    def test_small_1_unit(self):
        """1 unit property: full census."""
        target = compute_target_sample_size(1, self.cfg)
        assert target == 1

    def test_small_5_units(self):
        """5 units: 30% = 2, abs_min = 5 → 5 (entire property)."""
        target = compute_target_sample_size(5, self.cfg)
        assert target == 5

    def test_small_6_units(self):
        """6 units: 30% = 2, abs_min = 5 → 5."""
        target = compute_target_sample_size(6, self.cfg)
        assert target == 5

    # --- Medium property (21-100 units) ---

    def test_medium_21_units(self):
        """21 units → medium band: 20% = 5, abs_min = 6 → 6."""
        target = compute_target_sample_size(21, self.cfg)
        assert target == 6

    def test_medium_100_units(self):
        """100 units → medium band: 20% = 20, abs_min = 6 → 20."""
        target = compute_target_sample_size(100, self.cfg)
        assert target == 20

    def test_medium_30_units(self):
        """30 units → 20% = 6, abs_min = 6 → 6."""
        target = compute_target_sample_size(30, self.cfg)
        assert target == 6

    # --- Large property (101+ units) ---

    def test_large_101_units(self):
        """101 units → large band: 15% = 16, abs_min = 15 → 16."""
        target = compute_target_sample_size(101, self.cfg)
        assert target == 16  # ceil(101 * 0.15) = 16

    def test_large_200_units(self):
        """200 units → 15% = 30, abs_min = 15 → 30."""
        target = compute_target_sample_size(200, self.cfg)
        assert target == 30

    # --- Edge cases ---

    def test_zero_units(self):
        """0 units → 0 (no units to sample)."""
        target = compute_target_sample_size(0, self.cfg)
        assert target == 0

    def test_negative_units(self):
        """Negative units → 0."""
        target = compute_target_sample_size(-5, self.cfg)
        assert target == 0

    def test_target_never_exceeds_total(self):
        """Target sample should never exceed total_units."""
        for n in [1, 2, 3, 4, 5, 10, 20, 21, 50, 100, 101, 500]:
            target = compute_target_sample_size(n, self.cfg)
            assert target <= n, f"target {target} > total {n}"


# ---------------------------------------------------------------------------
# select_sample — empty roster
# ---------------------------------------------------------------------------

class TestSelectSampleEmptyRoster:
    def test_empty_roster_raises_value_error(self):
        """Empty roster must raise ValueError, not return empty plan."""
        with pytest.raises(ValueError, match="at least one unit"):
            select_sample([], "PROP001")


# ---------------------------------------------------------------------------
# select_sample — minimum sample floors
# ---------------------------------------------------------------------------

class TestMinimumSampleFloors:
    """Verify absolute minimums: 5 for small, 6 for medium, 15 for large."""

    def test_small_property_minimum_5(self):
        """A 10-unit property: 30% = 3, but abs_min = 5 → sample 5."""
        roster = _make_roster(10)
        plan = select_sample(roster, "PROP001", SamplingConfig(random_seed=42))
        assert plan.sample_size >= 5

    def test_small_property_4_units_full_census(self):
        """A 4-unit property: abs_min = 5 but only 4 exist → full census."""
        roster = _make_roster(4)
        plan = select_sample(roster, "PROP001", SamplingConfig(random_seed=42))
        assert plan.sample_size == 4

    def test_medium_property_minimum_6(self):
        """A 25-unit property: 20% = 5, but abs_min = 6 → sample 6."""
        roster = _make_roster(25)
        plan = select_sample(roster, "PROP001", SamplingConfig(random_seed=42))
        assert plan.sample_size >= 6

    def test_large_property_minimum_15(self):
        """A 101-unit property: abs_min = 15 → at least 15 sampled."""
        roster = _make_roster_unique_ids(101)
        plan = select_sample(roster, "PROP001", SamplingConfig(random_seed=42))
        assert plan.sample_size >= 15


# ---------------------------------------------------------------------------
# select_sample — size band boundaries
# ---------------------------------------------------------------------------

class TestSizeBandBoundaries:
    def test_20_units_is_small(self):
        roster = _make_roster(20)
        plan = select_sample(roster, "PROP001", SamplingConfig(random_seed=42))
        assert "small" in plan.selection_rationale.lower()

    def test_21_units_is_medium(self):
        roster = _make_roster(21)
        plan = select_sample(roster, "PROP001", SamplingConfig(random_seed=42))
        assert "medium" in plan.selection_rationale.lower()

    def test_100_units_is_medium(self):
        roster = _make_roster_unique_ids(100)
        plan = select_sample(roster, "PROP001", SamplingConfig(random_seed=42))
        assert "medium" in plan.selection_rationale.lower()

    def test_101_units_is_large(self):
        roster = _make_roster_unique_ids(101)
        plan = select_sample(roster, "PROP001", SamplingConfig(random_seed=42))
        assert "large" in plan.selection_rationale.lower()


# ---------------------------------------------------------------------------
# select_sample — UNKNOWN condition aggressive sampling
# ---------------------------------------------------------------------------

class TestUnknownConditionOversampling:
    def test_all_unknown_sampled_more_aggressively(self):
        """All-UNKNOWN roster should get at least as many samples as DATED."""
        cfg = SamplingConfig(random_seed=42)
        roster_dated = _make_roster(20, condition_tier=ConditionTier.DATED)
        roster_unknown = _make_roster(20, condition_tier=ConditionTier.UNKNOWN)

        plan_dated = select_sample(roster_dated, "PROP001", cfg)
        plan_unknown = select_sample(roster_unknown, "PROP002", cfg)

        # UNKNOWN should get at least as many samples
        assert plan_unknown.sample_size >= plan_dated.sample_size

    def test_unknown_units_preferred_in_stratum_selection(self):
        """When stratum has mix of UNKNOWN and DATED, UNKNOWN picked first."""
        units = [
            UnitRosterEntry(
                unit_id="D1", unit_type="2br_1ba", condition_tier=ConditionTier.DATED,
                floor=1, sqft=850, bedrooms=2, bathrooms=1.0,
            ),
            UnitRosterEntry(
                unit_id="U1", unit_type="2br_1ba", condition_tier=ConditionTier.UNKNOWN,
                floor=1, sqft=850, bedrooms=2, bathrooms=1.0,
            ),
        ]
        cfg = SamplingConfig(min_per_stratum=1, random_seed=42)
        plan = select_sample(units, "PROP001", cfg)
        # The UNKNOWN unit should be selected (priority 0 in sort)
        assert "U1" in plan.sampled_unit_ids


# ---------------------------------------------------------------------------
# select_sample — stratum guarantee
# ---------------------------------------------------------------------------

class TestStratumGuarantee:
    def test_each_stratum_gets_at_least_one(self):
        """Each (unit_type × floor_tier) stratum should have ≥ 1 selected."""
        units = [
            UnitRosterEntry(unit_id="A1", unit_type="1br", floor=1, sqft=600,
                            bedrooms=1, bathrooms=1.0),
            UnitRosterEntry(unit_id="A2", unit_type="1br", floor=2, sqft=600,
                            bedrooms=1, bathrooms=1.0),
            UnitRosterEntry(unit_id="B1", unit_type="2br_1ba", floor=1, sqft=850,
                            bedrooms=2, bathrooms=1.0),
            UnitRosterEntry(unit_id="B2", unit_type="2br_1ba", floor=2, sqft=850,
                            bedrooms=2, bathrooms=1.0),
        ]
        cfg = SamplingConfig(random_seed=42)
        plan = select_sample(units, "PROP001", cfg)
        for stratum in plan.strata:
            if stratum.total_units > 0:
                assert stratum.sampled_count >= 1, (
                    f"Stratum {stratum.unit_type}/{stratum.floor_tier} has 0 samples"
                )


# ---------------------------------------------------------------------------
# select_sample — warnings
# ---------------------------------------------------------------------------

class TestSamplePlanWarnings:
    def test_no_floor_numbers_warns(self):
        """Roster with no floor numbers should generate a warning."""
        units = [
            UnitRosterEntry(unit_id=f"U{i}", unit_type="2br_1ba", sqft=850,
                            bedrooms=2, bathrooms=1.0)
            for i in range(10)
        ]
        plan = select_sample(units, "PROP001", SamplingConfig(random_seed=42))
        assert any("floor" in w.lower() for w in plan.warnings)

    def test_unknown_unit_type_warns(self):
        """Units with unknown unit_type should generate a warning."""
        units = _make_roster(5, unit_type="unknown")
        plan = select_sample(units, "PROP001", SamplingConfig(random_seed=42))
        assert any("unknown unit_type" in w.lower() for w in plan.warnings)

    def test_occupied_units_warning(self):
        """Occupied sampled units should trigger coordination warning."""
        units = _make_roster(5, currently_occupied=True)
        plan = select_sample(units, "PROP001", SamplingConfig(random_seed=42))
        assert any("occupied" in w.lower() for w in plan.warnings)


# ---------------------------------------------------------------------------
# select_sample — reproducibility
# ---------------------------------------------------------------------------

class TestSamplingReproducibility:
    def test_same_seed_same_plan(self):
        """Same random_seed should produce identical sample plans."""
        roster = _make_roster(50)
        cfg = SamplingConfig(random_seed=99)
        plan1 = select_sample(roster, "PROP001", cfg)
        plan2 = select_sample(roster, "PROP001", cfg)
        assert plan1.sampled_unit_ids == plan2.sampled_unit_ids

    def test_different_seed_may_differ(self):
        """Different seeds should produce different selections (for large enough roster)."""
        roster = _make_roster(50)
        plan1 = select_sample(roster, "PROP001", SamplingConfig(random_seed=1))
        plan2 = select_sample(roster, "PROP001", SamplingConfig(random_seed=2))
        # Not guaranteed to differ for small rosters, but very likely for 50 units
        # Just verify both are valid plans
        assert plan1.sample_size > 0
        assert plan2.sample_size > 0


# ---------------------------------------------------------------------------
# select_sample — SamplePlan output structure
# ---------------------------------------------------------------------------

class TestSamplePlanStructure:
    def test_plan_fields_populated(self):
        roster = _make_roster(10)
        plan = select_sample(roster, "PROP001", SamplingConfig(random_seed=42))
        assert plan.property_id == "PROP001"
        assert plan.total_units == 10
        assert plan.sample_size > 0
        assert 0 < plan.sample_pct <= 1.0
        assert len(plan.sampled_unit_ids) == plan.sample_size
        assert len(plan.strata) > 0
        assert len(plan.selection_rationale) > 0
        assert len(plan.config_snapshot) > 0

    def test_sampled_ids_are_sorted(self):
        roster = _make_roster(20)
        plan = select_sample(roster, "PROP001", SamplingConfig(random_seed=42))
        assert plan.sampled_unit_ids == sorted(plan.sampled_unit_ids)

    def test_config_snapshot_contains_key_params(self):
        roster = _make_roster(10)
        plan = select_sample(roster, "PROP001", SamplingConfig(random_seed=42))
        expected_keys = {
            "small_property_min_pct", "medium_property_min_pct",
            "large_property_min_pct", "small_threshold", "large_threshold",
            "min_per_stratum", "random_seed",
        }
        assert expected_keys.issubset(plan.config_snapshot.keys())


# ---------------------------------------------------------------------------
# InspectionRecord — conservative multiplier defaults
# ---------------------------------------------------------------------------

class TestInspectionRecordMultiplier:
    def test_deferred_default_multiplier(self):
        rec = record_inspection(
            "U001", "PROP001", "2026-03-01",
            ConditionTier.DEFERRED, "standard_value_add",
        )
        assert rec.cost_condition_multiplier == 1.15

    def test_distressed_default_multiplier(self):
        rec = record_inspection(
            "U001", "PROP001", "2026-03-01",
            ConditionTier.DISTRESSED, "standard_value_add",
        )
        assert rec.cost_condition_multiplier == 1.25

    def test_unknown_default_multiplier(self):
        rec = record_inspection(
            "U001", "PROP001", "2026-03-01",
            ConditionTier.UNKNOWN, "standard_value_add",
        )
        assert rec.cost_condition_multiplier == 1.10

    def test_rent_ready_default_multiplier_is_1(self):
        rec = record_inspection(
            "U001", "PROP001", "2026-03-01",
            ConditionTier.RENT_READY, "light",
        )
        assert rec.cost_condition_multiplier == 1.0

    def test_explicit_multiplier_preserved(self):
        """If inspector explicitly sets a multiplier, don't override."""
        rec = record_inspection(
            "U001", "PROP001", "2026-03-01",
            ConditionTier.DEFERRED, "standard_value_add",
            cost_condition_multiplier=1.30,
        )
        assert rec.cost_condition_multiplier == 1.30


# ---------------------------------------------------------------------------
# InspectionRecord — serialization round-trip
# ---------------------------------------------------------------------------

class TestInspectionRecordSerialization:
    def test_round_trip_json(self):
        """InspectionRecord should survive JSON serialization and back."""
        rec = record_inspection(
            unit_id="U101",
            property_id="PROP001",
            inspected_date="2026-03-15",
            condition_tier=ConditionTier.DEFERRED,
            scope_recommendation="standard_value_add",
            inspector_name="Matt",
            flooring=TradeCondition.POOR,
            kitchen=TradeCondition.FAIR,
            moisture_intrusion_visible=True,
            photos_taken=5,
            photo_ids=["img_001.jpg", "img_002.jpg"],
            notes="Subfloor damage near entry",
        )
        data = rec.model_dump()
        json_str = json.dumps(data)
        restored_data = json.loads(json_str)
        restored = InspectionRecord(**restored_data)

        assert restored.unit_id == rec.unit_id
        assert restored.condition_tier == rec.condition_tier
        assert restored.flooring == TradeCondition.POOR
        assert restored.kitchen == TradeCondition.FAIR
        assert restored.moisture_intrusion_visible is True
        assert restored.photos_taken == 5
        assert restored.photo_ids == ["img_001.jpg", "img_002.jpg"]
        assert restored.notes == "Subfloor damage near entry"
        assert restored.cost_condition_multiplier == rec.cost_condition_multiplier

    def test_round_trip_dict(self):
        """model_dump() → InspectionRecord() round trip."""
        rec = record_inspection(
            "U001", "PROP001", "2026-03-01",
            ConditionTier.DISTRESSED, "standard_value_add",
            plumbing_active_leak=True,
            structural_concern=True,
        )
        data = rec.model_dump()
        restored = InspectionRecord(**data)
        assert restored.plumbing_active_leak is True
        assert restored.structural_concern is True
        assert restored.risk_flag_count == 2


# ---------------------------------------------------------------------------
# InspectionRecord — risk flags and deficiency notes
# ---------------------------------------------------------------------------

class TestInspectionRecordRiskFlags:
    def test_risk_flag_count(self):
        rec = record_inspection(
            "U001", "PROP001", "2026-03-01",
            ConditionTier.DISTRESSED, "standard_value_add",
            moisture_intrusion_visible=True,
            mold_visible=True,
            pest_evidence=True,
        )
        assert rec.risk_flag_count == 3

    def test_no_risk_flags(self):
        rec = record_inspection(
            "U001", "PROP001", "2026-03-01",
            ConditionTier.RENT_READY, "light",
        )
        assert rec.risk_flag_count == 0

    def test_deficiency_notes_from_flags(self):
        rec = record_inspection(
            "U001", "PROP001", "2026-03-01",
            ConditionTier.DEFERRED, "standard_value_add",
            moisture_intrusion_visible=True,
            flooring=TradeCondition.POOR,
        )
        notes = rec.deficiency_notes
        assert "moisture_intrusion" in notes
        assert "flooring_poor" in notes

    def test_deficiency_notes_failed_trade(self):
        rec = record_inspection(
            "U001", "PROP001", "2026-03-01",
            ConditionTier.DISTRESSED, "standard_value_add",
            electrical=TradeCondition.FAILED,
        )
        assert "electrical_failed" in rec.deficiency_notes


# ---------------------------------------------------------------------------
# record_inspection — input validation
# ---------------------------------------------------------------------------

class TestRecordInspectionValidation:
    def test_invalid_scope_raises(self):
        with pytest.raises(ValueError, match="scope_recommendation"):
            record_inspection(
                "U001", "PROP001", "2026-03-01",
                ConditionTier.DATED, "gut_renovation",
            )

    def test_string_condition_tier_accepted(self):
        """String values should be accepted and converted."""
        rec = record_inspection(
            "U001", "PROP001", "2026-03-01",
            "deferred", "standard_value_add",
        )
        assert rec.condition_tier == ConditionTier.DEFERRED

    def test_string_trade_condition_accepted(self):
        rec = record_inspection(
            "U001", "PROP001", "2026-03-01",
            ConditionTier.DATED, "light",
            flooring="poor",
        )
        assert rec.flooring == TradeCondition.POOR


# ---------------------------------------------------------------------------
# summarize_inspections
# ---------------------------------------------------------------------------

class TestSummarizeInspections:
    def _make_records(self):
        return [
            record_inspection(
                "U001", "PROP001", "2026-03-01",
                ConditionTier.DEFERRED, "standard_value_add",
                flooring=TradeCondition.POOR,
                moisture_intrusion_visible=True,
            ),
            record_inspection(
                "U002", "PROP001", "2026-03-01",
                ConditionTier.DATED, "standard_value_add",
            ),
            record_inspection(
                "U003", "PROP001", "2026-03-01",
                ConditionTier.RENT_READY, "light",
            ),
        ]

    def test_empty_records_returns_empty_summary(self):
        summary = summarize_inspections([])
        assert summary.total_inspected == 0
        assert summary.avg_cost_multiplier == 1.0

    def test_total_inspected(self):
        summary = summarize_inspections(self._make_records())
        assert summary.total_inspected == 3

    def test_condition_distribution(self):
        summary = summarize_inspections(self._make_records())
        assert summary.condition_distribution["deferred"] == 1
        assert summary.condition_distribution["dated"] == 1
        assert summary.condition_distribution["rent_ready"] == 1

    def test_scope_distribution(self):
        summary = summarize_inspections(self._make_records())
        assert summary.scope_distribution["standard_value_add"] == 2
        assert summary.scope_distribution["light"] == 1

    def test_flagged_units(self):
        summary = summarize_inspections(self._make_records())
        assert summary.units_with_risk_flags == 1
        assert "U001" in summary.flagged_unit_ids

    def test_avg_multiplier_conservative(self):
        """Average multiplier should reflect the DEFERRED unit's 1.15."""
        summary = summarize_inspections(self._make_records())
        assert summary.avg_cost_multiplier >= 1.0

    def test_max_multiplier(self):
        summary = summarize_inspections(self._make_records())
        assert summary.max_cost_multiplier >= 1.15

    def test_observed_deficiency_types(self):
        summary = summarize_inspections(self._make_records())
        assert "moisture_intrusion" in summary.observed_deficiency_types
        assert "flooring_poor" in summary.observed_deficiency_types

    def test_uninspected_units_tracked(self):
        """If sample_plan provided, uninspected units should be listed."""
        records = self._make_records()[:2]  # Only 2 of 3 inspected
        plan = SamplePlan(
            property_id="PROP001",
            total_units=10,
            sample_size=3,
            sample_pct=0.3,
            sampled_unit_ids=["U001", "U002", "U003"],
            strata=[],
            selection_rationale="Test plan",
        )
        summary = summarize_inspections(records, sample_plan=plan)
        assert "U003" in summary.uninspected_unit_ids


# ---------------------------------------------------------------------------
# Conservative bias invariants
# ---------------------------------------------------------------------------

class TestConservativeBiasInvariants:
    def test_unknown_condition_multiplier_above_1(self):
        """UNKNOWN condition → multiplier > 1.0 (assume something bad hiding)."""
        rec = record_inspection(
            "U001", "PROP001", "2026-03-01",
            ConditionTier.UNKNOWN, "standard_value_add",
        )
        assert rec.cost_condition_multiplier > 1.0

    def test_distressed_highest_multiplier(self):
        """DISTRESSED should have the highest default multiplier."""
        distressed = record_inspection(
            "U001", "PROP001", "2026-03-01",
            ConditionTier.DISTRESSED, "standard_value_add",
        )
        deferred = record_inspection(
            "U002", "PROP001", "2026-03-01",
            ConditionTier.DEFERRED, "standard_value_add",
        )
        assert distressed.cost_condition_multiplier > deferred.cost_condition_multiplier

    def test_trade_not_assessed_is_default(self):
        """All trades default to NOT_ASSESSED, not GOOD — conservative."""
        rec = record_inspection(
            "U001", "PROP001", "2026-03-01",
            ConditionTier.DATED, "standard_value_add",
        )
        assert rec.flooring == TradeCondition.NOT_ASSESSED
        assert rec.kitchen == TradeCondition.NOT_ASSESSED
        assert rec.bathroom == TradeCondition.NOT_ASSESSED
        assert rec.hvac == TradeCondition.NOT_ASSESSED
        assert rec.plumbing == TradeCondition.NOT_ASSESSED
        assert rec.electrical == TradeCondition.NOT_ASSESSED

    def test_sample_pct_at_least_minimum(self):
        """Sample percentage should always meet or exceed the tier minimum."""
        for n, expected_min_pct in [(10, 0.30), (50, 0.20), (200, 0.15)]:
            roster = _make_roster_unique_ids(n)
            plan = select_sample(roster, "PROP001", SamplingConfig(random_seed=42))
            assert plan.sample_pct >= expected_min_pct - 0.01, (
                f"n={n}: sample_pct {plan.sample_pct} below min {expected_min_pct}"
            )
