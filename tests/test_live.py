"""Live API contract checks - excluded from the gate suite (they hit the real
Sleeper + FantasyCalc APIs). Run on demand with `pytest -m live` to confirm the
upstream payload shapes haven't drifted.
"""

import pytest

from ff.contracts import Format
from ff.sleeper import SleeperClient
from ff.values import ValuesClient

pytestmark = pytest.mark.live


def test_fantasycalc_live_has_players_and_picks():
    book = ValuesClient().fetch(Format(superflex=True, num_qbs=2, num_teams=12, ppr=1.0))
    assert len(book.by_sleeper_id) > 100   # real player pool
    assert len(book.picks) > 10            # real draft picks
    # a star resolves by name and carries a positive value + rank
    star = book.resolve("Jahmyr Gibbs")
    assert star is not None and star.value > 0 and star.overall_rank


def test_fantasycalc_values_actually_track_format():
    # Superflex must value QBs far higher than 1QB. If FantasyCalc silently
    # ignored numQbs, these would be equal - exactly the regression to catch.
    one = ValuesClient().fetch(Format(superflex=False, num_qbs=1, num_teams=12, ppr=1.0))
    sf = ValuesClient().fetch(Format(superflex=True, num_qbs=2, num_teams=12, ppr=1.0))
    qb_one = one.resolve("Josh Allen")
    qb_sf = sf.resolve("Josh Allen")
    assert qb_one and qb_sf
    assert qb_sf.value > qb_one.value


def test_sleeper_live_trending_and_state():
    sc = SleeperClient()
    state = sc.state()
    assert state.get("season")
    trending = sc.trending(kind="add", limit=5)
    assert trending and "player_id" in trending[0]


def test_sleeper_draft_endpoints_live_have_expected_shape():
    # Shape canary for the four draft endpoints `ff draft` depends on. Anchored on
    # a real league id (drafts persist after completion), like the projections test
    # anchors on 2025 wk1. Asserts shape, not values.
    sc = SleeperClient()
    league_id = "1366910390553804800"
    drafts = sc.drafts(league_id)
    assert isinstance(drafts, list) and drafts and "draft_id" in drafts[0]

    did = drafts[0]["draft_id"]
    detail = sc.draft(did)
    # slot_to_roster_id is returned by the single-draft endpoint - the reason the
    # command must fetch detail rather than rely on the drafts list. Guard it.
    assert detail.get("slot_to_roster_id")
    assert (detail.get("settings") or {}).get("rounds")

    picks = sc.draft_picks(did)
    assert isinstance(picks, list)
    if picks:
        assert {"pick_no", "metadata", "roster_id"} <= set(picks[0])

    traded = sc.draft_traded_picks(did)
    assert isinstance(traded, list)
    if traded:
        assert {"round", "roster_id", "owner_id"} <= set(traded[0])


def test_sleeper_projections_live_have_stat_lines():
    from ff.projections import ProjectionsClient
    proj = ProjectionsClient().week("2025", 1)
    assert len(proj) > 100
    allen = proj.get("4984")  # Josh Allen's sleeper id
    assert allen and (allen.get("pass_yd") or allen.get("pts_half_ppr"))
