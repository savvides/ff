"""Unit tests for contract models: depth_chart_order, team, and depth_role."""

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
