"""Replay today's failing deal JSON through estimate_from_deal.

The original failure path returned the literal string
``"unhandled errors in a TaskGroup (1 sub-exception)"`` because the
agent passed a deal-shaped JSON to a tool that expected loose kwargs,
and the FastMCP TaskGroup wrapper swallowed the underlying validator
error.

This test asserts:
  1. The new estimate_from_deal path either succeeds OR returns a
     structured ValidationProblem with field_errors.
  2. The literal "unhandled errors in a TaskGroup" string is never
     present in the response.
"""
import asyncio
import json
from pathlib import Path

from plat_costmodel.server import estimate_from_deal


_FIXTURE = Path(__file__).parent / "fixtures" / "smoke_test_deal.json"


def _scenarios_for_smoke_deal() -> list[dict]:
    """Two interior scenarios matching the smoke_test_deal.json renovation_programs."""
    return [
        {
            "scope_type": "unit",
            "cohort_id": "cohort_0",
            "scope_level": "standard_value_add",
            "finish_tier": "basic",
            "rent_premium_monthly": 200,
            "schedule": {"start_month": "2026-06", "monthly_pace": 4},
        },
        {
            "scope_type": "unit",
            "cohort_id": "cohort_1",
            "scope_level": "standard_value_add",
            "finish_tier": "upgraded",
            "rent_premium_monthly": 275,
            "schedule": {"start_month": "2026-08", "monthly_pace": 4},
        },
    ]


def test_smoke_deal_does_not_taskgroup_swallow(tmp_db):
    deal = json.loads(_FIXTURE.read_text())
    out = estimate_from_deal(deal, _scenarios_for_smoke_deal())
    serialized = json.dumps(out)
    assert "unhandled errors in a TaskGroup" not in serialized


def test_smoke_deal_either_succeeds_or_structured_error(tmp_db):
    deal = json.loads(_FIXTURE.read_text())
    out = estimate_from_deal(deal, _scenarios_for_smoke_deal())
    if "error_type" in out:
        # Structured error path: must have a non-empty field_errors list
        assert out["field_errors"], (
            f"ValidationProblem returned but field_errors empty: {out}"
        )
    else:
        # Success path: index-aligned with the scenarios list
        scenarios = _scenarios_for_smoke_deal()
        assert "estimates" in out
        assert "renovation_programs" in out
        assert len(out["estimates"]) == len(scenarios)
        assert len(out["renovation_programs"]) == len(scenarios)


def test_corrupted_smoke_deal_returns_structured_error_with_field_errors(tmp_db):
    """Code-review followup: the success-or-error test above structurally
    has a dead error branch when run against the known-good fixture, so a
    regression that returns ``field_errors=[]`` on real failures would slip
    through. This test explicitly corrupts the fixture (missing
    ``renovation_programs``) so the error branch is exercised in CI."""
    deal = json.loads(_FIXTURE.read_text())
    deal.pop("renovation_programs")
    out = estimate_from_deal(deal, _scenarios_for_smoke_deal())
    assert "error_type" in out, f"expected structured error, got success: {out}"
    assert out["error_type"] == "validation_error"
    assert out["field_errors"], (
        f"ValidationProblem must populate field_errors on real failures: {out}"
    )
    assert any(
        fe.get("loc") == ["renovation_programs"] for fe in out["field_errors"]
    ), f"expected a field_errors entry with loc=['renovation_programs'], got: {out['field_errors']}"


def test_smoke_deal_succeeds_end_to_end(tmp_db):
    """The fixture is constructed so it should pass the ROI gate cleanly.
    If this fails, the deal_projection or scope_service has a real bug —
    not a 'structured error is acceptable' situation."""
    deal = json.loads(_FIXTURE.read_text())
    out = estimate_from_deal(deal, _scenarios_for_smoke_deal())
    assert "error_type" not in out, f"unexpected error: {out}"
    assert all(rp["renovation_cost_per_unit"] > 0 for rp in out["renovation_programs"])


def test_smoke_deal_through_fastmcp_dispatch_does_not_raise(tmp_db):
    """Regression lock: the original failure mode was the FastMCP TaskGroup
    wrapper swallowing an unhandled exception as the literal string
    "unhandled errors in a TaskGroup (1 sub-exception)".

    This test invokes estimate_from_deal through mcp.call_tool() — the real
    FastMCP dispatch path that goes through Tool.run() and its exception
    wrapping — rather than calling the Python function directly. That way, a
    future regression where @_validated is bypassed or removed will cause
    this test to fail (Tool.run raises ToolError instead of returning a
    structured dict), rather than surfacing only in production.

    The deal is deliberately missing renovation_programs, which previously
    raised a KeyError in deal_projection. @_validated must convert that into
    a structured ValidationProblem dict; Tool.run must propagate the return
    value cleanly rather than raising.
    """
    from plat_costmodel.server import mcp

    deal = {
        "schema_version": "0.1",
        "property": {"external_alias": "fastmcp-test", "total_units": 4},
        "unit_cohorts": [
            {
                "avg_sqft": 750,
                "avg_bedrooms": 1,
                "avg_bathrooms": 1,
                "unit_count": 4,
                "current_avg_rent": 700,
            },
        ],
        # renovation_programs intentionally missing — previously raised KeyError
        # that was swallowed into "unhandled errors in a TaskGroup (1 sub-exception)"
    }

    # mcp.call_tool() goes through FastMCP's Tool.run() which is the same
    # async dispatch path that the network transport uses.  The result for
    # a dict-returning tool is a list of TextContent objects; we unwrap the
    # first element's .text to recover the JSON dict.
    raw = asyncio.run(mcp.call_tool("estimate_from_deal", {"deal_dict": deal, "scenarios_list": []}))

    # Unwrap TextContent → dict.  If Tool.run raised instead of returning,
    # asyncio.run() would propagate the exception and this line is never reached.
    assert raw, "FastMCP dispatch returned empty content list"
    result = json.loads(raw[0].text)

    serialized = json.dumps(result, default=str)
    assert "unhandled errors in a TaskGroup" not in serialized
    assert isinstance(result, dict)
    assert result.get("error_type") in (
        "validation_error",
        "value_error",
        "not_found",
        "roi_failure",
    ), f"unexpected result shape: {result}"


def test_smoke_deal_through_fastmcp_dispatch_succeeds(tmp_db):
    """Success-path coverage of the FastMCP dispatch wrapping.

    The other smoke parity tests bypass Tool.run() and call the Python
    function directly; this one exercises the @_validated round-trip
    end-to-end with a non-empty scenarios list so that a future regression
    where @_validated is bypassed on the success path would be caught here.
    """
    from plat_costmodel.server import mcp

    deal = json.loads(_FIXTURE.read_text())
    scenarios = _scenarios_for_smoke_deal()
    raw = asyncio.run(
        mcp.call_tool("estimate_from_deal", {"deal_dict": deal, "scenarios_list": scenarios})
    )

    assert raw, "FastMCP dispatch returned empty content list"
    result = json.loads(raw[0].text)

    assert isinstance(result, dict), f"expected dict, got: {type(result)}"
    serialized = json.dumps(result, default=str)
    assert "unhandled errors in a TaskGroup" not in serialized
    assert "error_type" not in result, f"unexpected error on success path: {result}"
    assert "estimates" in result, f"missing 'estimates' key: {result}"
    assert "renovation_programs" in result, f"missing 'renovation_programs' key: {result}"
    assert len(result["estimates"]) == len(scenarios), (
        f"estimates count mismatch: {len(result['estimates'])} != {len(scenarios)}"
    )
    assert all(
        rp["renovation_cost_per_unit"] > 0 for rp in result["renovation_programs"]
    ), f"expected non-zero renovation costs: {result['renovation_programs']}"


def test_estimate_scope_via_fastmcp_unknown_property_returns_not_found(tmp_db):
    """@_validated must catch raise_problem() calls from inside estimate_scope
    (the service layer) and return a structured ValidationProblem dict with
    error_type == 'not_found' — NOT a TaskGroup wrapper string.

    This exercises the FastMCP dispatch path (mcp.call_tool → Tool.run →
    @_validated wrapper) for errors emitted from the service layer, not just
    from input schema validation.
    """
    from plat_costmodel.server import mcp

    # A structurally-valid ScopeRequest dict pointing at a property that does
    # not exist in the DB — this triggers raise_problem('not_found', ...) inside
    # estimate_scope(), which @_validated must catch and convert.
    scope_request = {
        "property_id": "DOES-NOT-EXIST-12345",
        "program_type": "interior_renovation",
        "cohort": {
            "floor_plan_id": "any",
            "unit_count": 1,
            "scope_level": "standard_value_add",
            "finish_tier": "basic",
            "current_monthly_rent": 800,
            "target_monthly_rent": 1000,
        },
        "schedule": {
            "start_month": "2026-06",
            "monthly_pace": 1,
        },
    }

    raw = asyncio.run(mcp.call_tool("estimate_scope", {"scope_request_dict": scope_request}))

    assert raw, "FastMCP dispatch returned empty content list"
    result = json.loads(raw[0].text)

    assert isinstance(result, dict), f"expected dict, got: {type(result)}"
    assert "unhandled errors in a TaskGroup" not in json.dumps(result, default=str)
    assert result.get("error_type") == "not_found", (
        f"expected error_type='not_found', got: {result}"
    )
