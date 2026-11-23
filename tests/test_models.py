"""Unit tests for contract models: depth_chart_order, team, and depth_role."""

from __future__ import annotations

from ff.contracts import Asset, RosterSlot, WaiverTarget


def test_roster_slot_depth_role():
    slot_qb2 = RosterSlot(
        player_id="1", name="Jalon Daniels", position="QB", team="TB", depth_chart_order=2
    )
    assert slot_qb2.depth_role == "QB2"

    slot_fa = RosterSlot(
        player_id="2", name="Tyreek Hill", position="WR", team=None, depth_chart_order=None
    )
    assert slot_fa.depth_role == "FA"

    slot_none_team = RosterSlot(
        player_id="3", name="Old Player", position="RB", team="None", depth_chart_order=1
    )
    assert slot_none_team.depth_role == "FA"

    slot_no_order = RosterSlot(
        player_id="4", name="Rookie", position="WR", team="CHI", depth_chart_order=None
    )
    assert slot_no_order.depth_role == "WR"


def test_asset_depth_role():
    a_qb1 = Asset(id="1", name="Patrick Mahomes", position="QB", team="KC", depth_chart_order=1)
    assert a_qb1.depth_role == "QB1"

    a_pick = Asset(id="p1", name="2026 1st", kind="pick", position="PICK")
    assert a_pick.depth_role == "PICK"

    a_fa = Asset(id="2", name="Free Agent", position="WR", team="FA")
    assert a_fa.depth_role == "FA"

    a_none_team = Asset(id="2b", name="Free Agent 2", position="WR", team="None")
    assert a_none_team.depth_role == "FA"

    a_no_order = Asset(id="3", name="Rookie", position="RB", team="DAL", depth_chart_order=None)
    assert a_no_order.depth_role == "RB"


def test_waiver_target_depth_role():
    asset = Asset(id="1", name="Jalon Daniels", position="QB", team="TB", depth_chart_order=2)
    wt = WaiverTarget(asset=asset, team="TB", depth_chart_order=2)
    assert wt.depth_role == "QB2"

    wt_from_asset = WaiverTarget(asset=asset)
    assert wt_from_asset.depth_role == "QB2"

    fa_asset = Asset(id="2", name="Free Agent", position="WR", team=None)
    wt_fa = WaiverTarget(asset=fa_asset)
    assert wt_fa.depth_role == "FA"


def test_asset_fill_from_meta_depth_chart_order():
    a = Asset(id="1", name="Test Player", position="RB")
    assert a.depth_chart_order is None
    a.fill_from_meta({"depth_chart_order": 2, "team": "DET"})
    assert a.depth_chart_order == 2
    assert a.team == "DET"
    assert a.depth_role == "RB2"


def test_window_contracts_and_roster_max_pf_default():
    from ff.contracts import (
        AssetDurationFlag,
        DecisionFilter,
        Roster,
        SeasonPhase,
        TeamWindow,
    )

    r = Roster(roster_id=1)
    assert r.max_pf == 0.0
    sp = SeasonPhase(
        phase="in_season_peak",
        label="Peak In-Season (Oct-Nov)",
        liquidity_bias="points_premium",
        week=8,
        season_type="regular",
        summary="Contenders pay a premium for points.",
    )
    flag = AssetDurationFlag(
        player_id="9221",
        name="Vet RB",
        position="RB",
        age=27.0,
        value=3000,
        kind="RB_OFFSEASON_DECAY",
        severity="HIGH",
        reason="Aging RB held in offseason.",
    )
    flt = DecisionFilter(name="Duration", signal="ALIGNED", summary="Fits contender window.")
    tw = TeamWindow(
        roster_id=1,
        team_name="Warriors",
        diagnosed="CONTEND",
        effective_target="contend",
        target_source="auto",
        win_now_score=90.0,
        win_now_rank=1,
        future_score=60.0,
        future_rank=5,
        starter_win_now_value=45000,
        max_pf=1520.5,
        dynasty_player_value=50000,
        pick_value=6000,
        season_phase=sp,
        flags=[flag],
    )
    assert tw.flags[0].severity == "HIGH"
    assert flt.signal == "ALIGNED"
