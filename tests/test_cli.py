"""Tests for the CLI interface."""

import json
import tempfile
from pathlib import Path

from click.testing import CliRunner

from plat_costmodel.cli import cli


class TestEstimateCommand:
    def test_basic_estimate(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["estimate", "--sqft", "850", "--beds", "2", "--baths", "1"])
        assert result.exit_code == 0
        assert "RENOVATION COST ESTIMATE" in result.output
        assert "flooring" in result.output
        assert "kitchen" in result.output

    def test_json_output(self):
        runner = CliRunner()
        result = runner.invoke(cli, [
            "estimate", "--sqft", "850", "--beds", "2", "--baths", "1", "--json-output"
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "line_items" in data
        assert "total_high" in data

    def test_with_year_built(self):
        runner = CliRunner()
        result = runner.invoke(cli, [
            "estimate", "--sqft", "850", "--beds", "2", "--baths", "1", "--year-built", "1975"
        ])
        assert result.exit_code == 0
        assert "RISK FLAGS" in result.output

    def test_light_scope(self):
        runner = CliRunner()
        result = runner.invoke(cli, [
            "estimate", "--sqft", "850", "--beds", "2", "--baths", "1", "--scope", "light"
        ])
        assert result.exit_code == 0


class TestROICommand:
    def test_passing_roi(self):
        runner = CliRunner()
        result = runner.invoke(cli, [
            "roi", "--cost-high", "15000", "--current-rent", "850", "--target-rent", "1050"
        ])
        assert result.exit_code == 0
        assert "PASS" in result.output

    def test_failing_roi(self):
        runner = CliRunner()
        result = runner.invoke(cli, [
            "roi", "--cost-high", "15000", "--current-rent", "900", "--target-rent", "1000"
        ])
        assert result.exit_code == 0
        assert "FAIL" in result.output

    def test_json_output(self):
        runner = CliRunner()
        result = runner.invoke(cli, [
            "roi", "--cost-high", "15000", "--current-rent", "850", "--target-rent", "1050", "--json-output"
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["clears_threshold"] is True


class TestSOWCommand:
    def test_basic_sow(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["sow", "--sqft", "850", "--beds", "2", "--baths", "1"])
        assert result.exit_code == 0
        assert "SCOPE OF WORK" in result.output

    def test_json_output(self):
        runner = CliRunner()
        result = runner.invoke(cli, [
            "sow", "--sqft", "850", "--beds", "2", "--baths", "1", "--json-output"
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "line_items" in data


class TestEvaluateBidCommand:
    def test_evaluate_bid(self):
        bid_data = {
            "contractor_name": "Test Co",
            "line_items": [
                {"description": "Flooring", "amount": 2000},
                {"description": "Kitchen", "amount": 2000},
                {"description": "Bathroom", "amount": 2800},
                {"description": "Paint", "amount": 1000},
            ],
            "total": 7800,
            "timeline_days": 10,
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(bid_data, f)
            bid_path = f.name

        runner = CliRunner()
        result = runner.invoke(cli, [
            "evaluate-bid", "--bid-json", bid_path,
            "--sqft", "850", "--beds", "2", "--baths", "1"
        ])
        assert result.exit_code == 0
        assert "BID EVALUATION" in result.output
        Path(bid_path).unlink()
