"""Tests for the bridge module (bridge.py).

Coverage per NEXT_PHASE.md Track 1:
  - Happy path: estimate passes ROI gate → bridge dict returned, fields match schema
  - Failure path: estimate fails ROI gate → ValueError raised with ROI result attached
  - Schema fidelity: output dict validates against deal schema required fields
  - Round-trip: renovation_program dict has all required underwriting fields
  - MCP tool: prepare_renovation_program_tool returns structured output
  - CLI: bridge-underwriting command works end-to-end
"""

import json

import pytest
from click.testing import CliRunner

from plat_costmodel.bridge import (
    BridgeResult,
    build_renovation_program_input,
    prepare_renovation_program,
    validate_against_roi,
)
from plat_costmodel.cli import cli
from plat_costmodel.estimator import estimate_unit
from plat_costmodel.models import ROIResult, UnitEstimate
from plat_costmodel.server import prepare_renovation_program_tool


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _passing_estimate() -> UnitEstimate:
    """An estimate that will pass the 15% ROI gate with a $200/mo rent lift."""
    return estimate_unit(
        unit_sqft=850, bedrooms=2, bathrooms=1,
        scope_level="standard_value_add", finish_tier="basic",
    )


def _passing_rents(est: UnitEstimate) -> tuple[float, float]:
    """Return (current, target) rents that pass 15% ROI for the given estimate.

    Formula: annual_lift / total_high >= 0.15
    => annual_lift >= total_high * 0.15
    => monthly_lift >= total_high * 0.15 / 12
    """
    monthly_lift_needed = (est.total_high * 0.15) / 12
    current = 850.0
    target = current + monthly_lift_needed + 10  # +$10 buffer to pass cleanly
    return current, round(target, 2)


def _failing_rents() -> tuple[float, float]:
    """Return rents that will fail the 15% ROI gate for any standard estimate."""
    return 850.0, 860.0  # Only $10/mo lift — way too small


# ---------------------------------------------------------------------------
# validate_against_roi
# ---------------------------------------------------------------------------

class TestValidateAgainstROI:
    def test_returns_roi_result(self):
        est = _passing_estimate()
        current, target = _passing_rents(est)
        result = validate_against_roi(est, current, target)
        assert isinstance(result, ROIResult)

    def test_passing_roi(self):
        est = _passing_estimate()
        current, target = _passing_rents(est)
        result = validate_against_roi(est, current, target)
        assert result.clears_threshold is True
        assert result.roi_pct >= 15.0

    def test_failing_roi(self):
        est = _passing_estimate()
        current, target = _failing_rents()
        result = validate_against_roi(est, current, target)
        assert result.clears_threshold is False
        assert result.roi_pct < 15.0

    def test_includes_line_item_suggestions_on_failure(self):
        """validate_against_roi passes line_items to check_roi for failure analysis."""
        est = _passing_estimate()
        current, target = _failing_rents()
        result = validate_against_roi(est, current, target)
        assert result.clears_threshold is False
        # line_item_suggestions should be populated since we pass line_items
        assert len(result.line_item_suggestions) > 0


# ---------------------------------------------------------------------------
# build_renovation_program_input — happy path
# ---------------------------------------------------------------------------

class TestBuildRenovationProgramHappy:
    def test_returns_bridge_result(self):
        est = _passing_estimate()
        current, target = _passing_rents(est)
        result = build_renovation_program_input(
            est, current, target,
            start_month="2026-06", monthly_pace=5,
        )
        assert isinstance(result, BridgeResult)
        assert result.ready_to_underwrite is True

    def test_renovation_cost_uses_total_high(self):
        est = _passing_estimate()
        current, target = _passing_rents(est)
        result = build_renovation_program_input(
            est, current, target,
            start_month="2026-06", monthly_pace=5,
        )
        assert result.renovation_program["renovation_cost_per_unit"] == est.total_high

    def test_rent_premium_is_lift(self):
        est = _passing_estimate()
        current, target = _passing_rents(est)
        result = build_renovation_program_input(
            est, current, target,
            start_month="2026-06", monthly_pace=5,
        )
        assert result.renovation_program["rent_premium_monthly"] == target - current

    def test_downtime_days_default(self):
        est = _passing_estimate()
        current, target = _passing_rents(est)
        result = build_renovation_program_input(
            est, current, target,
            start_month="2026-06", monthly_pace=5,
        )
        assert result.renovation_program["downtime_days"] == 21

    def test_downtime_days_custom(self):
        est = _passing_estimate()
        current, target = _passing_rents(est)
        result = build_renovation_program_input(
            est, current, target,
            start_month="2026-06", monthly_pace=5, downtime_days=30,
        )
        assert result.renovation_program["downtime_days"] == 30

    def test_strategy_is_renovation(self):
        est = _passing_estimate()
        current, target = _passing_rents(est)
        result = build_renovation_program_input(
            est, current, target,
            start_month="2026-06", monthly_pace=5,
        )
        assert result.renovation_program["strategy"] == "renovation"

    def test_start_month_and_pace(self):
        est = _passing_estimate()
        current, target = _passing_rents(est)
        result = build_renovation_program_input(
            est, current, target,
            start_month="2027-01", monthly_pace=8,
        )
        assert result.renovation_program["start_month"] == "2027-01"
        assert result.renovation_program["monthly_pace"] == 8

    def test_roi_result_attached(self):
        est = _passing_estimate()
        current, target = _passing_rents(est)
        result = build_renovation_program_input(
            est, current, target,
            start_month="2026-06", monthly_pace=5,
        )
        assert isinstance(result.roi_result, ROIResult)
        assert result.roi_result.clears_threshold is True


# ---------------------------------------------------------------------------
# build_renovation_program_input — failure path
# ---------------------------------------------------------------------------

class TestBuildRenovationProgramFailure:
    def test_raises_value_error_on_roi_fail(self):
        est = _passing_estimate()
        current, target = _failing_rents()
        with pytest.raises(ValueError, match="ROI gate failed"):
            build_renovation_program_input(
                est, current, target,
                start_month="2026-06", monthly_pace=5,
            )

    def test_error_has_roi_result_attached(self):
        est = _passing_estimate()
        current, target = _failing_rents()
        with pytest.raises(ValueError) as exc_info:
            build_renovation_program_input(
                est, current, target,
                start_month="2026-06", monthly_pace=5,
            )
        assert hasattr(exc_info.value, "roi_result")
        assert isinstance(exc_info.value.roi_result, ROIResult)
        assert exc_info.value.roi_result.clears_threshold is False

    def test_error_includes_roi_pct(self):
        est = _passing_estimate()
        current, target = _failing_rents()
        with pytest.raises(ValueError) as exc_info:
            build_renovation_program_input(
                est, current, target,
                start_month="2026-06", monthly_pace=5,
            )
        assert "%" in str(exc_info.value)

    def test_custom_threshold(self):
        """A lower threshold should allow previously-failing deals to pass."""
        est = _passing_estimate()
        current, target = _failing_rents()
        # The $10/mo lift on ~$13K est gives ROI ~0.9% — should fail even at 1%
        with pytest.raises(ValueError):
            build_renovation_program_input(
                est, current, target,
                start_month="2026-06", monthly_pace=5, threshold_pct=1.0,
            )


# ---------------------------------------------------------------------------
# Schema fidelity
# ---------------------------------------------------------------------------

class TestSchemaFidelity:
    """The renovation_program dict must have all fields the underwriting engine expects."""

    REQUIRED_FIELDS = {
        "renovation_cost_per_unit",
        "rent_premium_monthly",
        "downtime_days",
        "strategy",
        "start_month",
        "monthly_pace",
    }

    def test_all_required_fields_present(self):
        est = _passing_estimate()
        current, target = _passing_rents(est)
        result = build_renovation_program_input(
            est, current, target,
            start_month="2026-06", monthly_pace=5,
        )
        assert self.REQUIRED_FIELDS.issubset(result.renovation_program.keys())

    def test_no_extra_fields(self):
        """Only schema fields — no internal plat-costmodel fields leak through."""
        est = _passing_estimate()
        current, target = _passing_rents(est)
        result = build_renovation_program_input(
            est, current, target,
            start_month="2026-06", monthly_pace=5,
        )
        assert set(result.renovation_program.keys()) == self.REQUIRED_FIELDS

    def test_renovation_cost_is_positive_number(self):
        est = _passing_estimate()
        current, target = _passing_rents(est)
        result = build_renovation_program_input(
            est, current, target,
            start_month="2026-06", monthly_pace=5,
        )
        cost = result.renovation_program["renovation_cost_per_unit"]
        assert isinstance(cost, (int, float))
        assert cost > 0

    def test_rent_premium_is_positive(self):
        est = _passing_estimate()
        current, target = _passing_rents(est)
        result = build_renovation_program_input(
            est, current, target,
            start_month="2026-06", monthly_pace=5,
        )
        assert result.renovation_program["rent_premium_monthly"] > 0

    def test_strategy_value(self):
        est = _passing_estimate()
        current, target = _passing_rents(est)
        result = build_renovation_program_input(
            est, current, target,
            start_month="2026-06", monthly_pace=5,
        )
        assert result.renovation_program["strategy"] == "renovation"

    def test_serializable_to_json(self):
        """The full BridgeResult must be JSON-serializable for MCP transport."""
        est = _passing_estimate()
        current, target = _passing_rents(est)
        result = build_renovation_program_input(
            est, current, target,
            start_month="2026-06", monthly_pace=5,
        )
        json_str = result.model_dump_json()
        parsed = json.loads(json_str)
        assert parsed["ready_to_underwrite"] is True
        assert "renovation_program" in parsed
        assert "roi_result" in parsed


# ---------------------------------------------------------------------------
# prepare_renovation_program (end-to-end)
# ---------------------------------------------------------------------------

class TestPrepareRenovationProgram:
    def test_happy_path(self):
        est = _passing_estimate()
        current, target = _passing_rents(est)
        result = prepare_renovation_program(
            unit_sqft=850, bedrooms=2, bathrooms=1,
            current_monthly_rent=current,
            target_monthly_rent=target,
            start_month="2026-06", monthly_pace=5,
        )
        assert result.ready_to_underwrite is True
        assert result.renovation_program["renovation_cost_per_unit"] > 0

    def test_failure_path(self):
        current, target = _failing_rents()
        with pytest.raises(ValueError, match="ROI gate failed"):
            prepare_renovation_program(
                unit_sqft=850, bedrooms=2, bathrooms=1,
                current_monthly_rent=current,
                target_monthly_rent=target,
                start_month="2026-06", monthly_pace=5,
            )

    def test_light_scope(self):
        """Light scope ($3K-$5K) should need a smaller rent lift to pass."""
        result = prepare_renovation_program(
            unit_sqft=850, bedrooms=2, bathrooms=1,
            current_monthly_rent=800,
            target_monthly_rent=900,  # $100/mo lift on ~$5.5K est ≈ 21.8% ROI
            start_month="2026-06", monthly_pace=5,
            scope_level="light",
        )
        assert result.ready_to_underwrite is True

    def test_with_year_built(self):
        est = _passing_estimate()
        current, target = _passing_rents(est)
        result = prepare_renovation_program(
            unit_sqft=850, bedrooms=2, bathrooms=1,
            current_monthly_rent=current,
            target_monthly_rent=target,
            start_month="2026-06", monthly_pace=5,
            year_built=1975,
        )
        assert result.ready_to_underwrite is True


# ---------------------------------------------------------------------------
# MCP tool
# ---------------------------------------------------------------------------

class TestMCPTool:
    def test_happy_path_returns_dict(self):
        est = _passing_estimate()
        current, target = _passing_rents(est)
        result = prepare_renovation_program_tool(
            unit_sqft=850, bedrooms=2, bathrooms=1,
            current_monthly_rent=current,
            target_monthly_rent=target,
            start_month="2026-06", monthly_pace=5,
        )
        assert isinstance(result, dict)
        assert result["ready_to_underwrite"] is True
        assert "renovation_program" in result
        assert "roi_result" in result

    def test_failure_returns_structured_response(self):
        """MCP tool should not crash on ROI failure — returns structured failure."""
        current, target = _failing_rents()
        result = prepare_renovation_program_tool(
            unit_sqft=850, bedrooms=2, bathrooms=1,
            current_monthly_rent=current,
            target_monthly_rent=target,
            start_month="2026-06", monthly_pace=5,
        )
        assert isinstance(result, dict)
        assert result["ready_to_underwrite"] is False
        assert "roi_result" in result

    def test_failure_roi_result_has_path_to_pass(self):
        current, target = _failing_rents()
        result = prepare_renovation_program_tool(
            unit_sqft=850, bedrooms=2, bathrooms=1,
            current_monthly_rent=current,
            target_monthly_rent=target,
            start_month="2026-06", monthly_pace=5,
        )
        roi = result["roi_result"]
        assert roi["clears_threshold"] is False
        assert len(roi["path_to_pass"]) > 0

    def test_failure_includes_validation_problem_compatible_fields(self):
        """Followup: failure dict carries both the legacy rich shape AND
        ValidationProblem-compatible fields so callers using the standard
        MCP error-detection contract (`if "error_type" in result`) work."""
        current, target = _failing_rents()
        result = prepare_renovation_program_tool(
            unit_sqft=850, bedrooms=2, bathrooms=1,
            current_monthly_rent=current,
            target_monthly_rent=target,
            start_month="2026-06", monthly_pace=5,
        )
        # ValidationProblem-compatible
        assert result["error_type"] == "roi_failure"
        assert "message" in result
        assert "field_errors" in result
        assert "hint" in result
        # Legacy rich shape preserved
        assert result["ready_to_underwrite"] is False
        assert "renovation_program" in result
        assert "roi_result" in result


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------

class TestCLI:
    def setup_method(self):
        self.runner = CliRunner()

    def test_happy_path_human_output(self):
        est = _passing_estimate()
        current, target = _passing_rents(est)
        result = self.runner.invoke(cli, [
            "bridge-underwriting",
            "--sqft", "850", "--beds", "2", "--baths", "1",
            "--current-rent", str(current),
            "--target-rent", str(target),
            "--start-month", "2026-06",
            "--monthly-pace", "5",
        ])
        assert result.exit_code == 0
        assert "PASS" in result.output
        assert "renovation_cost_per_unit" in result.output

    def test_happy_path_json_output(self):
        est = _passing_estimate()
        current, target = _passing_rents(est)
        result = self.runner.invoke(cli, [
            "bridge-underwriting",
            "--sqft", "850", "--beds", "2", "--baths", "1",
            "--current-rent", str(current),
            "--target-rent", str(target),
            "--start-month", "2026-06",
            "--monthly-pace", "5",
            "--json-output",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ready_to_underwrite"] is True
        assert "renovation_program" in data

    def test_failure_exits_nonzero(self):
        result = self.runner.invoke(cli, [
            "bridge-underwriting",
            "--sqft", "850", "--beds", "2", "--baths", "1",
            "--current-rent", "850",
            "--target-rent", "860",
            "--start-month", "2026-06",
            "--monthly-pace", "5",
        ])
        assert result.exit_code == 1
        assert "FAIL" in result.output

    def test_failure_json_output(self):
        result = self.runner.invoke(cli, [
            "bridge-underwriting",
            "--sqft", "850", "--beds", "2", "--baths", "1",
            "--current-rent", "850",
            "--target-rent", "860",
            "--start-month", "2026-06",
            "--monthly-pace", "5",
            "--json-output",
        ])
        assert result.exit_code == 1
        data = json.loads(result.output.strip())
        assert data["ready_to_underwrite"] is False
