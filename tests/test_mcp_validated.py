"""Tests for the _validated decorator that wraps MCP tool handlers."""
import pytest
from pydantic import BaseModel, ValidationError

from plat_costmodel.server import _validated


def test_validated_passthrough_on_success():
    @_validated
    def handler(x: int) -> dict:
        return {"x": x}
    assert handler(5) == {"x": 5}


def test_validated_returns_validation_problem_on_validation_error():
    class Model(BaseModel):
        n: int

    @_validated
    def handler(payload: dict) -> dict:
        Model.model_validate(payload)
        return {"ok": True}

    out = handler({"n": "not-a-number"})
    assert out["error_type"] == "validation_error"
    assert out["field_errors"]
    assert out["field_errors"][0]["loc"] == ["n"]


def test_validated_returns_value_error_for_unknown_value_error():
    @_validated
    def handler() -> dict:
        raise ValueError("plain value error")
    out = handler()
    assert out["error_type"] == "value_error"
    assert "plain value error" in out["message"]


def test_validated_returns_roi_failure_when_value_error_carries_roi_result():
    from plat_costmodel.models import ROIResult

    @_validated
    def handler() -> dict:
        roi = ROIResult(
            total_cost_high=20000, current_monthly_rent=850,
            target_monthly_rent=900, monthly_rent_lift=50, annual_rent_lift=600,
            roi_pct=3.0, clears_threshold=False, note="below 15% threshold",
        )
        err = ValueError("roi gate failed")
        err.roi_result = roi
        raise err

    out = handler()
    assert out["error_type"] == "roi_failure"
    assert out["hint"] == "below 15% threshold"


def test_validated_returns_not_found_for_key_error():
    @_validated
    def handler() -> dict:
        raise KeyError("missing-key")
    out = handler()
    assert out["error_type"] == "not_found"


def test_validated_unwraps_validation_problem_carried_on_value_error():
    """Errors raised by deal_projection / scope_service carry a
    ValidationProblem on the exception via .validation_problem."""
    from plat_costmodel.schemas import ValidationProblem

    @_validated
    def handler() -> dict:
        vp = ValidationProblem(
            error_type="not_found", message="property X not found",
            field_errors=[{"loc": ["property_id"], "msg": "not found"}],
        )
        err = ValueError("property X not found")
        err.validation_problem = vp
        raise err

    out = handler()
    assert out["error_type"] == "not_found"
    assert out["field_errors"][0]["loc"] == ["property_id"]
