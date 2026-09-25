"""Risk flag generation based on property age and characteristics."""

from pathlib import Path
from typing import Union

import yaml

from .models import RiskFlag

_KB_PATH = Path(__file__).resolve().parent.parent / "data" / "knowledge_base.yaml"


def _load_risk_rules() -> list[dict]:
    with open(_KB_PATH) as f:
        kb = yaml.safe_load(f)
    return kb.get("risk_flags", [])


def _parse_flag_entry(entry: Union[str, dict]) -> tuple[str, str, str]:
    """Parse a flag entry from the knowledge base.

    Supports both legacy string format and new dict format with
    ``message``, ``type``, and ``recommended_action`` keys.

    Returns:
        (message, flag_type, recommended_action)
    """
    if isinstance(entry, str):
        return entry, "", ""
    return (
        entry.get("message", ""),
        entry.get("type", ""),
        entry.get("recommended_action", ""),
    )


def get_risk_flags(year_built: int | None) -> list[RiskFlag]:
    """Return risk flags triggered by the property's year built.

    Each returned :class:`~plat_costmodel.models.RiskFlag` carries:

    * ``message`` — plain-English description of the hazard
    * ``flag_type`` — machine-readable hazard category (e.g. ``"lead_paint"``)
    * ``severity`` — ``"critical"`` for pre-1985 hazards, ``"warning"`` otherwise
    * ``triggered_by`` — the year-range rule that fired (for audit trail)
    * ``recommended_action`` — specific mitigation step with cost guidance

    Args:
        year_built: Four-digit construction year, or ``None`` if unknown.

    Returns:
        Ordered list of :class:`RiskFlag` objects.  Empty list means no
        age-based risks were identified.
    """
    if year_built is None:
        return [RiskFlag(
            message="Year built unknown — cannot assess age-based risks. Recommend full inspection.",
            flag_type="unknown_age",
            severity="warning",
            triggered_by="year_built is None",
            recommended_action=(
                "Obtain year built from county appraisal records or seller disclosure. "
                "Schedule full property inspection to identify hazardous materials manually."
            ),
        )]

    flags: list[RiskFlag] = []
    for rule in _load_risk_rules():
        low, high = rule["year_range"]
        if low <= year_built <= high:
            # Pre-1986 hazards (lead, asbestos, galvanized) are critical; later are warnings
            severity = "critical" if high <= 1985 else "warning"
            for entry in rule["flags"]:
                message, flag_type, recommended_action = _parse_flag_entry(entry)
                flags.append(RiskFlag(
                    message=message,
                    flag_type=flag_type,
                    severity=severity,
                    triggered_by=f"year_built {year_built} in [{low}, {high}]",
                    recommended_action=recommended_action,
                ))
    return flags
