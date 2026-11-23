from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

import pytest

from ff.analysis.roster import value_all_rosters
from ff.analysis.window import analyze_league_windows, detect_season_phase
from ff.contracts import Asset, FuturePick, Roster, SeasonPhase, TeamPicks
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
