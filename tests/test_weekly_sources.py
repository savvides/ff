from datetime import datetime, timezone
from copy import deepcopy

import pytest
import responses

from ff.contracts import Roster
from ff.services.weekly import game_facts, build_weekly, load_weekly, SCHEDULE, SCOREBOARD
from ff.sleeper import SleeperClient, build_rosters


def payloads(status="STATUS_SCHEDULED", state="pre", complete=False, sleeper="pre_game"):
    schedule = [{"home": "WAS", "away": "LAR", "week": 3, "status": sleeper}]
    board = {"season": {"year": 2026, "type": 2}, "week": {"number": 3}, "events": [
        {"competitions": [{"date": "2026-09-27T17:00Z", "competitors": [
            {"team": {"abbreviation": "WSH"}}, {"team": {"abbreviation": "LAR"}}],
            "status": {"type": {"name": status, "state": state, "completed": complete}}}]}]}
    return schedule, board


def test_schedule_cross_checks_teams_and_utc_kickoff():
    games = game_facts(*payloads(), "2026", 3)
    assert games["WAS"] == ("scheduled", datetime(2026, 9, 27, 17, tzinfo=timezone.utc))


@pytest.mark.parametrize("status,state,complete,sleeper,expected", [
    ("STATUS_FINAL", "post", True, "complete", "final"),
    ("STATUS_IN_PROGRESS", "in", False, "in_progress", "live"),
    ("STATUS_POSTPONED", "pre", False, "pre_game", "unknown"),
    ("STATUS_SUSPENDED", "post", False, "in_progress", "unknown"),
    ("STATUS_FINAL", "post", True, "pre_game", "unknown"),
])
def test_nonstandard_and_conflicting_statuses_do_not_guess(status, state, complete, sleeper, expected):
    assert game_facts(*payloads(status, state, complete, sleeper), "2026", 3)["WAS"][0] == expected


def test_wrong_week_and_missing_pair_refuse():
    s, b = payloads()
    with pytest.raises(ValueError, match="season/week"):
        game_facts(s, b, "2026", 4)
    b["events"] = []
    with pytest.raises(ValueError, match="disagree"):
        game_facts(s, b, "2026", 3)


def test_empty_starters_survive_loading():
    roster = build_rosters([{"roster_id": 1, "starters": [None, "a", "0"]}], [])[0]
    assert roster.starters == ["0", "a", "0"]


@responses.activate
def test_live_loader_refreshes_status_and_uses_matchup_actual_zero():
    s, b = payloads("STATUS_FINAL", "post", True, "complete")
    responses.get(f"{SCHEDULE}/2026", json=s)
    responses.get(SCOREBOARD, json=b)
    responses.get("https://api.sleeper.com/players/nfl/a", json={"player_id": "a", "team": "WAS", "injury_status": "Out"})
    responses.get("https://api.sleeper.app/v1/league/L/matchups/3", json=[
        {"roster_id": 1, "starters": ["a"], "players_points": {"a": 0}}])
    roster = Roster(roster_id=1, player_ids=["a"], starters=["a"])
    context, meta = load_weekly(SleeperClient(), "L", roster, "2026", 3,
                                {"roster_positions": ["WR"]}, {"a": {"injury_status": None}})
    assert context.players["a"].actual == 0
    assert context.players["a"].injury_status == meta["a"]["injury_status"] == "Out"
    assert context.players["a"].game_status == "final"
    assert context.as_of.tzinfo


def test_invalid_ir_and_autosubs_block_actionable_advice():
    roster = Roster(roster_id=1, player_ids=["a"], starters=[], reserve=["a"])
    args = (roster, {"a": {"team": "WAS", "injury_status": None}}, {}, {"starters": []})
    context = build_weekly(*args, {}, ["WR"], datetime.now(timezone.utc))
    assert "IR eligibility" in context.blocked_reason
    roster.reserve = []
    context = build_weekly(*args, {"max_subs": 1}, ["WR"], datetime.now(timezone.utc))
    assert "AutoSubs" in context.blocked_reason


def test_snapshot_disagreement_requires_refresh():
    with pytest.raises(ValueError, match="disagree"):
        build_weekly(Roster(roster_id=1, starters=["a"]), {}, {}, {"starters": ["b"]}, {}, ["WR"], datetime.now(timezone.utc))


@responses.activate
def test_fresh_projection_snapshot_rejects_wrong_week_and_keeps_injury_evidence():
    from ff.projections import ProjectionsClient
    import re
    url = re.compile(r"https://api.sleeper.com/projections/nfl/2026/3.*")
    entry = {"player_id": "a", "season": "2026", "week": 2, "stats": {"rec": 10},
             "player": {"position": "WR", "team": "WAS", "injury_status": "Questionable"}}
    responses.get(url, json=[entry])
    with pytest.raises(ValueError, match="season/week"):
        ProjectionsClient().snapshot("2026", 3, fresh=True)
    entry["week"] = 3
    responses.get(url, json=[entry])
    points, players = ProjectionsClient().snapshot("2026", 3, fresh=True)
    assert points["a"] == {"rec": 10}
    assert players["a"]["injury_status"] == "Questionable"
