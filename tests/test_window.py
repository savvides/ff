from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

import pytest

from ff.analysis.roster import value_all_rosters
from ff.analysis.window import analyze_league_windows, detect_season_phase, evaluate_trade_filters
from ff.contracts import Asset, FuturePick, Roster, SeasonPhase, TeamPicks, TeamWindow, TradeEvaluation, TradeSide
from ff.values import ValueBook


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


STANDARD_SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "BN", "IR", "TAXI"]


def _player(
    pid: str,
    name: str,
    pos: str,
    value: int,
    *,
    redraft: Optional[int] = None,
    age: Optional[float] = 24.0,
    depth_chart_order: Optional[int] = 1,
    status: Optional[str] = "Active",
    injury_status: Optional[str] = None,
) -> Asset:
    return Asset(
        id=pid,
        name=name,
        position=pos,
        value=value,
        redraft_value=value if redraft is None else redraft,
        age=age,
        depth_chart_order=depth_chart_order,
        status=status,
        injury_status=injury_status,
    )


def _core_lineup(prefix: str, base_redraft: int, base_dynasty: Optional[int] = None) -> List[Asset]:
    dyn = base_redraft if base_dynasty is None else base_dynasty
    specs = [
        ("qb1", "QB", 1.0),
        ("qb2", "QB", 0.7),
        ("rb1", "RB", 0.9),
        ("rb2", "RB", 0.8),
        ("wr1", "WR", 1.0),
        ("wr2", "WR", 0.85),
        ("wr3", "WR", 0.75),
        ("te1", "TE", 0.65),
    ]
    return [
        _player(
            f"{prefix}_{suffix}",
            f"{prefix.upper()} {suffix}",
            pos,
            max(100, int(dyn * mult)),
            redraft=max(100, int(base_redraft * mult)),
            age=25.0,
        )
        for suffix, pos, mult in specs
    ]


def _pick_capital(roster_id: int, team_name: str, total_value: int) -> TeamPicks:
    if total_value <= 0:
        return TeamPicks(roster_id=roster_id, team_name=team_name, picks=[])
    return TeamPicks(
        roster_id=roster_id,
        team_name=team_name,
        picks=[
            FuturePick(
                season="2027",
                round=1,
                original_roster_id=roster_id,
                original_team=team_name,
                value=total_value,
            )
        ],
    )


def test_analyze_league_windows_12_team_cutoffs_and_middle_trap() -> None:
    assets: List[Asset] = []
    rosters: List[Roster] = []
    ledger: List[TeamPicks] = []
    for i in range(1, 13):
        team_assets = _core_lineup(
            f"t{i}",
            base_redraft=(13 - i) * 1000,
            base_dynasty=i * 800,
        )
        assets.extend(team_assets)
        rosters.append(
            Roster(
                roster_id=i,
                team_name=f"Team {i}",
                player_ids=[a.id for a in team_assets],
                wins=13 - i,
                losses=i - 1,
                max_pf=float((13 - i) * 150 + 1000),
            )
        )
        # Rank 4 gets above-median picks (8000); ranks 5 and 8 get below-median picks (1000).
        pick_val = 8000 if i == 4 else (1000 if i in (5, 8) else 3000)
        ledger.append(_pick_capital(i, f"Team {i}", pick_val))

    book = ValueBook(assets)
    valuations = value_all_rosters(rosters, book)
    phase = SeasonPhase(
        phase="in_season_peak",
        label="Peak In-Season (Oct-Nov)",
        liquidity_bias="points_premium",
        week=8,
        season_type="regular",
        summary="Peak season",
    )

    windows = analyze_league_windows(
        rosters,
        valuations,
        book,
        STANDARD_SLOTS,
        season_phase=phase,
        pick_ledger=ledger,
    )

    assert len(windows) == 12
    counts = {"CONTEND": 0, "MIDDLE_TRAP": 0, "REBUILD": 0}
    for w in windows:
        counts[w.diagnosed] += 1
        assert 0.0 <= w.win_now_score <= 100.0
        assert 0.0 <= w.future_score <= 100.0

    assert counts == {"CONTEND": 3, "MIDDLE_TRAP": 6, "REBUILD": 3}
    assert sorted(w.win_now_rank for w in windows) == list(range(1, 13))
    assert sorted(w.future_rank for w in windows) == list(range(1, 13))

    by_id = {w.roster_id: w for w in windows}
    assert by_id[4].diagnosed == "MIDDLE_TRAP"
    assert by_id[4].win_now_rank == 4
    assert by_id[4].pivot_lean == "PIVOT_CONTEND"
    assert by_id[4].pivot_reason

    assert by_id[5].diagnosed == "MIDDLE_TRAP"
    assert by_id[5].win_now_rank == 5
    assert by_id[5].pivot_lean == "PIVOT_REBUILD"
    assert by_id[5].pivot_reason

    assert by_id[8].diagnosed == "MIDDLE_TRAP"
    assert by_id[8].win_now_rank == 8
    assert by_id[8].pivot_lean == "PIVOT_REBUILD"
    assert by_id[8].pivot_reason

    for rid in (1, 2, 3, 10, 11, 12):
        assert by_id[rid].pivot_lean is None
        assert by_id[rid].pivot_reason is None

    # Verify N = 2 returns 1 CONTEND and 1 REBUILD with zero MIDDLE_TRAP
    two_rosters = rosters[:2]
    two_vals = value_all_rosters(two_rosters, book)
    two_windows = analyze_league_windows(
        two_rosters,
        two_vals,
        book,
        STANDARD_SLOTS,
        season_phase=phase,
    )
    assert [w.diagnosed for w in sorted(two_windows, key=lambda x: x.win_now_rank)] == [
        "CONTEND",
        "REBUILD",
    ]

    # Verify N = 1 single-team league uses 50.0 percentiles and CONTEND
    one_window = analyze_league_windows(
        rosters[:1],
        valuations[:1],
        book,
        STANDARD_SLOTS,
        season_phase=phase,
    )
    assert len(one_window) == 1
    assert one_window[0].diagnosed == "CONTEND"
    assert one_window[0].win_now_score == 50.0
    assert one_window[0].future_score == 50.0


def test_analyze_windows_weighting_and_taxi_ir_exclusion() -> None:
    # 3 teams to isolate percentile weights cleanly:
    # Team 1: highest starters (100%), lowest max_pf (0%), lowest win_pct (0%)
    # Team 2: middle starters (50%), highest max_pf (100%), middle win_pct (50%)
    # Team 3: lowest starters (0%), middle max_pf (50%), highest win_pct (100%)
    t1_active = _core_lineup("a", base_redraft=4000)
    t1_ir = _player("a_ir", "Injured Ace", "WR", 9000, redraft=9000, status="Injured Reserve")
    t1_taxi = _player("a_taxi", "Taxi Stud", "RB", 8000, redraft=8000, age=21.0)
    t1_assets = [*t1_active, t1_ir, t1_taxi]

    t2_assets = _core_lineup("b", base_redraft=2500)
    t3_assets = _core_lineup("c", base_redraft=1000)

    all_assets = [*t1_assets, *t2_assets, *t3_assets]
    book = ValueBook(all_assets)
    rosters = [
        Roster(
            roster_id=1,
            team_name="Team 1",
            player_ids=[a.id for a in t1_assets],
            reserve=[t1_ir.id],
            taxi=[t1_taxi.id],
            wins=0,
            losses=8,
            max_pf=800.0,
        ),
        Roster(
            roster_id=2,
            team_name="Team 2",
            player_ids=[a.id for a in t2_assets],
            wins=4,
            losses=4,
            max_pf=1600.0,
        ),
        Roster(
            roster_id=3,
            team_name="Team 3",
            player_ids=[a.id for a in t3_assets],
            wins=8,
            losses=0,
            max_pf=1200.0,
        ),
    ]
    valuations = value_all_rosters(rosters, book)

    offseason = detect_season_phase({"season_type": "off", "week": 0}, today=date(2026, 7, 1))
    off_win = {
        w.roster_id: w
        for w in analyze_league_windows(rosters, valuations, book, STANDARD_SLOTS, season_phase=offseason)
    }
    # Taxi + IR excluded from starter_win_now_value
    expected_t1_starters = sum(a.redraft_value or 0 for a in t1_active)
    assert off_win[1].starter_win_now_value == expected_t1_starters
    # Offseason weights 100% starter_win_now_value even with nonzero max_pf
    assert off_win[1].win_now_score == pytest.approx(100.0)
    assert off_win[2].win_now_score == pytest.approx(50.0)
    assert off_win[3].win_now_score == pytest.approx(0.0)

    wk2 = detect_season_phase({"season_type": "regular", "week": 2})
    early_win = {
        w.roster_id: w
        for w in analyze_league_windows(rosters, valuations, book, STANDARD_SLOTS, season_phase=wk2)
    }
    assert early_win[1].win_now_score == pytest.approx(0.65 * 100.0 + 0.25 * 0.0 + 0.10 * 0.0)
    assert early_win[2].win_now_score == pytest.approx(0.65 * 50.0 + 0.25 * 100.0 + 0.10 * 50.0)
    assert early_win[3].win_now_score == pytest.approx(0.65 * 0.0 + 0.25 * 50.0 + 0.10 * 100.0)

    wk4 = detect_season_phase({"season_type": "regular", "week": 4})
    wk4_win = {
        w.roster_id: w
        for w in analyze_league_windows(rosters, valuations, book, STANDARD_SLOTS, season_phase=wk4)
    }
    assert wk4_win[1].win_now_score == pytest.approx(0.35 * 100.0 + 0.45 * 0.0 + 0.20 * 0.0)

    wk8 = detect_season_phase({"season_type": "regular", "week": 8})
    peak_win = {
        w.roster_id: w
        for w in analyze_league_windows(rosters, valuations, book, STANDARD_SLOTS, season_phase=wk8)
    }
    assert peak_win[1].win_now_score == pytest.approx(0.35 * 100.0 + 0.45 * 0.0 + 0.20 * 0.0)
    assert peak_win[2].win_now_score == pytest.approx(0.35 * 50.0 + 0.45 * 100.0 + 0.20 * 50.0)
    assert peak_win[3].win_now_score == pytest.approx(0.35 * 0.0 + 0.45 * 50.0 + 0.20 * 100.0)

    # All-zero max_pf in-season degrades to 100% starter_win_now_value
    zero_pf_rosters = [r.model_copy(update={"max_pf": 0.0}) for r in rosters]
    zero_pf_win = {
        w.roster_id: w
        for w in analyze_league_windows(zero_pf_rosters, valuations, book, STANDARD_SLOTS, season_phase=wk8)
    }
    assert zero_pf_win[1].win_now_score == pytest.approx(100.0)
    assert zero_pf_win[3].win_now_score == pytest.approx(0.0)

    # Empty roster_positions falls back to top 9 active assets (still excluding taxi/IR)
    extra_active = [
        _player("a_b1", "Bench 1", "WR", 1500, redraft=1500),
        _player("a_b2", "Bench 2", "RB", 1200, redraft=1200),
        _player("a_b3", "Bench 3", "WR", 500, redraft=500),
    ]
    r1_big_assets = [*t1_active, *extra_active, t1_ir, t1_taxi]
    big_book = ValueBook([*r1_big_assets, *t2_assets, *t3_assets])
    rosters_big = [
        Roster(
            roster_id=1,
            team_name="Team 1",
            player_ids=[a.id for a in r1_big_assets],
            reserve=[t1_ir.id],
            taxi=[t1_taxi.id],
        ),
        rosters[1],
        rosters[2],
    ]
    vals_big = value_all_rosters(rosters_big, big_book)
    fallback_win = {
        w.roster_id: w
        for w in analyze_league_windows(rosters_big, vals_big, big_book, [], season_phase=offseason)
    }
    top9_sum = sum(sorted((a.redraft_value or 0 for a in [*t1_active, *extra_active]), reverse=True)[:9])
    assert fallback_win[1].starter_win_now_value == top9_sum


def test_analyze_windows_target_scoping() -> None:
    assets: List[Asset] = []
    rosters: List[Roster] = []
    for i in range(1, 13):
        team_assets = _core_lineup(f"s{i}", base_redraft=(13 - i) * 1000)
        assets.extend(team_assets)
        rosters.append(
            Roster(
                roster_id=i,
                team_name=f"Team {i}",
                player_ids=[a.id for a in team_assets],
                wins=13 - i,
                losses=i - 1,
                max_pf=float((13 - i) * 100 + 500),
            )
        )
    book = ValueBook(assets)
    valuations = value_all_rosters(rosters, book)
    phase = detect_season_phase({"season_type": "regular", "week": 8})

    # Config override scoped only to target_roster_id=5
    cfg_windows = {
        w.roster_id: w
        for w in analyze_league_windows(
            rosters,
            valuations,
            book,
            STANDARD_SLOTS,
            season_phase=phase,
            window_mode="rebuild",
            mode_override=None,
            target_roster_id=5,
        )
    }
    assert cfg_windows[5].diagnosed == "MIDDLE_TRAP"
    assert cfg_windows[5].effective_target == "rebuild"
    assert cfg_windows[5].target_source == "config"
    for rid, w in cfg_windows.items():
        if rid != 5:
            assert w.target_source == "auto"
            assert w.effective_target == w.diagnosed.lower()

    # Explicit override beats config for target_roster_id=5
    ovr_windows = {
        w.roster_id: w
        for w in analyze_league_windows(
            rosters,
            valuations,
            book,
            STANDARD_SLOTS,
            season_phase=phase,
            window_mode="rebuild",
            mode_override="contend",
            target_roster_id=5,
        )
    }
    assert ovr_windows[5].diagnosed == "MIDDLE_TRAP"
    assert ovr_windows[5].effective_target == "contend"
    assert ovr_windows[5].target_source == "override"
    for rid, w in ovr_windows.items():
        if rid != 5:
            assert w.target_source == "auto"

    # Explicit mode_override="auto" reverts target_roster_id=5 to live diagnosed
    auto_windows = {
        w.roster_id: w
        for w in analyze_league_windows(
            rosters,
            valuations,
            book,
            STANDARD_SLOTS,
            season_phase=phase,
            window_mode="rebuild",
            mode_override="auto",
            target_roster_id=5,
        )
    }
    assert auto_windows[5].diagnosed == "MIDDLE_TRAP"
    assert auto_windows[5].effective_target == "middle_trap"
    assert auto_windows[5].target_source == "auto"
    for rid, w in auto_windows.items():
        if rid != 5:
            assert w.target_source == "auto"


def test_analyze_windows_roster_duration_and_rb_flags() -> None:
    # Two-team league: Team 1 = CONTEND (high starters/max_pf), Team 2 = REBUILD (low starters/max_pf)
    contend_assets = [
        _player("c_qb1", "Contend QB", "QB", 6000, redraft=6000, age=26.0),
        _player("c_rb1", "Aging Contender RB", "RB", 3000, redraft=3600, age=28.0),
        _player("c_rb2", "Young RB1", "RB", 5000, redraft=5000, age=23.0),
        _player("c_wr1", "Contend WR1", "WR", 7000, redraft=7000, age=25.0),
        _player("c_wr2", "Contend WR2", "WR", 5500, redraft=5500, age=25.0),
        _player("c_te1", "Contend TE", "TE", 4000, redraft=4000, age=26.0),
        _player("c_flex", "Contend Flex", "WR", 4500, redraft=4500, age=25.0),
        _player("c_sflex", "Contend SF", "QB", 5000, redraft=5000, age=27.0),
        # Bench / IR young non-starter with +60% gap -> TRADEABLE_LIQUIDITY (INFO)
        _player("c_stash", "Young Stash WR", "WR", 3200, redraft=2000, age=22.0),
        # IR-designated valuable asset -> TRADEABLE_LIQUIDITY (INFO)
        _player("c_ir_star", "Injured Star WR", "WR", 4000, redraft=4000, age=24.0, status="Injured Reserve"),
    ]
    rebuild_assets = [
        # Non-QB starter vet with <= -20% gap -> SELL_POINTS (HIGH)
        _player("r_wr1", "Vet Starter WR", "WR", 2000, redraft=3000, age=29.0),
        # Non-QB bench vet with <= -20% gap -> SELL_POINTS (MODERATE)
        _player("r_wr_bench", "Vet Bench WR", "WR", 1500, redraft=2200, age=28.0),
        # QB vet with <= -20% gap must NOT get SELL_POINTS
        _player("r_qb1", "Vet QB", "QB", 2000, redraft=3200, age=34.0),
        # Age-27 RB worth 3000 -> RB_OFFSEASON_DECAY (offseason) / RB_WINDOW_MISMATCH (in-season)
        _player("r_rb1", "Aging Rebuilder RB", "RB", 3000, redraft=3500, age=27.0),
        # Active bench RB2 backup -> RB_CALL_OPTION (INFO)
        _player("r_rb_bkp", "Backup RB2", "RB", 900, redraft=900, age=23.0, depth_chart_order=2),
        # Taxi RB2 backup must NOT get RB_CALL_OPTION
        _player("r_rb_taxi", "Taxi RB2", "RB", 800, redraft=800, age=21.0, depth_chart_order=2),
        # Filler starters so r_wr_bench and r_rb_bkp stay on the bench
        _player("r_qb2", "Mid QB2", "QB", 2300, redraft=2300, age=25.0),
        _player("r_rb2", "Mid RB2", "RB", 1800, redraft=1800, age=24.0),
        _player("r_wr2", "Mid WR2", "WR", 2600, redraft=2600, age=23.0),
        _player("r_wr3", "Mid WR3", "WR", 2400, redraft=2400, age=23.0),
        _player("r_te1", "Mid TE", "TE", 1200, redraft=1200, age=24.0),
    ]

    all_assets = [*contend_assets, *rebuild_assets]
    book = ValueBook(all_assets)
    rosters = [
        Roster(
            roster_id=1,
            team_name="Contender",
            player_ids=[a.id for a in contend_assets],
            reserve=["c_ir_star"],
            wins=8,
            losses=0,
            max_pf=1500.0,
        ),
        Roster(
            roster_id=2,
            team_name="Rebuilder",
            player_ids=[a.id for a in rebuild_assets],
            taxi=["r_rb_taxi"],
            wins=1,
            losses=7,
            max_pf=900.0,
        ),
    ]
    valuations = value_all_rosters(rosters, book)

    # 1. Offseason check: aging RB triggers RB_OFFSEASON_DECAY (HIGH), not SELL_POINTS
    offseason = detect_season_phase({"season_type": "off"}, today=date(2026, 7, 15))
    off_by_id = {
        w.roster_id: w
        for w in analyze_league_windows(rosters, valuations, book, STANDARD_SLOTS, season_phase=offseason)
    }
    reb_off_flags = {(f.player_id, f.kind): f for f in off_by_id[2].flags}
    assert ("r_rb1", "RB_OFFSEASON_DECAY") in reb_off_flags
    assert reb_off_flags[("r_rb1", "RB_OFFSEASON_DECAY")].severity == "HIGH"
    assert ("r_rb1", "SELL_POINTS") not in reb_off_flags

    # 2. In-season check: all expected flags, severities, exclusions, and sorting
    peak = detect_season_phase({"season_type": "regular", "week": 8})
    peak_by_id = {
        w.roster_id: w
        for w in analyze_league_windows(rosters, valuations, book, STANDARD_SLOTS, season_phase=peak)
    }

    contend_flags = {(f.player_id, f.kind): f for f in peak_by_id[1].flags}
    assert ("c_rb1", "RB_CLIFF_WATCH") in contend_flags
    assert contend_flags[("c_rb1", "RB_CLIFF_WATCH")].severity == "MODERATE"
    assert ("c_stash", "TRADEABLE_LIQUIDITY") in contend_flags
    assert contend_flags[("c_stash", "TRADEABLE_LIQUIDITY")].severity == "INFO"
    assert ("c_ir_star", "TRADEABLE_LIQUIDITY") in contend_flags
    assert contend_flags[("c_ir_star", "TRADEABLE_LIQUIDITY")].severity == "INFO"

    reb_flags = {(f.player_id, f.kind): f for f in peak_by_id[2].flags}
    assert ("r_rb1", "RB_WINDOW_MISMATCH") in reb_flags
    assert reb_flags[("r_rb1", "RB_WINDOW_MISMATCH")].severity == "HIGH"
    assert ("r_rb1", "SELL_POINTS") not in reb_flags
    assert ("r_rb_bkp", "RB_CALL_OPTION") in reb_flags
    assert reb_flags[("r_rb_bkp", "RB_CALL_OPTION")].severity == "INFO"
    assert ("r_rb_taxi", "RB_CALL_OPTION") not in reb_flags
    assert ("r_wr1", "SELL_POINTS") in reb_flags
    assert reb_flags[("r_wr1", "SELL_POINTS")].severity == "HIGH"
    assert ("r_wr_bench", "SELL_POINTS") in reb_flags
    assert reb_flags[("r_wr_bench", "SELL_POINTS")].severity == "MODERATE"
    assert ("r_qb1", "SELL_POINTS") not in reb_flags

    # Sorting: HIGH -> MODERATE -> INFO (and -value, name within severity)
    sev_order = {"HIGH": 0, "MODERATE": 1, "INFO": 2}
    for w in peak_by_id.values():
        keys = [(sev_order[f.severity], -f.value, f.name) for f in w.flags]
        assert keys == sorted(keys)

    # 3. Redraft league yields empty flags
    redraft_windows = analyze_league_windows(
        rosters,
        valuations,
        book,
        STANDARD_SLOTS,
        season_phase=peak,
        is_dynasty=False,
    )
    assert all(w.flags == [] for w in redraft_windows)

    # 4. players_meta enriches missing age/depth_chart_order on assets
    meta_asset = Asset(id="r_rb_meta", name="Meta RB2", position="RB", value=900, redraft_value=0)
    meta_book = ValueBook([*contend_assets, *rebuild_assets, meta_asset])
    meta_rosters = [
        rosters[0],
        rosters[1].model_copy(update={"player_ids": [*rosters[1].player_ids, "r_rb_meta"]}),
    ]
    meta_vals = value_all_rosters(meta_rosters, meta_book)
    players_meta: Dict[str, Any] = {
        "r_rb_meta": {"age": 24.0, "depth_chart_order": 2, "status": "Active"},
    }
    meta_windows = {
        w.roster_id: w
        for w in analyze_league_windows(
            meta_rosters,
            meta_vals,
            meta_book,
            STANDARD_SLOTS,
            season_phase=peak,
            players_meta=players_meta,
        )
    }
    meta_flags = {(f.player_id, f.kind): f for f in meta_windows[2].flags}
    assert ("r_rb_meta", "RB_CALL_OPTION") in meta_flags


def _pick(name: str, value: int, *, redraft_value: Optional[int] = 0) -> Asset:
    return Asset(
        id=name.lower(),
        name=name,
        kind="pick",
        position="PICK",
        value=value,
        redraft_value=redraft_value,
    )


def _window(
    effective_target: str,
    season_phase: SeasonPhase,
    *,
    diagnosed: Optional[str] = None,
    pivot_lean: Optional[str] = None,
) -> TeamWindow:
    diag = diagnosed or {"contend": "CONTEND", "rebuild": "REBUILD", "middle_trap": "MIDDLE_TRAP"}[effective_target]
    return TeamWindow(
        roster_id=1,
        team_name="My Team",
        diagnosed=diag,  # type: ignore[arg-type]
        effective_target=effective_target,  # type: ignore[arg-type]
        target_source="auto",
        pivot_lean=pivot_lean,  # type: ignore[arg-type]
        win_now_score=50.0,
        win_now_rank=5,
        future_score=50.0,
        future_rank=5,
        starter_win_now_value=20000,
        season_phase=season_phase,
    )


def _trade(
    get_assets: List[Asset],
    give_assets: List[Asset],
    *,
    is_dynasty: bool = True,
) -> TradeEvaluation:
    return TradeEvaluation(
        side_a=TradeSide(assets=get_assets, adjustment=100, secondary_adjustment=50),
        side_b=TradeSide(assets=give_assets, adjustment=0, secondary_adjustment=0),
        label_a="You get",
        label_b="You give",
        adjusted=True,
        is_dynasty=is_dynasty,
    )


def test_trade_filters_non_mutating_and_redraft_guard() -> None:
    peak = detect_season_phase({"season_type": "regular", "week": 8})
    draft_phase = detect_season_phase({"season_type": "off"}, today=date(2026, 4, 10))
    rb27 = _player("rb27", "Aging RB", "RB", 3000, redraft=3400, age=27.0)
    pick27 = _pick("2027 1st", 3500)
    vet = _player("vet", "Steady WR", "WR", 3500, redraft=3600, age=27.0)

    ev_dyn = _trade([rb27, pick27], [vet], is_dynasty=True)
    win = _window("contend", peak)
    snapshot = ev_dyn.model_dump()
    res_dyn = evaluate_trade_filters(ev_dyn, win, peak)
    assert ev_dyn.model_dump() == snapshot
    assert [f.name for f in res_dyn] == ["Duration", "RB Option Risk", "Seasonal Liquidity"]
    assert all(f.summary for f in res_dyn)

    # Redraft guard: all three filters return N/A
    ev_redraft = _trade([rb27, pick27], [vet], is_dynasty=False)
    res_redraft = evaluate_trade_filters(ev_redraft, win, peak)
    assert [f.name for f in res_redraft] == ["Duration", "RB Option Risk", "Seasonal Liquidity"]
    assert all(f.signal == "N/A" and f.summary for f in res_redraft)

    # team_window=None in dynasty: Duration -> N/A, RB & Seasonal still evaluate
    vet2 = _player("vet2", "Steady WR 2", "WR", 3000, redraft=3200, age=28.0)
    res_no_win_off = evaluate_trade_filters(_trade([pick27, rb27], [vet, vet2]), None, draft_phase)
    by_name_off = {f.name: f for f in res_no_win_off}
    assert by_name_off["Duration"].signal == "N/A"
    assert by_name_off["RB Option Risk"].signal == "MISMATCH"
    assert by_name_off["Seasonal Liquidity"].signal == "HEADWIND"

    # team_window=None in-season: age >= 28 RB -> CAUTION, age 26-27 RB -> NEUTRAL
    rb28 = _player("rb28", "Cliff RB", "RB", 3000, redraft=3400, age=28.0)
    by_name_28 = {f.name: f for f in evaluate_trade_filters(_trade([rb28], [vet]), None, peak)}
    assert by_name_28["Duration"].signal == "N/A"
    assert by_name_28["RB Option Risk"].signal == "CAUTION"

    by_name_27 = {f.name: f for f in evaluate_trade_filters(_trade([rb27], [vet]), None, peak)}
    assert by_name_27["Duration"].signal == "N/A"
    assert by_name_27["RB Option Risk"].signal == "NEUTRAL"


def test_trade_filters_duration_by_window_and_missing_redraft() -> None:
    peak = detect_season_phase({"season_type": "regular", "week": 8})
    contend_win = _window("contend", peak)
    rebuild_win = _window("rebuild", peak)
    mid_win = _window("middle_trap", peak, pivot_lean="PIVOT_CONTEND")

    win_now_vet = _player("v1", "Win Now WR", "WR", 3000, redraft=4200, age=29.0)
    young_wr = _player("y1", "Young WR", "WR", 4500, redraft=2500, age=22.0)
    pick27 = _pick("2027 1st", 3500)
    small_vet_a = _player("sa", "Small A", "WR", 2200, redraft=2400, age=26.0)
    small_vet_b = _player("sb", "Small B", "WR", 2000, redraft=2000, age=26.0)

    # Contender: buying win-now points >= 1000 -> ALIGNED
    f_c_buy = evaluate_trade_filters(_trade([win_now_vet], [young_wr]), contend_win, peak)[0]
    assert f_c_buy.signal == "ALIGNED"

    # Contender: selling points <= -1000 for picks (net_future > 0) -> MISMATCH
    f_c_sell = evaluate_trade_filters(_trade([pick27], [win_now_vet]), contend_win, peak)[0]
    assert f_c_sell.signal == "MISMATCH"

    # Contender: shift < 1000 -> NEUTRAL
    f_c_small = evaluate_trade_filters(_trade([small_vet_a], [small_vet_b]), contend_win, peak)[0]
    assert f_c_small.signal == "NEUTRAL"

    # Rebuilder: buying future >= 1000 with net_win_now <= 0 -> ALIGNED
    f_r_buy_fut = evaluate_trade_filters(_trade([pick27], [win_now_vet]), rebuild_win, peak)[0]
    assert f_r_buy_fut.signal == "ALIGNED"

    # Rebuilder: buying points >= 1000 while losing future (< 0) -> MISMATCH
    f_r_buy_pts = evaluate_trade_filters(_trade([win_now_vet], [pick27]), rebuild_win, peak)[0]
    assert f_r_buy_pts.signal == "MISMATCH"

    # Rebuilder: buying points >= 1000 with net_future >= 0 -> CAUTION
    vet_high_dyn = _player("vhd", "Prime Vet WR", "WR", 5000, redraft=4500, age=26.0)
    cheap_vet = _player("cv", "Cheap Vet WR", "WR", 1500, redraft=1500, age=29.0)
    f_r_caution = evaluate_trade_filters(_trade([vet_high_dyn], [cheap_vet]), rebuild_win, peak)[0]
    assert f_r_caution.signal == "CAUTION"

    # Rebuilder: small shift -> NEUTRAL
    f_r_small = evaluate_trade_filters(_trade([small_vet_a], [small_vet_b]), rebuild_win, peak)[0]
    assert f_r_small.signal == "NEUTRAL"

    # Middle trap: meaningful shift -> CAUTION naming pivot direction
    f_m_contend = evaluate_trade_filters(_trade([win_now_vet], [pick27]), mid_win, peak)[0]
    assert f_m_contend.signal == "CAUTION"
    assert "contend" in f_m_contend.summary.lower()

    f_m_rebuild = evaluate_trade_filters(_trade([pick27], [win_now_vet]), mid_win, peak)[0]
    assert f_m_rebuild.signal == "CAUTION"
    assert "rebuild" in f_m_rebuild.summary.lower()

    f_m_small = evaluate_trade_filters(_trade([small_vet_a], [small_vet_b]), mid_win, peak)[0]
    assert f_m_small.signal == "NEUTRAL"


def test_trade_filters_missing_redraft_rookie_vs_pick() -> None:
    peak = detect_season_phase({"season_type": "regular", "week": 8})
    contend_win = _window("contend", peak)
    rebuild_win = _window("rebuild", peak)

    rookie = Asset(
        id="rk1",
        name="Unredrafted Rookie",
        kind="player",
        position="WR",
        value=4000,
        redraft_value=None,
        age=21.0,
    )
    pick27 = _pick("2027 1st", 3000, redraft_value=0)
    depth = Asset(
        id="dp1",
        name="Depth Vet",
        kind="player",
        position="WR",
        value=500,
        redraft_value=500,
        age=27.0,
    )

    # Buying rookie (redraft=None, val=4000) + 2027 1st (3000) for depth (redraft=500):
    # - rookie excluded from win-now (not treated as 4000 fallback) -> net_win_now == -500
    # - rookie name recorded in details
    # - both rookie and pick (+7000) counted in net_future
    ev = _trade([rookie, pick27], [depth])
    dur_contend = evaluate_trade_filters(ev, contend_win, peak)[0]
    assert dur_contend.signal == "NEUTRAL"
    joined_details = " ".join(dur_contend.details)
    assert "Unredrafted Rookie" in joined_details
    assert "+7,000" in joined_details or "+7000" in joined_details
    assert "-500" in joined_details

    dur_rebuild = evaluate_trade_filters(ev, rebuild_win, peak)[0]
    assert dur_rebuild.signal == "ALIGNED"
    assert "Unredrafted Rookie" in " ".join(dur_rebuild.details)

    # Checked against a starter vet (redraft_value=2000): still lists rookie in details and counts +4000 future
    vet = _player("vet2k", "Starter Vet", "WR", 2000, redraft=2000, age=28.0)
    ev_vs_vet = _trade([rookie], [vet])
    dur_vs_vet_reb = evaluate_trade_filters(ev_vs_vet, rebuild_win, peak)[0]
    assert dur_vs_vet_reb.signal == "ALIGNED"
    assert "Unredrafted Rookie" in " ".join(dur_vs_vet_reb.details)
    assert "+4,000" in " ".join(dur_vs_vet_reb.details) or "+4000" in " ".join(dur_vs_vet_reb.details)


def test_trade_filters_rb_option_risk() -> None:
    peak = detect_season_phase({"season_type": "regular", "week": 8})
    off_draft = detect_season_phase({"season_type": "off"}, today=date(2026, 4, 10))
    off_quiet = detect_season_phase({"season_type": "off"}, today=date(2026, 7, 10))

    contend_peak = _window("contend", peak)
    rebuild_peak = _window("rebuild", peak)
    middle_peak = _window("middle_trap", peak, pivot_lean="PIVOT_CONTEND")
    contend_off_draft = _window("contend", off_draft)
    contend_off_quiet = _window("contend", off_quiet)

    rb26 = _player("rb26", "Prime RB26", "RB", 3000, redraft=3300, age=26.0)
    rb27 = _player("rb27", "Aging RB27", "RB", 3000, redraft=3400, age=27.0)
    rb28 = _player("rb28", "Cliff RB28", "RB", 3000, redraft=3500, age=28.0)
    rb2_bkp = _player("rb_bkp", "Backup RB2", "RB", 900, redraft=900, age=23.0, depth_chart_order=2)
    wr = _player("wr1", "Comparable WR", "WR", 3000, redraft=3000, age=24.0)
    wr_other = _player("wr2", "Other WR", "WR", 3000, redraft=3000, age=25.0)

    # Acquiring age-27 RB in offseason_draft -> MISMATCH
    assert evaluate_trade_filters(_trade([rb27], [wr]), contend_off_draft, off_draft)[1].signal == "MISMATCH"
    # Acquiring age-27 RB in-season while rebuilding -> MISMATCH
    assert evaluate_trade_filters(_trade([rb27], [wr]), rebuild_peak, peak)[1].signal == "MISMATCH"
    # Acquiring age-26 RB in-season while contending -> ALIGNED; age-28 -> CAUTION
    assert evaluate_trade_filters(_trade([rb26], [wr]), contend_peak, peak)[1].signal == "ALIGNED"
    assert evaluate_trade_filters(_trade([rb28], [wr]), contend_peak, peak)[1].signal == "CAUTION"
    # Middle trap in-season mirrors contend for RB option risk
    assert evaluate_trade_filters(_trade([rb26], [wr]), middle_peak, peak)[1].signal == "ALIGNED"
    assert evaluate_trade_filters(_trade([rb28], [wr]), middle_peak, peak)[1].signal == "CAUTION"
    # Selling age-27 RB in offseason_quiet or while rebuilding -> TAILWIND
    assert evaluate_trade_filters(_trade([wr], [rb27]), contend_off_quiet, off_quiet)[1].signal == "TAILWIND"
    assert evaluate_trade_filters(_trade([wr], [rb27]), rebuild_peak, peak)[1].signal == "TAILWIND"
    # Acquiring only cheap RB2 backup -> ALIGNED
    assert evaluate_trade_filters(_trade([rb2_bkp], [wr]), rebuild_peak, peak)[1].signal == "ALIGNED"
    # Pure WR swap -> NEUTRAL
    assert evaluate_trade_filters(_trade([wr], [wr_other]), contend_peak, peak)[1].signal == "NEUTRAL"


def test_trade_filters_seasonal_liquidity() -> None:
    peak = detect_season_phase({"season_type": "regular", "week": 8})
    off_draft = detect_season_phase({"season_type": "off"}, today=date(2026, 4, 10))
    early = detect_season_phase({"season_type": "regular", "week": 2})
    playoffs = detect_season_phase({"season_type": "regular", "week": 15})
    off_quiet = detect_season_phase({"season_type": "off"}, today=date(2026, 7, 10))

    healthy_vet = _player("hvet", "Healthy Vet", "WR", 3500, redraft=3800, age=28.0)
    proven_vet = _player("pvet", "Proven Vet", "WR", 3500, redraft=3600, age=27.0)
    ir_star = _player("irstar", "Injured Star", "WR", 5000, redraft=1200, age=25.0, injury_status="IR")
    pick27 = _pick("2027 1st", 3500)
    pick_small = _pick("2027 3rd", 1000)
    small_vet = _player("svet", "Small Vet", "WR", 1200, redraft=1300, age=28.0)

    # in_season_peak (Oct-Nov): sell healthy vet for 2027 1st + IR star -> TAILWIND; reverse -> CAUTION
    assert (
        evaluate_trade_filters(_trade([pick27, ir_star], [healthy_vet]), _window("rebuild", peak), peak)[2].signal
        == "TAILWIND"
    )
    assert (
        evaluate_trade_filters(_trade([healthy_vet], [pick27, ir_star]), _window("contend", peak), peak)[2].signal
        == "CAUTION"
    )
    # Below 1500 threshold -> NEUTRAL
    assert (
        evaluate_trade_filters(_trade([pick_small], [small_vet]), _window("contend", peak), peak)[2].signal
        == "NEUTRAL"
    )

    # offseason_draft (Mar-May): sell 2027 1st for proven vet -> TAILWIND; reverse -> HEADWIND
    assert (
        evaluate_trade_filters(_trade([proven_vet], [pick27]), _window("contend", off_draft), off_draft)[2].signal
        == "TAILWIND"
    )
    assert (
        evaluate_trade_filters(_trade([pick27], [proven_vet]), _window("rebuild", off_draft), off_draft)[2].signal
        == "HEADWIND"
    )
    assert (
        evaluate_trade_filters(_trade([pick_small], [small_vet]), _window("rebuild", off_draft), off_draft)[2].signal
        == "NEUTRAL"
    )

    # Other phases always NEUTRAL
    for phase in (early, playoffs, off_quiet):
        assert (
            evaluate_trade_filters(_trade([pick27], [proven_vet]), _window("contend", phase), phase)[2].signal
            == "NEUTRAL"
        )
        assert (
            evaluate_trade_filters(_trade([proven_vet], [pick27]), _window("contend", phase), phase)[2].signal
            == "NEUTRAL"
        )


def test_trade_filters_seasonal_questionable_and_suspended_players() -> None:
    peak = detect_season_phase({"season_type": "regular", "week": 8})
    healthy_vet = _player("hvet", "Healthy Vet", "WR", 3500, redraft=3800, age=28.0)
    q_star = _player("qstar", "Questionable Star", "WR", 5000, redraft=5000, age=26.0, injury_status="Questionable")
    q_vet = _player("qvet", "Questionable Vet", "WR", 3500, redraft=3800, age=28.0, injury_status="Questionable")
    sus_star = _player("sstar", "Suspended Star", "WR", 4000, redraft=4000, age=25.0, injury_status="Suspended")
    out_star = _player("ostar", "Out Star", "WR", 3500, redraft=2500, age=25.0, injury_status="Out")
    pick27 = _pick("2027 1st", 3500)

    # Questionable star is NOT a discounted injured star (must be NEUTRAL, not TAILWIND)
    assert (
        evaluate_trade_filters(_trade([q_star], [healthy_vet]), _window("rebuild", peak), peak)[2].signal
        == "NEUTRAL"
    )
    # Suspended player is NOT a discounted injured star
    assert (
        evaluate_trade_filters(_trade([sus_star], [healthy_vet]), _window("rebuild", peak), peak)[2].signal
        == "NEUTRAL"
    )
    # Mid-week Questionable vet still counts as active vet points when sold for a 1st (and vice versa)
    assert (
        evaluate_trade_filters(_trade([pick27], [q_vet]), _window("rebuild", peak), peak)[2].signal
        == "TAILWIND"
    )
    assert (
        evaluate_trade_filters(_trade([q_vet], [pick27]), _window("contend", peak), peak)[2].signal
        == "CAUTION"
    )
    # Out star DOES count as a serious injury absence
    assert (
        evaluate_trade_filters(_trade([out_star], [healthy_vet]), _window("rebuild", peak), peak)[2].signal
        == "TAILWIND"
    )


def test_trade_filters_seasonal_mixed_two_sided_net_vet_shift() -> None:
    peak = detect_season_phase({"season_type": "regular", "week": 8})
    off_draft = detect_season_phase({"season_type": "off"}, today=date(2026, 4, 10))

    vet_big = _player("vbig", "Big Vet", "WR", 4500, redraft=4800, age=28.0)
    vet_mid = _player("vmid", "Mid Vet", "WR", 3500, redraft=3600, age=27.0)
    vet_small = _player("vsm", "Small Vet", "WR", 2500, redraft=2800, age=27.0)
    vet_tiny = _player("vtiny", "Tiny Vet", "WR", 2000, redraft=2500, age=27.0)
    pick_1st = _pick("2027 1st", 3500)
    pick_2nd = _pick("2027 2nd", 1500)

    # in_season_peak mixed trade: gaining discounted net +2000 AND gaining net vets +2000 -> NEUTRAL
    # (gross vets_give=2500 >= 1500, but net vets_give - vets_get = -2000)
    ev_peak_mixed_neutral = _trade([vet_big, pick_1st], [vet_small, pick_2nd])
    assert evaluate_trade_filters(ev_peak_mixed_neutral, _window("rebuild", peak), peak)[2].signal == "NEUTRAL"

    # in_season_peak mixed trade with >= 1500 net shift on both discounted and vets -> TAILWIND / CAUTION
    ev_peak_mixed_tailwind = _trade([vet_small, pick_1st], [vet_big, pick_2nd])
    assert evaluate_trade_filters(ev_peak_mixed_tailwind, _window("rebuild", peak), peak)[2].signal == "TAILWIND"
    ev_peak_mixed_caution = _trade([vet_big, pick_2nd], [vet_small, pick_1st])
    assert evaluate_trade_filters(ev_peak_mixed_caution, _window("contend", peak), peak)[2].signal == "CAUTION"

    # offseason_draft mixed trade: net picks_give - picks_get = +2000, gross vets_get=3500 >= 1500,
    # but net vets_get - vets_give = -1000 -> NEUTRAL (not TAILWIND)
    ev_off_mixed_neutral = _trade([vet_mid, pick_2nd], [vet_big, pick_1st])
    assert evaluate_trade_filters(ev_off_mixed_neutral, _window("contend", off_draft), off_draft)[2].signal == "NEUTRAL"

    # offseason_draft mixed trade with >= 1500 net shift on both picks and vets -> TAILWIND / HEADWIND
    ev_off_mixed_tailwind = _trade([vet_big, pick_2nd], [vet_tiny, pick_1st])
    assert evaluate_trade_filters(ev_off_mixed_tailwind, _window("contend", off_draft), off_draft)[2].signal == "TAILWIND"
    ev_off_mixed_headwind = _trade([vet_tiny, pick_1st], [vet_big, pick_2nd])
    assert evaluate_trade_filters(ev_off_mixed_headwind, _window("rebuild", off_draft), off_draft)[2].signal == "HEADWIND"
