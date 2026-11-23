from __future__ import annotations

from datetime import date

from ff.analysis.window import detect_season_phase


def test_detect_season_phase_all_regimes() -> None:
    early = detect_season_phase({"season_type": "regular", "week": 2}, today=date(2026, 9, 15))
    assert early.phase == "in_season_early"
    assert early.label == "Early Season (Wk 1-4)"
    assert early.liquidity_bias == "caution"
    assert early.week == 2
    assert early.season_type == "regular"
    assert early.summary

    peak = detect_season_phase({"season_type": "regular", "week": 8}, today=date(2026, 10, 28))
    assert peak.phase == "in_season_peak"
    assert peak.label == "Peak In-Season (Oct-Nov)"
    assert peak.liquidity_bias == "points_premium"
    assert peak.week == 8

    playoffs_wk15 = detect_season_phase({"season_type": "regular", "week": 15}, today=date(2026, 12, 18))
    assert playoffs_wk15.phase == "playoffs"
    assert playoffs_wk15.label == "Playoff Push / Playoffs"
    assert playoffs_wk15.liquidity_bias == "win_now_lock"

    post = detect_season_phase({"season_type": "post", "week": 1}, today=date(2027, 1, 12))
    assert post.phase == "playoffs"
    assert post.liquidity_bias == "win_now_lock"

    draft_off = detect_season_phase({"season_type": "off", "week": 18}, today=date(2026, 4, 15))
    assert draft_off.phase == "offseason_draft"
    assert draft_off.label == "Offseason Rookie Hype (Mar-May)"
    assert draft_off.liquidity_bias == "picks_premium"

    quiet_off = detect_season_phase({"season_type": "off", "week": 0}, today=date(2026, 7, 10))
    assert quiet_off.phase == "offseason_quiet"
    assert quiet_off.label == "Offseason Liquidity Window"
    assert quiet_off.liquidity_bias == "vet_discount"
    assert quiet_off.week is None

    pre = detect_season_phase({"season_type": "pre", "week": 2}, today=date(2026, 8, 12))
    assert pre.phase == "offseason_quiet"
    assert pre.liquidity_bias == "vet_discount"


def test_detect_season_phase_fallbacks() -> None:
    # Missing season_type with positive week treats as regular season
    inferred = detect_season_phase({"season": "2026", "week": 2, "display_week": 2}, today=date(2026, 4, 1))
    assert inferred.phase == "in_season_early"
    assert inferred.season_type == "regular"

    # Empty/partial state (like conftest FakeSleeper.state) falls back to today.month
    assert detect_season_phase({"season": "2026"}, today=date(2026, 4, 1)).phase == "offseason_draft"
    assert detect_season_phase(None, today=date(2026, 9, 10)).phase == "in_season_early"
    assert detect_season_phase({}, today=date(2026, 11, 1)).phase == "in_season_peak"
    assert detect_season_phase({}, today=date(2026, 12, 15)).phase == "playoffs"
    assert detect_season_phase({}, today=date(2026, 7, 1)).phase == "offseason_quiet"


def test_detect_season_phase_boundaries() -> None:
    assert detect_season_phase({"season_type": "regular", "week": 4}).phase == "in_season_early"
    assert detect_season_phase({"season_type": "regular", "week": 5}).phase == "in_season_peak"
    assert detect_season_phase({"season_type": "regular", "week": 13}).phase == "in_season_peak"
    assert detect_season_phase({"season_type": "regular", "week": 14}).phase == "playoffs"
    assert detect_season_phase({"season_type": "off"}, today=date(2026, 3, 1)).phase == "offseason_draft"
    assert detect_season_phase({"season_type": "off"}, today=date(2026, 5, 31)).phase == "offseason_draft"
    assert detect_season_phase({"season_type": "off"}, today=date(2026, 2, 15)).phase == "offseason_quiet"
    assert detect_season_phase({"season_type": "off"}, today=date(2026, 6, 1)).phase == "offseason_quiet"
    assert detect_season_phase({}, today=date(2026, 1, 15)).phase == "offseason_quiet"
    assert detect_season_phase({}, today=date(2026, 5, 10)).phase == "offseason_draft"
    assert detect_season_phase({}, today=date(2026, 8, 20)).phase == "offseason_quiet"
    assert detect_season_phase({}, today=date(2026, 10, 5)).phase == "in_season_peak"
