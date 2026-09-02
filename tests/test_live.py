"""Live API contract checks - excluded from the gate suite (they hit the real
Sleeper + FantasyCalc APIs). Run on demand with `pytest -m live` to confirm the
upstream payload shapes haven't drifted.
"""

import os

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


def test_fantasycalc_live_pick_tiers_stay_distinct():
    # `ff picks` and tiered trade input depend on FantasyCalc naming near-season
    # rounds "YYYY 1st (Early)/(Mid)/(Late)". If that naming drifts, the tier keys
    # vanish and every pick silently prices at the flat round value - catch it here.
    book = ValuesClient().fetch(Format(superflex=True, num_qbs=2, num_teams=12, ppr=1.0))
    tiers = [k for k in book.picks if k.endswith((" early", " mid", " late"))]
    assert tiers, "no tiered pick entries - has FantasyCalc renamed its tiers?"
    year = tiers[0].split()[0]
    early = book.picks.get(f"{year} 1 early")
    late = book.picks.get(f"{year} 1 late")
    assert early and late and early.value > late.value
    # the flat round entry must survive alongside the tiers (collision regression)
    assert f"{year} 1" in book.picks


def test_sleeper_live_traded_picks_shape():
    # Shape canary for the endpoint `ff picks` reconciles ownership from.
    league_id = os.environ.get("FF_LIVE_LEAGUE_ID")
    if not league_id:
        pytest.skip("set FF_LIVE_LEAGUE_ID to a real league id to run this")
    traded = SleeperClient().traded_picks(league_id)
    assert isinstance(traded, list)
    if traded:
        assert {"season", "round", "roster_id", "owner_id"} <= set(traded[0])
        assert isinstance(traded[0]["season"], str)  # season is a string, round an int


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
    # a real league whose draft has completed (drafts persist after completion),
    # like the projections test anchors on 2025 wk1. Asserts shape, not values. The
    # id comes from FF_LIVE_LEAGUE_ID so no personal league id lives in the source;
    # set it to any league you can see, e.g. `FF_LIVE_LEAGUE_ID=123 make test-live`.
    league_id = os.environ.get("FF_LIVE_LEAGUE_ID")
    if not league_id:
        pytest.skip("set FF_LIVE_LEAGUE_ID to a real (completed) league id to run this")
    sc = SleeperClient()
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


def test_dealer_live_maps_sleeper_ids():
    # Dual-market merge depends on Dynasty Dealer returning sleeper ids (or pick
    # labels) the dealer client understands. If the payload shape drifts, every
    # `--market both` number silently goes missing.
    from ff.values.dealer import DynastyDealerClient
    values = DynastyDealerClient().fetch_values()
    if not values:
        pytest.skip("Dynasty Dealer returned no values (offline or shape change)")
    assert any(k.isdigit() for k in values), "no sleeper-id keys in Dealer map"
    assert any(v > 0 for v in values.values())

