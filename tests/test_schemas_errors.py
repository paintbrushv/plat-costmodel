"""Tests for ValidationProblem schema."""
from plat_costmodel.schemas.errors import ValidationProblem


def test_minimal_validation_problem():
    p = ValidationProblem(error_type="validation_error", message="bad input")
    assert p.error_type == "validation_error"
    assert p.message == "bad input"
    assert p.field_errors == []
    assert p.hint == ""


def test_full_validation_problem_round_trip():
    original = ValidationProblem(
        error_type="not_found",
        message="property not found",
        field_errors=[{"loc": ["property_id"], "msg": "missing"}],
        hint="call register_property first",
    )
    dumped = original.model_dump()
    restored = ValidationProblem.model_validate(dumped)
    assert restored == original


def test_error_type_is_required():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ValidationProblem(message="missing error_type")
