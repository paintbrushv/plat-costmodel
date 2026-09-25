"""Cost range data matrix — per-unit dollar lookup by scope × size × finish level.

This module provides a fast, structured lookup into the pre-computed cost matrix
stored in ``plat_costmodel/data/knowledge_base.yaml`` (shipped package data).  It is
"ballpark" ranges before a full line-item estimate is produced.

Typical usage
-------------
::

    from plat_costmodel.matrix import lookup_range, CostRange
    from plat_costmodel.models import ScopeLevel, SizeCategory, FinishTier

    r = lookup_range("standard_value_add", "medium", "basic", bathrooms=2)
    print(f"${r.low:,.0f} – ${r.high:,.0f}")

Design notes
------------
* Conservative bias: the ``high`` value always errs on the expensive side.
* Ranges include contingency (10 % for light, 15 % for standard_value_add).
* No market adjustment factors — Dallas vs. Birmingham is learned from Yardi actuals.
* All values are configurable by editing ``knowledge_base.yaml``; no numbers are
  hardcoded here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from .models import FinishTier, ScopeLevel, SizeCategory

_KB_PATH = Path(__file__).resolve().parent / "data" / "knowledge_base.yaml"


# ---------------------------------------------------------------------------
# Public data classes
# ---------------------------------------------------------------------------

@dataclass
class CostRange:
    """A low/high cost range in dollars, with optional provenance metadata.

    Attributes:
        low:        Conservative low estimate (dollars, includes contingency).
        high:       Conservative high estimate (dollars, includes contingency).
        basis:      Human-readable description of assumptions baked into this range.
        typical_unit: Description of the unit type this range is calibrated for.
        derivation: Computation note (e.g. which size/finish factors were applied).
    """

    low: float
    high: float
    basis: str = ""
    typical_unit: str = ""
    derivation: str = ""

    def __post_init__(self) -> None:
        if self.high < self.low:
            raise ValueError(
                f"CostRange high ({self.high}) must be >= low ({self.low})"
            )

    def add_bathroom_increment(self, increment: "CostRange", count: int = 1) -> "CostRange":
        """Return a new CostRange with ``count`` additional bathroom increments applied.

        Args:
            increment: The per-bathroom marginal cost range.
            count:     Number of additional bathrooms (beyond the 1-BA baseline).

        Returns:
            New :class:`CostRange` with increments added.
        """
        if count <= 0:
            return self
        return CostRange(
            low=self.low + increment.low * count,
            high=self.high + increment.high * count,
            basis=self.basis,
            typical_unit=self.typical_unit,
            derivation=f"{self.derivation} + {count}x bathroom increment",
        )

    def as_dict(self) -> dict:
        return {
            "low": self.low,
            "high": self.high,
            "basis": self.basis,
            "typical_unit": self.typical_unit,
            "derivation": self.derivation,
        }


@dataclass
class MatrixSummary:
    """Full cost matrix summary for display or inspection.

    Attributes:
        meta:        Metadata from the knowledge base (calibration status, source, etc.).
        light:       Light-scope range (same for all sizes/finishes).
        standard_value_add: Nested dict of ``size → finish → CostRange``.
        per_bathroom_increment: Nested dict of ``size → finish → CostRange``.
    """

    meta: dict = field(default_factory=dict)
    light: Optional[CostRange] = None
    standard_value_add: dict = field(default_factory=dict)
    per_bathroom_increment: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_matrix() -> dict:
    """Load and return the ``cost_matrix`` section of the knowledge base."""
    with open(_KB_PATH) as fh:
        kb = yaml.safe_load(fh)
    matrix = kb.get("cost_matrix")
    if matrix is None:
        raise KeyError(
            "cost_matrix section not found in knowledge_base.yaml. "
            "Re-check the YAML or re-run the seed data setup."
        )
    return matrix


def _cell_to_range(cell: dict) -> CostRange:
    """Convert a YAML cell dict to a :class:`CostRange`."""
    return CostRange(
        low=float(cell["low"]),
        high=float(cell["high"]),
        basis=cell.get("basis", ""),
        typical_unit=cell.get("typical_unit", ""),
        derivation=cell.get("derivation", ""),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def lookup_range(
    scope: "ScopeLevel | str",
    size: "SizeCategory | str",
    finish: "FinishTier | str" = FinishTier.BASIC,
    bathrooms: int = 1,
) -> CostRange:
    """Return the pre-computed cost range for a given scope / size / finish combination.

    Ranges include the appropriate contingency percentage (10 % for light, 15 % for
    standard value-add) and assume a 1-bathroom baseline.  Additional bathrooms are
    automatically added via the per-bathroom increment table.

    Args:
        scope:      ``"light"`` or ``"standard_value_add"`` (or corresponding enum).
        size:       ``"small"`` / ``"medium"`` / ``"large"`` (or :class:`SizeCategory`).
        finish:     ``"basic"`` or ``"upgraded"`` (or :class:`FinishTier`).
                    Ignored for light scope — light turns have no finish differentiation.
        bathrooms:  Total bathroom count.  Values below 1 are treated as 1.

    Returns:
        :class:`CostRange` with ``low`` and ``high`` in dollars.

    Raises:
        ValueError: If ``scope``, ``size``, or ``finish`` is not a recognised value.
        KeyError:   If the cost_matrix section is missing from the knowledge base.

    Examples:
        >>> r = lookup_range("standard_value_add", "medium", "basic")
        >>> assert r.low == 9000
        >>> assert r.high == 13000

        >>> r2 = lookup_range("standard_value_add", "medium", "basic", bathrooms=2)
        >>> assert r2.low == r.low + 2300   # 1 extra BA increment
    """
    scope = ScopeLevel(scope)
    size = SizeCategory(size)
    finish = FinishTier(finish)
    bathrooms = max(1, bathrooms)

    matrix = _load_matrix()

    if scope == ScopeLevel.LIGHT:
        cell = matrix["light"]["all_sizes"]["any_finish"]
        return _cell_to_range(cell)

    # Standard value-add
    sva = matrix["standard_value_add"]
    cell = sva[size.value][finish.value]
    base_range = _cell_to_range(cell)

    extra_baths = bathrooms - 1
    if extra_baths > 0:
        incr_cell = sva["per_bathroom_increment"][size.value][finish.value]
        incr = _cell_to_range(incr_cell)
        return base_range.add_bathroom_increment(incr, count=extra_baths)

    return base_range


def get_per_bathroom_increment(
    size: "SizeCategory | str",
    finish: "FinishTier | str" = FinishTier.BASIC,
) -> CostRange:
    """Return the marginal cost range per additional bathroom (standard_value_add only).

    This is the incremental cost for each bathroom beyond the 1-BA baseline.
    The range includes the 15 % contingency factor.

    Args:
        size:   Unit size category.
        finish: Finish tier.

    Returns:
        :class:`CostRange` representing one additional bathroom's cost.
    """
    size = SizeCategory(size)
    finish = FinishTier(finish)

    matrix = _load_matrix()
    cell = matrix["standard_value_add"]["per_bathroom_increment"][size.value][finish.value]
    return _cell_to_range(cell)


def validate_estimate_against_matrix(
    total_high: float,
    scope: "ScopeLevel | str",
    size: "SizeCategory | str",
    finish: "FinishTier | str" = FinishTier.BASIC,
    bathrooms: int = 1,
    tolerance_pct: float = 25.0,
) -> dict:
    """Cross-check a line-item estimate total against the matrix reference range.

    This is a sanity-check utility — it catches estimates that deviate significantly
    from the pre-computed matrix (which could indicate data-entry errors or
    outlier unit configurations).

    Args:
        total_high:    The line-item estimate's high total (dollars).
        scope:         Scope level.
        size:          Size category.
        finish:        Finish tier.
        bathrooms:     Bathroom count.
        tolerance_pct: Acceptable deviation band (default 25 %).  An estimate
                       that falls outside ``matrix_high * (1 ± tolerance_pct/100)``
                       is flagged.

    Returns:
        Dict with keys:
        * ``within_range``: bool — True if the estimate is within tolerance.
        * ``matrix_low``:   Matrix reference low.
        * ``matrix_high``:  Matrix reference high.
        * ``deviation_pct``: How far total_high deviates from matrix_high (%).
        * ``note``:         Human-readable finding.
    """
    ref = lookup_range(scope, size, finish, bathrooms)
    band_low = ref.high * (1 - tolerance_pct / 100)
    band_high = ref.high * (1 + tolerance_pct / 100)

    within_range = band_low <= total_high <= band_high
    if ref.high > 0:
        deviation_pct = round((total_high - ref.high) / ref.high * 100, 1)
    else:
        deviation_pct = 0.0

    if within_range:
        note = f"Estimate ${total_high:,.0f} is within {tolerance_pct:.0f}% of matrix high ${ref.high:,.0f}."
    elif total_high < band_low:
        note = (
            f"UNDER-RANGE: Estimate ${total_high:,.0f} is {abs(deviation_pct):.1f}% below "
            f"matrix high ${ref.high:,.0f}. Verify inputs — may be under-estimating."
        )
    else:
        note = (
            f"OVER-RANGE: Estimate ${total_high:,.0f} is {deviation_pct:.1f}% above "
            f"matrix high ${ref.high:,.0f}. Likely a high-deferred-maintenance unit or "
            f"unusual scope — confirm line items are correct."
        )

    return {
        "within_range": within_range,
        "matrix_low": ref.low,
        "matrix_high": ref.high,
        "total_high": total_high,
        "deviation_pct": deviation_pct,
        "note": note,
    }


def get_matrix_summary() -> MatrixSummary:
    """Return the full cost matrix as a structured :class:`MatrixSummary` object.

    Useful for CLI display, documentation generation, or inspection.
    """
    matrix = _load_matrix()
    summary = MatrixSummary(meta=matrix.get("_meta", {}))

    # Light
    light_cell = matrix["light"]["all_sizes"]["any_finish"]
    summary.light = _cell_to_range(light_cell)

    # Standard value-add — iterate all size × finish combinations
    sva = matrix["standard_value_add"]
    incr = sva["per_bathroom_increment"]

    for size in SizeCategory:
        size_key = size.value
        summary.standard_value_add[size_key] = {}
        summary.per_bathroom_increment[size_key] = {}

        for finish in FinishTier:
            fin_key = finish.value
            summary.standard_value_add[size_key][fin_key] = _cell_to_range(
                sva[size_key][fin_key]
            )
            summary.per_bathroom_increment[size_key][fin_key] = _cell_to_range(
                incr[size_key][fin_key]
            )

    return summary
