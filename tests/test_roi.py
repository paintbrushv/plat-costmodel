"""Tests for ROI threshold gating."""

import pytest
from plat_costmodel.roi import check_roi


class TestROICheck:
    def test_passes_threshold(self):
        """$15K cost, $850→$1050 rent = $2400/yr = 16% ROI → passes."""
        result = check_roi(15000, 850, 1050)
        assert result.clears_threshold is True
        assert result.roi_pct == 16.0

    def test_fails_threshold(self):
        """$15K cost, $900→$1000 rent = $1200/yr = 8% ROI → fails."""
        result = check_roi(15000, 900, 1000)
        assert result.clears_threshold is False
        assert result.roi_pct == 8.0

    def test_exactly_at_threshold(self):
        """Exactly 15% should pass."""
        # $15K cost, need $2250/yr = $187.50/mo lift
        result = check_roi(15000, 800, 987.50)
        assert result.clears_threshold is True
        assert result.roi_pct == 15.0

    def test_uses_high_estimate(self):
        """The note should confirm using conservative (high) cost."""
        result = check_roi(15000, 850, 1050)
        assert "conservative" in result.note.lower() or "high" in result.note.lower()

    def test_failure_note_shows_needed_rent(self):
        result = check_roi(15000, 900, 1000)
        assert "need" in result.note.lower() or "fails" in result.note.lower()

    def test_zero_cost_returns_zero_roi(self):
        result = check_roi(0, 850, 1050)
        assert result.roi_pct == 0.0
        assert result.clears_threshold is False

    def test_negative_rent_lift(self):
        """If target rent is below current, ROI is negative."""
        result = check_roi(15000, 1000, 900)
        assert result.roi_pct < 0
        assert result.clears_threshold is False

    def test_custom_threshold(self):
        result = check_roi(15000, 850, 1050, threshold_pct=20.0)
        assert result.threshold_pct == 20.0
        assert result.clears_threshold is False  # 16% < 20%

    def test_monthly_and_annual_lift(self):
        result = check_roi(15000, 850, 1050)
        assert result.monthly_rent_lift == 200
        assert result.annual_rent_lift == 2400
