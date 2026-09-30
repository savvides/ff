"""Live API contract checks - excluded from the gate suite (they hit the real
Sleeper + FantasyCalc APIs). Run on demand with `pytest -m live` to confirm the
upstream payload shapes haven't drifted.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from ff.cli import _current_week
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


def test_ktc_live_maps_values():
    # Dual-market merge depends on KeepTradeCut returning values for players and picks.
    # If the page structure drifts, secondary market values silently go missing.
    from ff.values.ktc import KtcClient
    client = KtcClient()
    values = client.fetch_values(Format(superflex=True), use_cache=False)
    if not values:
        # Offline is a skip; a page that downloads but parses to nothing is the
        # drift this check exists to catch (it hid KTC's Sept 2026 layout change).
        if not client._fetch_text(use_cache=False):
            pytest.skip("KTC unreachable (offline or blocked)")
        pytest.fail("KTC page downloaded but no values parsed - the page layout changed")
    assert any(" " in k for k in values), "no player/pick name keys in KTC map"
    assert any(v > 0 for v in values.values())
    assert "jahmyr gibbs" in values
    assert values["jahmyr gibbs"] > 0
    assert any(k.startswith("202") for k in values)


def test_weekly_live_schedule_and_fresh_player_contracts():
    from ff.core.http import get_json
    from ff.projections import ProjectionsClient
    from ff.services.weekly import game_facts, SCHEDULE, SCOREBOARD
    sc = SleeperClient()
    state = sc.state()
    season = str(state["season"])
    week = _current_week(state)
    games = game_facts(get_json(f"{SCHEDULE}/{season}", ttl=0),
                       get_json(SCOREBOARD, params={"dates": season, "seasontype": 2, "week": week}, ttl=0),
                       season, week)
    assert games and all(status != "unknown" for status, _ in games.values())
    projections, meta = ProjectionsClient().snapshot(season, week, fresh=True)
    assert len(projections) > 100 and len(meta) > 100
    pid = next(iter(meta))
    player = sc.player(pid)
    assert player["player_id"] == pid and "injury_status" in player
    assert isinstance(sc.player_news(pid), list)


def test_weekly_live_roster_matchup_slot_alignment():
    from ff.sleeper import build_rosters
    league_id = os.environ.get("FF_LIVE_LEAGUE_ID")
    if not league_id:
        pytest.skip("set FF_LIVE_LEAGUE_ID for current roster/matchup alignment")
    sc = SleeperClient()
    state = sc.state()
    week = _current_week(state)
    rosters = build_rosters(sc.rosters(league_id, fresh=True), sc.league_users(league_id))
    matchups = {m["roster_id"]: m for m in sc.matchups(league_id, week)}
    assert matchups
    for roster in rosters:
        matchup = matchups[roster.roster_id]
        assert roster.starters == [str(p) if p else "0" for p in matchup["starters"]]
        assert isinstance(matchup["players_points"], dict)


# --- calculator parity: ff's trade math must equal the sites' own ---------------

REPO = Path(__file__).resolve().parent.parent
LEAGUE_FMT = Format(is_dynasty=True, superflex=True, num_qbs=2, num_teams=12, ppr=0.5, tep=0.5)


def test_calculator_code_unchanged_live():
    # The same check `ff trade` runs: a failure means a site changed its calculator
    # since ff's port was verified; regenerate the vectors and re-verify the port.
    from ff.values.calculators_live import check_calculators
    from ff.values.ktc import KtcClient
    html = KtcClient()._fetch_text(use_cache=False)
    assert check_calculators(html) == []


def test_calculator_vectors_still_match_the_site_code_live():
    if not shutil.which("node"):
        pytest.skip("node not installed")
    res = subprocess.run(["node", str(REPO / "scripts/calculator_oracle.mjs"), "--check",
                          str(REPO / "tests/fixtures/calculator_vectors.json")],
                         capture_output=True, text=True, timeout=300)
    assert res.returncode == 0, res.stdout + res.stderr


def test_trade_numbers_match_the_sites_on_live_data():
    """End to end on today's values: each asset priced as the sites price it (the
    oracle looks values up itself, KTC through the page's own field selection), and
    the sites' own code producing the adjustments and totals ff reports."""
    if not shutil.which("node"):
        pytest.skip("node not installed")
    from ff.analysis import analyze_trade
    book = ValuesClient().fetch(LEAGUE_FMT, fresh=True)
    trades = [  # (ff tokens get, ff tokens give, site names get, site names give)
        (["Quinshon Judkins"], ["Kirk Cousins", "Michael Pittman"],
         [("Quinshon Judkins", "Quinshon Judkins")], [("Kirk Cousins", "Kirk Cousins"), ("Michael Pittman", "Michael Pittman")]),
        (["Kenyon Sadiq"], ["Tee Higgins"], [("Kenyon Sadiq", "Kenyon Sadiq")], [("Tee Higgins", "Tee Higgins")]),
        (["2027 2nd (Early)", "Brock Bowers"], ["Kirk Cousins"],
         [("2027 2nd (Early)", "2027 Early 2nd"), ("Brock Bowers", "Brock Bowers")], [("Kirk Cousins", "Kirk Cousins")]),
    ]
    # Same KTC page snapshot ff priced from: KTC's values move between fetches.
    payload = {"fc_params": LEAGUE_FMT.fantasycalc_params(), "ktc_tep": LEAGUE_FMT.ktc_tep_tier(), "ktc_format": 2,
               "ktc_html": book.secondary_html,
               "trades": [{"side1": [{"fc": f, "ktc": k} for f, k in get_sites],
                           "side2": [{"fc": f, "ktc": k} for f, k in give_sites]}
                          for _, _, get_sites, give_sites in trades]}
    res = subprocess.run(["node", str(REPO / "scripts/calculator_oracle.mjs"), "--eval"],
                         input=json.dumps(payload), capture_output=True, text=True, timeout=300)
    assert res.returncode == 0, res.stderr
    site = json.loads(res.stdout)["results"]
    for (get, give, _, _), s in zip(trades, site):
        ev, missing = analyze_trade(get, give, book)
        assert not missing
        assert [[a.value for a in ev.side_a.assets], [a.value for a in ev.side_b.assets]] == s["fc_values"]
        assert [[a.secondary_value for a in ev.side_a.assets],
                [a.secondary_value for a in ev.side_b.assets]] == s["ktc_values"]
        assert ev.secondary_top == s["ktc_top"]
        assert (ev.value_a, ev.value_b) == (s["fc"]["total1"], s["fc"]["total2"])
        assert (ev.secondary_value_a, ev.secondary_value_b) == (s["ktc"]["total1"], s["ktc"]["total2"])
        assert ev.secondary_is_fair() == s["ktc"]["fair"]


def test_te_premium_reaches_both_markets_live():
    plain = ValuesClient().fetch(Format(is_dynasty=True, superflex=True, num_qbs=2, num_teams=12, ppr=0.5))
    tep = ValuesClient().fetch(LEAGUE_FMT, fresh=True)
    bowers_plain, bowers_tep = plain.resolve("Brock Bowers"), tep.resolve("Brock Bowers")
    assert bowers_tep.value > bowers_plain.value  # FantasyCalc tep=te+
    assert bowers_tep.secondary_value > bowers_plain.secondary_value  # KTC TE+ tier
    assert tep.resolve("Kirk Cousins").value == plain.resolve("Kirk Cousins").value  # non-TEs unchanged
