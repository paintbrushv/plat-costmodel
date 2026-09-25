"""Tests for Yardi CSV import and parsing."""

import io
import json
import tempfile
from pathlib import Path

from plat_costmodel.ingest import parse_yardi_csv, summarize_by_unit, export_training_data


def _make_csv(rows: list[str]) -> io.StringIO:
    return io.StringIO("\n".join(rows))


SAMPLE_CSV = _make_csv([
    "Date,Unit,Category,Amount,Description",
    "2025-01-15,101,Flooring,$2100.00,LVP installation",
    "2025-01-15,101,Kitchen,$1800.00,Cabinet paint and counters",
    "2025-01-20,101,Bathroom,$2500.00,Vanity and tub resurface",
    "2025-01-22,101,Paint,$950.00,Interior 2-coat",
    "2025-01-25,101,Appliances,$2200.00,Full package stainless",
    "2025-02-01,102,Flooring,$1900.00,LVP throughout",
    "2025-02-01,102,Kitchen,$1650.00,Basic butcher block",
    "2025-02-05,102,HVAC,$3500.00,Mini split install",
    "2025-02-10,,Roof,$45000.00,Building A full replacement",
    "2025-02-15,,Parking lot,$12000.00,Resurface and striping",
])


class TestParseYardiCSV:
    def test_parses_all_rows(self):
        csv = _make_csv([
            "Date,Unit,Category,Amount,Description",
            "2025-01-15,101,Flooring,$2100.00,LVP",
            "2025-01-15,101,Kitchen,$1800.00,Cabinets",
        ])
        records = parse_yardi_csv(csv, "PROP1")
        assert len(records) == 2

    def test_maps_categories(self):
        csv = _make_csv([
            "Date,Unit,Category,Amount,Description",
            "2025-01-15,101,Flooring,$2100.00,LVP",
        ])
        records = parse_yardi_csv(csv, "PROP1")
        assert records[0]["internal_category"] == "flooring"

    def test_handles_currency_format(self):
        csv = _make_csv([
            "Date,Unit,Category,Amount,Description",
            "2025-01-15,101,Flooring,\"$2,100.00\",LVP",
        ])
        records = parse_yardi_csv(csv, "PROP1")
        assert records[0]["amount"] == 2100.0

    def test_maps_hvac(self):
        csv = _make_csv([
            "Date,Unit,Category,Amount,Description",
            "2025-02-05,102,HVAC,$3500.00,Mini split",
        ])
        records = parse_yardi_csv(csv, "PROP1")
        assert records[0]["internal_category"] == "hvac"

    def test_maps_exterior_items(self):
        csv = _make_csv([
            "Date,Unit,Category,Amount,Description",
            "2025-02-10,,Roof,$45000.00,Full replacement",
            "2025-02-15,,Parking lot,$12000.00,Resurface",
        ])
        records = parse_yardi_csv(csv, "PROP1")
        assert records[0]["internal_category"] == "roof"
        assert records[1]["internal_category"] == "parking"

    def test_tags_property_id(self):
        csv = _make_csv([
            "Date,Unit,Category,Amount,Description",
            "2025-01-15,101,Flooring,$2100.00,LVP",
        ])
        records = parse_yardi_csv(csv, "PROP_ABC")
        assert records[0]["property_id"] == "PROP_ABC"

    def test_unknown_category_maps_to_other(self):
        csv = _make_csv([
            "Date,Unit,Category,Amount,Description",
            "2025-01-15,101,Legal fees,$500.00,Attorney",
        ])
        records = parse_yardi_csv(csv, "PROP1")
        assert records[0]["internal_category"] == "other"

    def test_fallback_to_description_mapping(self):
        csv = _make_csv([
            "Date,Unit,Category,Amount,Description",
            "2025-01-15,101,Renovation,$2100.00,LVP flooring install",
        ])
        records = parse_yardi_csv(csv, "PROP1")
        assert records[0]["internal_category"] == "flooring"

    def test_file_path_input(self, tmp_path):
        csv_path = tmp_path / "test.csv"
        csv_path.write_text("Date,Unit,Category,Amount,Description\n2025-01-15,101,Flooring,$2100.00,LVP\n")
        records = parse_yardi_csv(csv_path, "PROP1")
        assert len(records) == 1


class TestSummarizeByUnit:
    def test_groups_by_unit(self):
        records = [
            {"unit_id": "101", "internal_category": "flooring", "amount": 2100},
            {"unit_id": "101", "internal_category": "kitchen", "amount": 1800},
            {"unit_id": "102", "internal_category": "flooring", "amount": 1900},
        ]
        summary = summarize_by_unit(records)
        assert "101" in summary
        assert "102" in summary
        assert summary["101"]["total"] == 3900
        assert summary["101"]["categories"]["flooring"] == 2100

    def test_empty_records(self):
        summary = summarize_by_unit([])
        assert summary == {}


class TestExportTrainingData:
    def test_exports_json(self, tmp_path):
        records = [
            {"property_id": "PROP1", "unit_id": "101", "internal_category": "flooring", "amount": 2100},
        ]
        output = tmp_path / "training.json"
        count = export_training_data(records, output)
        assert count == 1
        assert output.exists()
        data = json.loads(output.read_text())
        assert len(data) == 1

    def test_creates_parent_dirs(self, tmp_path):
        output = tmp_path / "subdir" / "training.json"
        count = export_training_data([{"test": 1}], output)
        assert count == 1
        assert output.exists()
