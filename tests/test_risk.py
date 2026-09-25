"""Tests for risk flag generation."""

from plat_costmodel.risk import get_risk_flags


class TestRiskFlags:
    # -------------------------------------------------------------------------
    # Existing message / severity / triggered_by tests
    # -------------------------------------------------------------------------

    def test_1975_build_has_galvanized_flag(self):
        flags = get_risk_flags(1975)
        messages = [f.message for f in flags]
        assert any("galvanized" in m.lower() for m in messages)

    def test_1975_build_has_lead_paint_flag(self):
        flags = get_risk_flags(1975)
        messages = [f.message for f in flags]
        assert any("lead paint" in m.lower() for m in messages)

    def test_1975_build_has_asbestos_flag(self):
        flags = get_risk_flags(1975)
        messages = [f.message for f in flags]
        assert any("asbestos" in m.lower() for m in messages)

    def test_1985_build_has_electrical_flag(self):
        flags = get_risk_flags(1985)
        messages = [f.message for f in flags]
        assert any("electrical" in m.lower() for m in messages)

    def test_1995_build_has_foundation_flag(self):
        flags = get_risk_flags(1995)
        messages = [f.message for f in flags]
        assert any("foundation" in m.lower() for m in messages)

    def test_2005_build_no_flags(self):
        flags = get_risk_flags(2005)
        assert len(flags) == 0

    def test_none_year_warns(self):
        flags = get_risk_flags(None)
        assert len(flags) == 1
        assert "unknown" in flags[0].message.lower()

    def test_old_buildings_have_critical_severity(self):
        flags = get_risk_flags(1975)
        assert any(f.severity == "critical" for f in flags)

    def test_triggered_by_includes_year(self):
        flags = get_risk_flags(1975)
        assert any("1975" in f.triggered_by for f in flags)

    # -------------------------------------------------------------------------
    # flag_type tests (Sub-AC 5b: structured type field)
    # -------------------------------------------------------------------------

    def test_lead_paint_flag_has_correct_type(self):
        """lead_paint flag must carry the machine-readable type."""
        flags = get_risk_flags(1975)
        lead_flags = [f for f in flags if f.flag_type == "lead_paint"]
        assert len(lead_flags) >= 1

    def test_asbestos_flag_has_correct_type(self):
        flags = get_risk_flags(1975)
        asbestos_flags = [f for f in flags if f.flag_type == "asbestos"]
        assert len(asbestos_flags) >= 1

    def test_galvanized_pipe_flag_has_correct_type(self):
        flags = get_risk_flags(1975)
        galv_flags = [f for f in flags if f.flag_type == "galvanized_pipe"]
        assert len(galv_flags) >= 1

    def test_electrical_panel_flag_has_correct_type(self):
        flags = get_risk_flags(1985)
        elec_flags = [f for f in flags if f.flag_type == "electrical_panel"]
        assert len(elec_flags) >= 1

    def test_foundation_flag_has_correct_type(self):
        flags = get_risk_flags(1995)
        found_flags = [f for f in flags if f.flag_type == "foundation"]
        assert len(found_flags) >= 1

    def test_underground_plumbing_flag_has_correct_type(self):
        flags = get_risk_flags(1995)
        up_flags = [f for f in flags if f.flag_type == "underground_plumbing"]
        assert len(up_flags) >= 1

    def test_none_year_has_unknown_age_type(self):
        flags = get_risk_flags(None)
        assert flags[0].flag_type == "unknown_age"

    def test_all_flags_have_non_empty_type(self):
        """Every triggered flag must have a non-empty flag_type."""
        for year in [1950, 1970, 1975, 1980, 1985, 1990, 1995]:
            for flag in get_risk_flags(year):
                assert flag.flag_type != "", (
                    f"flag_type empty for year={year}, message={flag.message!r}"
                )

    # -------------------------------------------------------------------------
    # recommended_action tests (Sub-AC 5b: actionable guidance)
    # -------------------------------------------------------------------------

    def test_all_flags_have_recommended_action(self):
        """Every triggered flag must include a recommended action."""
        for year in [1950, 1970, 1975, 1980, 1985, 1990, 1995]:
            for flag in get_risk_flags(year):
                assert flag.recommended_action, (
                    f"recommended_action empty for year={year}, type={flag.flag_type!r}"
                )

    def test_none_year_has_recommended_action(self):
        flags = get_risk_flags(None)
        assert flags[0].recommended_action

    def test_lead_paint_action_mentions_test(self):
        """Lead paint action should reference testing, not just abatement."""
        flags = get_risk_flags(1975)
        lead = next(f for f in flags if f.flag_type == "lead_paint")
        assert "test" in lead.recommended_action.lower()

    def test_asbestos_action_mentions_inspection(self):
        flags = get_risk_flags(1975)
        asb = next(f for f in flags if f.flag_type == "asbestos")
        assert "inspect" in asb.recommended_action.lower() or "abatement" in asb.recommended_action.lower()

    def test_electrical_action_mentions_panel(self):
        flags = get_risk_flags(1985)
        elec = next(f for f in flags if f.flag_type == "electrical_panel")
        assert "panel" in elec.recommended_action.lower()

    def test_foundation_action_mentions_engineer(self):
        flags = get_risk_flags(1995)
        found = next(f for f in flags if f.flag_type == "foundation")
        assert "engineer" in found.recommended_action.lower()

    def test_recommended_actions_contain_cost_guidance(self):
        """At least one action for old buildings should include a dollar amount."""
        flags = get_risk_flags(1975)
        actions_with_dollars = [f for f in flags if "$" in f.recommended_action]
        assert len(actions_with_dollars) >= 1, "Expected cost guidance ($) in at least one recommended_action"

    # -------------------------------------------------------------------------
    # Severity threshold correctness
    # -------------------------------------------------------------------------

    def test_1986_electrical_flag_is_warning_not_critical(self):
        """1986 is post-1985; electrical flag triggered by [0, 1990] is warning."""
        flags = get_risk_flags(1986)
        elec = next((f for f in flags if f.flag_type == "electrical_panel"), None)
        assert elec is not None
        assert elec.severity == "warning"

    def test_1978_pre_cutoff_is_critical(self):
        """1978 hits the [0, 1978] lead/asbestos band — must be critical."""
        flags = get_risk_flags(1978)
        lead = next((f for f in flags if f.flag_type == "lead_paint"), None)
        assert lead is not None
        assert lead.severity == "critical"

    def test_1979_post_lead_cutoff_has_no_lead_flag(self):
        """1979 is outside [0, 1978]; no lead paint flag expected."""
        flags = get_risk_flags(1979)
        lead_flags = [f for f in flags if f.flag_type == "lead_paint"]
        assert len(lead_flags) == 0
