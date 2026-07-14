"""Sleeper helpers: format auto-detection and roster building (the part that
makes values correct for the user's league). Plus one mocked client call."""

import responses

from ff.sleeper import SleeperClient, build_rosters, detect_format, team_names


def test_detect_format_superflex_ppr_dynasty(league):
    fmt = detect_format(league)
    assert fmt.superflex is True
    assert fmt.num_qbs == 2
    assert fmt.num_teams == 12
    assert fmt.ppr == 1.0
    assert fmt.is_dynasty is True
    assert fmt.fantasycalc_params() == {
        "isDynasty": "true", "numQbs": "2", "numTeams": "12", "ppr": "1.0"
    }


def test_detect_format_one_qb_half_ppr_redraft():
    league = {
        "total_rosters": 10,
        "roster_positions": ["QB", "RB", "WR", "FLEX", "BN"],
        "scoring_settings": {"rec": 0.5},
        "settings": {"type": 0},
    }
    fmt = detect_format(league)
    assert fmt.superflex is False
    assert fmt.num_qbs == 1
    assert fmt.ppr == 0.5
    assert fmt.is_dynasty is False
    assert fmt.label() == "10-team Redraft 1QB Half-PPR"


def test_fantasycalc_params_track_format():
    from ff.contracts import Format
    sf = Format(superflex=True, num_qbs=2, num_teams=12, ppr=1.0).fantasycalc_params()
    one = Format(superflex=False, num_qbs=1, num_teams=10, ppr=0.5).fantasycalc_params()
    assert sf["numQbs"] == "2" and one["numQbs"] == "1"
    assert sf["numTeams"] == "12" and one["numTeams"] == "10"
    assert sf["ppr"] == "1.0" and one["ppr"] == "0.5"


def test_format_label_shows_tep_when_present():
    from ff.contracts import Format
    assert "+0.5TEP" in Format(superflex=True, num_qbs=2, ppr=0.5, tep=0.5).label()
    assert "TEP" not in Format(ppr=1.0, tep=0.0).label()


def test_team_names_falls_back_to_username(users_raw):
    names = team_names(users_raw)
    assert names["userA"] == "Dynasty Warriors"
    assert names["userC"] == "carol"  # no team_name set


def test_build_rosters(rosters_raw, users_raw):
    rosters = build_rosters(rosters_raw, users_raw)
    r1 = next(r for r in rosters if r.roster_id == 1)
    assert r1.team_name == "Dynasty Warriors"
    assert r1.player_ids == ["7564", "9221", "9999"]
    assert r1.starters == ["7564", "9221"]
    assert r1.wins == 8 and r1.losses == 5
    assert r1.points_for == 1500.45
    # leagues without taxi/IR: those lists default empty
    assert r1.taxi == [] and r1.reserve == []


def test_build_rosters_taxi_and_reserve():
    raw = [{"roster_id": 1, "owner_id": "u",
            "players": ["a", "b", "c", "d"], "starters": ["a"],
            "taxi": ["c", "0"], "reserve": ["d"], "settings": {}}]
    users = [{"user_id": "u", "display_name": "x", "metadata": {}}]
    r = build_rosters(raw, users)[0]
    assert r.taxi == ["c"]          # empty-slot "0" filtered out
    assert r.reserve == ["d"]
    assert r.player_ids == ["a", "b", "c", "d"]  # taxi/IR are subsets of players


@responses.activate
def test_client_get_is_cached(rosters_raw, monkeypatch):
    """One network hit even across two calls (disk cache)."""
    url = "https://api.sleeper.app/v1/league/LG1/rosters"
    responses.add(responses.GET, url, json=rosters_raw, status=200)
    sc = SleeperClient()
    first = sc.rosters("LG1")
    second = sc.rosters("LG1")
    assert first == second == rosters_raw
    assert len(responses.calls) == 1  # second served from cache
