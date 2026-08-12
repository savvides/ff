"""Gate tests for the team-relative draft fit scorer.

All deterministic, offline, tiny in-test objects (no network, no fixtures file).
Asserts ORDERING and the structural no-double-count guard, not tuned magnitudes.
"""
from __future__ import annotations

import inspect

from ff.analysis import fit as fitmod
from ff.analysis.fit import (
    HORIZON_FLOOR,
    WEIGHTS,
    detect_status,
    positional_standing,
    rank_fits,
    score_candidate,
    startable_value,
)
from ff.analysis.movers import value_redraft_gap
from ff.contracts import Asset, RosterValuation


def A(id_, pos, value, redraft=None):
    return Asset(id=id_, name=id_, position=pos, value=value, redraft_value=redraft)


def RV(assets, rank):
    return RosterValuation(roster_id=1, team_name="me", assets=assets, power_rank=rank)


SF = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "BN", "IR"]



# (b) starter-upgrade marginal math -----------------------------------------
def test_marginal_starter_upgrade_math():
    rp = ["WR", "BN"]  # one WR slot, no FLEX -> unambiguous
    mine = [A("w1", "WR", 1000)]
    w = WEIGHTS["contend"]
    base, _ = startable_value(mine, rp)
    assert base == 1000

    big = score_candidate(A("c", "WR", 5000), base, mine, rp, {}, w, "contend", 1)
    assert big.marginal_starter == 4000  # displaces the 1000 starter

    small = score_candidate(A("c", "WR", 500), base, mine, rp, {}, w, "contend", 1)
    assert small.marginal_starter == 0  # does not crack the lineup

    nope = score_candidate(A("c", "K", 3000), base, mine, rp, {}, w, "contend", 1)
    assert nope.marginal_starter == 0  # no eligible slot


# (c) rebuild vs contend flip the order -------------------------------------
def test_horizon_flips_order_by_status():
    rp = ["QB", "BN"]  # WR candidates can't crack this lineup -> only horizon decides
    mine = [A("q", "QB", 9000)]
    myval = RV(mine, 1)
    vet = A("vet", "WR", 3000, redraft=4500)  # redraft > dynasty: win-now
    yng = A("yng", "WR", 3000, redraft=1800)  # dynasty > redraft: young
    cands = [vet, yng]

    _, fc = rank_fits(cands, myval, [myval], rp, "contend", 10)
    oc = [f.asset.id for f in fc]
    _, fr = rank_fits(cands, myval, [myval], rp, "rebuild", 10)
    orr = [f.asset.id for f in fr]

    assert oc.index("vet") < oc.index("yng")  # contend favors win-now vet
    assert orr.index("yng") < orr.index("vet")  # rebuild favors young

    # The rationale must describe the REAL signal, not the post-sign tilt. The
    # horizon sign is flipped by status inside score_candidate, so keying the
    # message off the flipped tilt sign inverts it for contenders.
    why_c = {f.asset.id: f.why for f in fc}
    why_r = {f.asset.id: f.why for f in fr}
    assert "win-now" in why_c["vet"]  # contend boosts the vet *as* win-now value
    assert "building block" in why_r["yng"]  # rebuild boosts the young *as* future
    assert "building block" not in why_c["vet"]  # never call a win-now vet "young"


# (c2) standing tilt promotes a startable hole, contenders only -------------
def test_standing_tilt_promotes_hole_position_in_contend_only():
    # One slot per skill position, no FLEX -> startable value per position is the
    # team's best player at that position. I'm RB-thin and TE-rich vs the league.
    rp = ["QB", "RB", "WR", "TE", "BN"]
    me = RV([A("my_rb", "RB", 3000), A("my_te", "TE", 5000)], 6)
    o1 = RosterValuation(roster_id=2, team_name="o1",
                         assets=[A("o1_rb", "RB", 6000), A("o1_te", "TE", 1000)])
    o2 = RosterValuation(roster_id=3, team_name="o2",
                         assets=[A("o2_rb", "RB", 7000), A("o2_te", "TE", 500)])
    all_vals = [me, o1, o2]

    # Direct standing math: RB is a genuine hole, TE is a strength.
    by = {s.position: s for s in positional_standing(me, all_vals, rp)}
    assert by["RB"].mine == 3000 and by["RB"].median == 6000 and by["RB"].is_hole
    assert by["TE"].mine == 5000 and by["TE"].median == 1000 and not by["TE"].is_hole

    # Two candidates, neither cracks my lineup (so upgrade=0 for both) and neither
    # has redraft (horizon=0). The TE even has the HIGHER market value. Only the
    # standing tilt differs -> in contend the hole-filling RB must jump ahead.
    cand_te = A("c_te", "TE", 2000)
    cand_rb = A("c_rb", "RB", 1999)
    cands = [cand_te, cand_rb]  # incoming market order: TE first (2000 > 1999)

    _, fc = rank_fits(cands, me, all_vals, rp, "contend", 10)
    assert [f.asset.id for f in fc] == ["c_rb", "c_te"]  # hole wins despite lower value
    _, fr = rank_fits(cands, me, all_vals, rp, "rebuild", 10)
    assert [f.asset.id for f in fr] == ["c_te", "c_rb"]  # w_s=0 -> market order holds


# (d) graceful degradation when redraft is missing --------------------------
def test_redraft_none_falls_back_to_market_order():
    rp = ["WR", "BN"]
    mine = [A("w", "WR", 2000)]
    myval = RV(mine, 12)
    cands = [A("a", "WR", 900), A("b", "RB", 800), A("c", "TE", 700)]  # all redraft=None
    _, fits = rank_fits(cands, myval, [myval], rp, "rebuild", 10)
    assert [f.asset.id for f in fits] == ["a", "b", "c"]  # market (value) order
    assert all(f.horizon_tilt == 0.0 for f in fits)


def test_zero_value_candidate_is_safe():
    rp = ["WR", "BN"]
    mine = [A("w", "WR", 1000)]
    z = score_candidate(A("z", "WR", 0), 1000, mine, rp, {}, WEIGHTS["rebuild"], "rebuild", 5)
    assert z.fit_score == 0.0  # no div-by-zero, sinks to the bottom


# (e) double-count guard -----------------------------------------------------
def test_fit_never_reapplies_format_scarcity():
    # Drop the module docstring; its prose legitimately names the scarcity we do
    # NOT re-apply. The guard is about code, not documentation.
    code = inspect.getsource(fitmod).split('"""', 2)[2]
    assert "detect_format" not in code  # no format detection
    assert "Format" not in code  # never imports or references the Format model
    assert ".superflex" not in code  # never reads format-scarcity attributes
    assert ".num_qbs" not in code
    # behavioral: no slots, no standing, no redraft -> fit == anchor exactly
    f = score_candidate(A("x", "WR", 2500), 0, [], [], {}, WEIGHTS["rebuild"], "rebuild", 1)
    assert f.fit_score == 2500.0


def test_value_redraft_gap_matches_and_floors():
    assert value_redraft_gap(A("a", "WR", 2000, 1000), 1000) == (2000 - 1000) / 1000 * 100
    assert value_redraft_gap(A("b", "WR", 2000, 50), 1000) is None  # redraft below floor
    assert value_redraft_gap(A("c", "WR", 50, 2000), 1000) is None  # value below floor


# status detection -----------------------------------------------------------
def test_detect_status_thirds():
    assert detect_status(1, 12) == "contend"
    assert detect_status(12, 12) == "rebuild"
    assert detect_status(6, 12) == "balanced"
    assert detect_status(None, 12) == "balanced"
