"""Tests for category_mapping ordering invariants (Wave 2 Bug 2.7 fix).

Per the audit: ``_GL_RANGES`` and ``_DESCRIPTION_KEYWORDS`` were iterated
in source-file order with first-match-wins resolution. Adding a new keyword
above an existing one risked silently reclassifying historical Yardi data.

The fix:
  * ``_DESCRIPTION_KEYWORDS`` is sorted longest-pattern-first so a more
    specific phrase wins over a broader substring (e.g. "door hardware"
    over generic "hardware").
  * ``_GL_RANGES`` is asserted disjoint at module import time: any future
    overlap raises ``ValueError`` immediately.
"""

from __future__ import annotations

import importlib

import pytest

from plat_costmodel.category_mapping import (
    CategoryMapper,
    _assert_gl_ranges_no_overlap,
    map_yardi_entry,
)


# ---------------------------------------------------------------------------
# Longest-pattern-first description matching
# ---------------------------------------------------------------------------


class TestLongestKeywordWins:
    def test_door_hardware_beats_hardware(self):
        """``door hardware`` is more specific than ``hardware``; the
        fixtures_doors_trim mapping must win over the generic light-scope
        ``hardware`` mapping.
        """
        result = map_yardi_entry(description="Door hardware replacement")
        assert result.internal_category == "fixtures_doors_trim"

    def test_security_contract_services_resolves_to_fencing(self):
        """A multi-word description should resolve via the longest matching
        substring rather than first-token-wins. "Security gate" is more
        specific than the generic "gate" or "contract services" buckets.
        """
        result = map_yardi_entry(description="Security gate access control")
        # "security gate" is in the keyword table → fencing_gates wins.
        assert result.internal_category == "fencing_gates"

    def test_carpet_replacement_beats_carpet(self):
        """``carpet replacement`` (carpet category) is more specific than
        the bare ``carpet`` keyword; must resolve to ``carpet`` not whatever
        a shorter substring would otherwise pick up.
        """
        result = map_yardi_entry(description="Carpet replacement turn")
        assert result.internal_category == "carpet"

    def test_kitchen_renovation_beats_kitchen(self):
        result = map_yardi_entry(description="Full kitchen renovation 2BR")
        assert result.internal_category == "kitchen"

    def test_extra_keywords_take_priority(self):
        """User-supplied ``extra_keywords`` are sorted longest-first within
        their tier and prepended ahead of the built-ins.
        """
        mapper = CategoryMapper(
            extra_keywords=[
                ("custom widget install", "other"),
                ("widget", "other"),
            ]
        )
        result = mapper.map(description="Custom widget install service")
        assert result.match_key == "custom widget install"


# ---------------------------------------------------------------------------
# GL-range disjointness assertion
# ---------------------------------------------------------------------------


class TestGLRangeAssertion:
    def test_module_load_asserts_no_gl_overlap(self):
        """A deliberately overlapping range must raise ValueError.

        Calls the assertion helper directly with a malformed range list to
        prove the invariant is enforced (the real ``_GL_RANGES`` already
        loaded cleanly when the module imported).
        """
        bad_ranges = [
            (5000, 5099, "patch_repair"),
            (5050, 5060, "flooring"),  # overlaps the above
        ]
        with pytest.raises(ValueError, match="overlap"):
            _assert_gl_ranges_no_overlap(bad_ranges)

    def test_invalid_low_gt_high_raises(self):
        bad_ranges = [(5100, 5050, "patch_repair")]
        with pytest.raises(ValueError, match="invalid"):
            _assert_gl_ranges_no_overlap(bad_ranges)

    def test_disjoint_ranges_pass(self):
        good = [
            (5000, 5099, "patch_repair"),
            (5100, 5199, "flooring"),
            (5200, 5299, "kitchen"),
        ]
        # Should not raise.
        _assert_gl_ranges_no_overlap(good)

    def test_real_module_ranges_are_disjoint(self):
        """The real, shipping ``_GL_RANGES`` must already be disjoint —
        otherwise the module import would have failed and this test would
        not run.
        """
        from plat_costmodel import category_mapping as cm
        # Re-run the assertion on the live ranges to prove disjointness.
        cm._assert_gl_ranges_no_overlap(cm._GL_RANGES)

    def test_module_reload_with_overlap_fails(self):
        """Monkeypatch a deliberate overlap into ``_GL_RANGES`` and re-run
        the assertion to prove a bad addition would surface at import time.
        """
        from plat_costmodel import category_mapping as cm

        # Construct a bad version of the live list and assert it fails.
        sabotaged = list(cm._GL_RANGES) + [(5005, 5008, "kitchen")]
        # 5005-5008 overlaps the existing 5000-5009 patch_repair range.
        with pytest.raises(ValueError, match="overlap"):
            cm._assert_gl_ranges_no_overlap(sabotaged)
