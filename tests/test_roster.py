"""Roster valuation math."""

from ff.analysis import value_all_rosters, value_roster
from ff.sleeper import build_rosters


def test_value_roster_totals_and_unvalued(book, rosters_raw, users_raw, players_meta):
    rosters = build_rosters(rosters_raw, users_raw)
    r1 = next(r for r in rosters if r.roster_id == 1)
    val = value_roster(r1, book, players_meta)

    assert val.total_value == 17500          # Chase 9500 + Gibbs 8000 + kicker 0
    assert val.starters_value == 17500       # both stars are starters
    assert val.by_position["WR"] == 9500
    assert val.by_position["RB"] == 8000
    assert val.unvalued == ["9999"]
    # assets sorted by value desc
    assert [a.name for a in val.assets[:2]] == ["Ja'Marr Chase", "Jahmyr Gibbs"]


def test_unvalued_player_name_from_meta(book, rosters_raw, users_raw, players_meta):
    rosters = build_rosters(rosters_raw, users_raw)
    r1 = next(r for r in rosters if r.roster_id == 1)
    val = value_roster(r1, book, players_meta)
    kicker = next(a for a in val.assets if a.id == "9999")
    assert kicker.name == "Test Kicker"
    assert kicker.value == 0


def test_power_rankings_order(book, rosters_raw, users_raw, players_meta):
    rosters = build_rosters(rosters_raw, users_raw)
    valuations = value_all_rosters(rosters, book, players_meta)
    # Gridiron Kings (22000) > Dynasty Warriors (17500) > carol (0)
    assert [v.team_name for v in valuations] == [
        "Gridiron Kings", "Dynasty Warriors", "carol",
    ]
    assert valuations[0].power_rank == 1
    assert valuations[0].total_value == 22000
    assert valuations[-1].power_rank == 3


def test_value_roster_enriches_injury_and_depth(book, rosters_raw, users_raw):
    players_meta = {
        "7564": {"full_name": "Ja'Marr Chase", "position": "WR", "team": "CIN", "depth_chart_order": 1},
        "9221": {"full_name": "Jahmyr Gibbs", "position": "RB", "team": "DET", "depth_chart_order": 2, "injury_status": "Questionable", "injury_body_part": "Hamstring"},
        "9999": {"full_name": "Test Kicker", "position": "K", "team": "DET", "depth_chart_order": 1},
    }
    rosters = build_rosters(rosters_raw, users_raw)
    r1 = next(r for r in rosters if r.roster_id == 1)
    val = value_roster(r1, book, players_meta)

    chase = next(a for a in val.assets if a.id == "7564")
    assert chase.depth_chart_order == 1
    assert chase.depth_tag == "WR1"
    assert chase.injury_tag == ""

    gibbs = next(a for a in val.assets if a.id == "9221")
    assert gibbs.depth_chart_order == 2
    assert gibbs.depth_tag == "RB2"
    assert gibbs.injury_tag == "[Q - Hamstring]"
    assert gibbs.status_label == "RB2 [Q - Hamstring]"
