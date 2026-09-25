from datetime import datetime, timedelta, timezone

import pytest

from ff.analysis.weekly_waivers import weekly_waivers
from ff.contracts import Roster
from ff.contracts.models import WeeklyContext, WeeklyPlayer


def run(position=None, limit=20, updates=None, trending=None):
    now = datetime(2026, 9, 27, tzinfo=timezone.utc)
    meta = {"own": {"position": "WR", "full_name": "Own"},
            "rival": {"position": "WR", "full_name": "Rival"},
            "new": {"position": "WR", "full_name": "New"},
            "depth": {"position": "WR", "full_name": "Depth"},
            "rb": {"position": "RB", "full_name": "Runner"},
            "k": {"position": "K", "full_name": "Kicker"}}
    projections = {p: {"rec": n} for p, n in zip(meta, [5, 40, 10, 2, 20, 50])}
    facts = {p: WeeklyPlayer(game_status="scheduled", kickoff=now + timedelta(hours=2)) for p in meta}
    facts.update(updates or {})
    roster = Roster(roster_id=1, player_ids=["own"], starters=["own", "0"])
    return weekly_waivers(roster, [roster, Roster(roster_id=2, player_ids=["rival"])], projections,
                          {"rec": 1}, ["WR", "RB", "BN"], meta, WeeklyContext(as_of=now, players=facts),
                          "2026", 3, position=position, limit=limit, trending_ids=trending)


def test_full_pool_ranked_by_team_gain_filters_before_limit():
    result = run(position="WR", limit=1)
    assert result.candidates_evaluated == 2
    assert [t.player_id for t in result.targets] == ["new"]
    assert result.targets[0].lineup_gain == 5
    assert result.targets[0].displaced == ["Own"]
    assert result.baseline.total == 5


def test_owned_and_unusable_positions_never_included_and_depth_zero():
    result = run()
    assert [t.player_id for t in result.targets] == ["rb", "new", "depth"]
    assert [t.lineup_gain for t in result.targets] == [20, 5, 0]


@pytest.mark.parametrize("fact", [WeeklyPlayer(), WeeklyPlayer(game_status="final", actual=40),
                                   WeeklyPlayer(game_status="bye"),
                                   WeeklyPlayer(game_status="scheduled", injury_status="Out")])
def test_unverified_started_bye_or_out_candidate_is_excluded(fact):
    assert "new" not in [t.player_id for t in run(updates={"new": fact}).targets]


def test_trending_is_only_a_filter_when_explicit():
    assert [t.player_id for t in run(trending={"depth"}).targets] == ["depth"]
    assert "new" in [t.player_id for t in run().targets]


def test_locked_existing_starter_cannot_be_displaced():
    result = run(position="WR", updates={"own": WeeklyPlayer(game_status="final", actual=0)})
    assert all(t.lineup_gain == 0 for t in result.targets)
    assert result.baseline.slots[0].player_id == "own"
