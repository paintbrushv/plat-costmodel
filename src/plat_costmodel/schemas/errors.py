"""Structured error responses for MCP tool boundaries.

Returned by MCP tools instead of letting Pydantic / value / key errors
propagate into the FastMCP TaskGroup wrapper (which today swallows them
into ``"unhandled errors in a TaskGroup (1 sub-exception)"``).
"""
from __future__ import annotations

from typing import NoReturn

from pydantic import BaseModel, Field


class ValidationProblem(BaseModel):
    """A structured error returned from MCP tool handlers."""

    error_type: str
    """One of: ``validation_error``, ``value_error``, ``roi_failure``, ``not_found``."""

    message: str
    """Human-readable summary of what went wrong."""

    field_errors: list[dict] = Field(default_factory=list)
    """List of ``{loc: [...], msg: str}`` dicts for Pydantic-style field errors."""

    hint: str = ""
    """Optional next-step guidance for the caller."""


def raise_problem(
    error_type: str,
    message: str,
    *,
    field_errors: list[dict] | None = None,
    hint: str = "",
) -> NoReturn:
    """Raise a ValueError carrying a structured ValidationProblem.

    The ValidationProblem is attached to the ValueError as
    ``.validation_problem`` so MCP `_validated` decorator can unwrap and
    return it as a structured response.
    """
    vp = ValidationProblem(
        error_type=error_type,
        message=message,
        field_errors=field_errors or [],
        hint=hint,
    )
    err = ValueError(message)
    err.validation_problem = vp  # type: ignore[attr-defined]
    raise err
