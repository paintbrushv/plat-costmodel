"""Yardi Voyager CSV import and parsing.

Ingests Yardi expense exports, maps every row to a standardized rehab cost
category via the category_mapping module, and produces records ready for
cost-model training and budget-vs-actual tracking.
"""

import csv
import json
from pathlib import Path
from typing import TextIO

from .category_mapping import CategoryMapper, map_yardi_entry

# Module-level default mapper (can be overridden per-call if needed)
_DEFAULT_MAPPER = CategoryMapper()


def parse_yardi_csv(
    csv_file: str | Path | TextIO,
    property_id: str,
    category_column: str = "Category",
    amount_column: str = "Amount",
    unit_column: str = "Unit",
    date_column: str = "Date",
    description_column: str = "Description",
    gl_code_column: str = "GL Account",
    mapper: CategoryMapper | None = None,
) -> list[dict]:
    """Parse a Yardi Voyager CSV expense export into structured records.

    Each output record includes:
      - property_id, unit_id, date, amount, description
      - yardi_category (raw Yardi field)
      - gl_code (raw GL account code, if present)
      - internal_category (standardized rehab category)
      - mapping_source ("gl_exact" | "gl_range" | "description" | "fallback")
      - mapping_confidence ("high" | "medium" | "low")

    Args:
        csv_file: Path to CSV file or file-like object.
        property_id: Property identifier to tag all records with.
        category_column: Column name for Yardi expense category.
        amount_column: Column name for dollar amount.
        unit_column: Column name for unit number.
        date_column: Column name for date.
        description_column: Column name for free-text description.
        gl_code_column: Column name for GL account code (optional — may not be
            present in every Yardi export format).
        mapper: Custom CategoryMapper instance.  Defaults to module-level mapper.

    Returns:
        List of parsed expense records with internal category mapping applied.
    """
    active_mapper = mapper or _DEFAULT_MAPPER

    if isinstance(csv_file, (str, Path)):
        with open(csv_file, newline="") as f:
            return _parse_rows(
                f, property_id, category_column, amount_column,
                unit_column, date_column, description_column,
                gl_code_column, active_mapper,
            )
    else:
        return _parse_rows(
            csv_file, property_id, category_column, amount_column,
            unit_column, date_column, description_column,
            gl_code_column, active_mapper,
        )


def _parse_rows(
    f: TextIO,
    property_id: str,
    category_column: str,
    amount_column: str,
    unit_column: str,
    date_column: str,
    description_column: str,
    gl_code_column: str,
    mapper: CategoryMapper,
) -> list[dict]:
    reader = csv.DictReader(f)
    records = []

    for row in reader:
        yardi_category = row.get(category_column, "").strip()
        amount_str = row.get(amount_column, "0").strip()
        unit_id = row.get(unit_column, "").strip()
        date_str = row.get(date_column, "").strip()
        description = row.get(description_column, "").strip()
        gl_code = row.get(gl_code_column, "").strip()

        # Parse amount — handle currency formatting ($1,234.56 or 1234.56)
        try:
            amount = float(amount_str.replace("$", "").replace(",", ""))
        except (ValueError, AttributeError):
            amount = 0.0

        # Map to internal category using the full mapping hierarchy
        result = mapper.map(
            gl_code=gl_code or None,
            description=description or None,
            category_name=yardi_category or None,
        )

        records.append({
            "property_id": property_id,
            "unit_id": unit_id,
            "date": date_str,
            "yardi_category": yardi_category,
            "gl_code": gl_code,
            "internal_category": result.internal_category,
            "mapping_source": result.source,
            "mapping_confidence": result.confidence,
            "amount": amount,
            "description": description,
        })

    return records


def summarize_by_unit(records: list[dict]) -> dict[str, dict]:
    """Summarize parsed records by unit, grouping costs by internal category.

    Returns:
        Dict keyed by unit_id, each containing category totals and grand total.
    """
    units: dict[str, dict] = {}

    for rec in records:
        uid = rec["unit_id"]
        if uid not in units:
            units[uid] = {"unit_id": uid, "categories": {}, "total": 0.0}

        cat = rec["internal_category"]
        if cat not in units[uid]["categories"]:
            units[uid]["categories"][cat] = 0.0
        units[uid]["categories"][cat] += rec["amount"]
        units[uid]["total"] += rec["amount"]

    return units


def export_training_data(records: list[dict], output_path: str | Path) -> int:
    """Export parsed records as JSON for training the cost model.

    Returns the number of records written.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        json.dump(records, f, indent=2, default=str)

    return len(records)
