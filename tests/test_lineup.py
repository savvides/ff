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
    assert project_points({"rec": 6, "rec_yd": 90, "rec_td": 1}, SCORING) == 18.0


def test_tep_comes_from_bonus_stat_key_and_is_not_doubled():
    # Sleeper provides bonus_rec_te as its own stat (= TE reception count); the
    # generic loop applies it exactly once. A manual TEP would double-count.
    base = {"rec": 6, "rec_yd": 90, "rec_td": 1}
    assert project_points(base, SCORING) == 18.0                         # no bonus key, no TEP
    assert project_points({**base, "bonus_rec_te": 6}, SCORING) == 21.0  # +0.5*6, once


def test_qb_passing_score():
    # 300 yd * 0.04 + 3 td * 4 - 1 int * 2 = 12 + 12 - 2 = 22
    assert project_points({"pass_yd": 300, "pass_td": 3, "pass_int": 1}, SCORING) == 22.0


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
        "te1": {"rec": 5, "rec_yd": 60, "bonus_rec_te": 5},  # 2.5+6 + TEP 0.5*5 = 11
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


def test_assign_primitive_is_score_agnostic_and_laminar():
    # The extracted greedy primitive `_assign` is what both lineup (points) and
    # fit (dynasty value) reuse. Drive it with arbitrary scores to prove it fills
    # the most-restrictive slot first and is correct on the laminar slot family.
    from ff.analysis.lineup import _assign

    positions = {"qb1": "QB", "qb2": "QB", "wr1": "WR", "rb1": "RB"}
    scores = {"qb1": 30.0, "qb2": 20.0, "wr1": 25.0, "rb1": 10.0}
    starting = ["QB", "WR", "FLEX", "SUPER_FLEX"]
    pick = {starting[i]: pid for i, pid in _assign(positions, scores, starting).items()}

    assert pick["QB"] == "qb1"          # most restrictive slot, best QB
    assert pick["WR"] == "wr1"
    assert pick["SUPER_FLEX"] == "qb2"  # only QB left fits superflex here
    assert pick["FLEX"] == "rb1"        # last flex-eligible skill player


def test_non_laminar_flex_slots_are_flagged_not_misfilled():
    # WRRB_FLEX + REC_FLEX overlap non-laminarly; greedy could be wrong, so they
    # are reported as unsupported instead of silently mis-filled.
    roster = Roster(roster_id=1, player_ids=["rb1", "wr1", "te1"], starters=[])
    proj = {"rb1": {"rush_yd": 90}, "wr1": {"rec": 10, "rec_yd": 100}, "te1": {"rec": 3}}
    meta = _meta(rb1="RB", wr1="WR", te1="TE")
    lu = optimal_lineup(roster, proj, SCORING, ["WRRB_FLEX", "REC_FLEX", "BN"], meta)
    assert lu.slots == []
    assert set(lu.unsupported_slots) == {"WRRB_FLEX", "REC_FLEX"}


def test_standard_slots_have_no_unsupported():
    roster = Roster(roster_id=1, player_ids=["wr1"], starters=["wr1"])
    meta = _meta(wr1="WR")
    lu = optimal_lineup(roster, {"wr1": {"rec": 5}}, SCORING,
                        ["QB", "RB", "WR", "TE", "FLEX", "SUPER_FLEX", "BN"], meta)
    assert lu.unsupported_slots == []


def test_projected_points_map():
    roster = Roster(roster_id=1, player_ids=["wr1"], starters=["wr1"])
    info = projected_points(roster, {"wr1": {"rec": 6, "rec_yd": 90, "rec_td": 1}},
                            SCORING, {"wr1": {"position": "WR", "full_name": "WR One"}})
    assert info["wr1"]["points"] == 18.0
    assert info["wr1"]["name"] == "WR One"


def test_te_premium_via_projected_points_is_not_doubled():
    # End-to-end through projected_points: a TE with a bonus_rec_te stat gets the
    # premium exactly once (regression guard for the old manual-TEP double-count).
    roster = Roster(roster_id=1, player_ids=["te1"], starters=["te1"])
    stats = {"te1": {"rec": 6, "rec_yd": 90, "rec_td": 1, "bonus_rec_te": 6}}
    meta = {"te1": {"position": "TE", "full_name": "TE One"}}
    info = projected_points(roster, stats, SCORING, meta)
    assert info["te1"]["points"] == 21.0  # 18 base + 0.5*6, not 24


def test_optimal_lineup_does_not_start_taxi_or_ir():
    # Taxi/IR are subsets of player_ids but cannot occupy a starting slot.
    # A taxi QB with a better projection must not beat the active starter.
    roster = Roster(
        roster_id=1,
        player_ids=["qb1", "taxi_qb", "ir_qb"],
        starters=["qb1"],
        taxi=["taxi_qb"],
        reserve=["ir_qb"],
    )
    proj = {
        "qb1": {"pass_yd": 200, "pass_td": 1},       # 12
        "taxi_qb": {"pass_yd": 400, "pass_td": 4},   # 32
        "ir_qb": {"pass_yd": 350, "pass_td": 3},     # 26
    }
    meta = _meta(qb1="QB", taxi_qb="QB", ir_qb="QB")
    lu = optimal_lineup(roster, proj, SCORING, ["QB", "BN"], meta)
    started = {s.player_id for s in lu.slots}
    assert started == {"qb1"}
    leftover = {b.player_id for b in lu.bench}
    assert leftover == {"taxi_qb", "ir_qb"}
