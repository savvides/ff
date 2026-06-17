"""Lineup scoring + optimal assignment (the start/sit optimizer)."""

from ff.analysis import optimal_lineup, project_points, projected_points
from ff.contracts import Roster

# Half-PPR with a 0.5 TE premium, like the user's league.
SCORING = {
    "rec": 0.5, "rec_yd": 0.1, "rec_td": 6.0, "rush_yd": 0.1, "rush_td": 6.0,
    "pass_yd": 0.04, "pass_td": 4.0, "pass_int": -2.0, "fum_lost": -1.0,
    "bonus_rec_te": 0.5,
}


def test_project_points_half_ppr():
    # WR: 6 rec * 0.5 + 90 yd * 0.1 + 1 td * 6 = 3 + 9 + 6 = 18
    assert project_points({"rec": 6, "rec_yd": 90, "rec_td": 1}, SCORING, "WR") == 18.0


def test_tep_adds_bonus_for_te_only():
    line = {"rec": 6, "rec_yd": 90, "rec_td": 1}
    wr = project_points(line, SCORING, "WR")
    te = project_points(line, SCORING, "TE")
    assert te == wr + 3.0  # 0.5 TEP * 6 receptions


def test_qb_passing_score():
    # 300 yd * 0.04 + 3 td * 4 - 1 int * 2 = 12 + 12 - 2 = 22
    assert project_points({"pass_yd": 300, "pass_td": 3, "pass_int": 1}, SCORING, "QB") == 22.0


def _meta(**pos):
    return {pid: {"position": p, "full_name": pid.upper()} for pid, p in pos.items()}


def test_optimal_lineup_fills_superflex_with_second_qb():
    roster = Roster(roster_id=1,
                    player_ids=["qb1", "qb2", "rb1", "rb2", "wr1", "wr2", "te1"],
                    starters=["qb1", "rb1", "rb2", "wr1", "wr2", "te1", "qb2"])
    proj = {
        "qb1": {"pass_yd": 300, "pass_td": 3},   # 24
        "qb2": {"pass_yd": 250, "pass_td": 2},   # 18
        "rb1": {"rush_yd": 100, "rush_td": 1},   # 16
        "rb2": {"rush_yd": 50},                  # 5
        "wr1": {"rec": 8, "rec_yd": 120, "rec_td": 1},  # 22
        "wr2": {"rec": 4, "rec_yd": 40},         # 6
        "te1": {"rec": 5, "rec_yd": 60},         # 2.5+6 + TEP 2.5 = 11
    }
    meta = _meta(qb1="QB", qb2="QB", rb1="RB", rb2="RB", wr1="WR", wr2="WR", te1="TE")
    positions = ["QB", "RB", "WR", "TE", "FLEX", "SUPER_FLEX", "BN"]
    lu = optimal_lineup(roster, proj, SCORING, positions, meta)
    by_slot = {s.slot: s for s in lu.slots}

    assert by_slot["QB"].player_id == "qb1"
    assert by_slot["SUPER_FLEX"].player_id == "qb2"  # 2nd QB only fits superflex
    assert by_slot["FLEX"].player_id == "wr2"        # best flex-eligible left (6 > rb2's 5)
    assert lu.total == 24 + 16 + 22 + 11 + 6 + 18    # 97
    assert {b.player_id for b in lu.bench} == {"rb2"}  # lowest projection sits


def test_projected_points_map():
    roster = Roster(roster_id=1, player_ids=["wr1"], starters=["wr1"])
    info = projected_points(roster, {"wr1": {"rec": 6, "rec_yd": 90, "rec_td": 1}},
                            SCORING, {"wr1": {"position": "WR", "full_name": "WR One"}})
    assert info["wr1"]["points"] == 18.0
    assert info["wr1"]["name"] == "WR One"
