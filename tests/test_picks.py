"""Pick ledger: default endowment reconciled with traded_picks, tier-valued.

Roster/rank shape used throughout (from the book + rosters fixtures):
roster 2 (Gridiron Kings) is #1, roster 1 (Dynasty Warriors) is #2, roster 3
(carol) is #3 - so with 3 teams their tiers are late / mid / early.
"""

import pytest

from ff.analysis import pick_ledger, pick_tier, price_pick
from ff.contracts import FuturePick
from ff.sleeper import build_rosters

RANKS = {1: 2, 2: 1, 3: 3}


@pytest.fixture
def rosters(rosters_raw, users_raw):
    return build_rosters(rosters_raw, users_raw)


def _team(ledger, roster_id):
    return next(t for t in ledger if t.roster_id == roster_id)


def test_no_trades_everyone_owns_their_own(rosters, book):
    ledger = pick_ledger(rosters, [], book, RANKS, seasons=["2027"], rounds=2)
    assert len(ledger) == 3
    for t in ledger:
        assert len(t.picks) == 2  # own 1st + own 2nd
        assert all(not p.acquired for p in t.picks)
        assert all(p.original_roster_id == t.roster_id for p in t.picks)


def test_traded_away_and_acquired(rosters, book, traded_picks):
    ledger = pick_ledger(rosters, traded_picks, book, RANKS,
                         seasons=["2027", "2028"], rounds=2)
    warriors = _team(ledger, 1)
    gridiron = _team(ledger, 2)
    # Warriors: own 2027 1st + Gridiron's 1st + carol's 2nd + own 2028 1st/2nd;
    # their own 2027 2nd is gone (traded to carol).
    assert len(warriors.picks) == 5
    assert {(p.season, p.round, p.original_roster_id) for p in warriors.picks} == {
        ("2027", 1, 1), ("2027", 1, 2), ("2027", 2, 3), ("2028", 1, 1), ("2028", 2, 1)}
    acquired = [p for p in warriors.picks if p.acquired]
    assert {p.original_team for p in acquired} == {"Gridiron Kings", "carol"}
    # Gridiron kept nothing in 2027 but its own 2nd.
    assert [(p.season, p.round) for p in gridiron.picks] == [
        ("2027", 2), ("2028", 1), ("2028", 2)]


def test_retraded_pick_last_row_wins(rosters, book, traded_picks):
    # carol's 2027 2nd went to Gridiron, then Gridiron flipped it to Warriors:
    # the later traded_picks row is current, so Warriors own it.
    ledger = pick_ledger(rosters, traded_picks, book, RANKS,
                         seasons=["2027"], rounds=2)
    holders = [t.roster_id for t in ledger
               if any(p.season == "2027" and p.round == 2 and p.original_roster_id == 3
                      for p in t.picks)]
    assert holders == [1]


def test_valuation_tiers_and_totals(rosters, book, traded_picks):
    ledger = pick_ledger(rosters, traded_picks, book, RANKS,
                         seasons=["2027", "2028"], rounds=2)
    warriors = _team(ledger, 1)
    by_key = {(p.season, p.round, p.original_roster_id): p for p in warriors.picks}
    assert by_key[("2027", 1, 1)].value == 3100  # own 1st, rank 2/3 -> mid
    assert by_key[("2027", 1, 1)].tier == "mid"
    assert by_key[("2027", 1, 2)].value == 2400  # Gridiron's 1st, rank 1/3 -> late
    assert by_key[("2027", 2, 3)].value == 1400  # no tiered 2nds -> flat round value
    assert by_key[("2027", 2, 3)].tier is None
    assert by_key[("2028", 1, 1)].value == 2200  # flat 2028 1st
    assert by_key[("2028", 2, 1)].value == 0  # unpriced round stays 0, never guessed
    assert warriors.total_value == 3100 + 2400 + 1400 + 2200
    # Best capital first: Warriors 9,100 > carol (4200+1400+2200) > Gridiron.
    assert [t.roster_id for t in ledger] == [1, 3, 2]


def test_pick_tier_thirds():
    assert pick_tier(1, 12) == "late"
    assert pick_tier(4, 12) == "late"
    assert pick_tier(5, 12) == "mid"
    assert pick_tier(8, 12) == "mid"
    assert pick_tier(9, 12) == "early"
    assert pick_tier(12, 12) == "early"
    assert pick_tier(None, 12) == "mid"  # unknown rank prices neutrally
    assert pick_tier(1, 2) == "mid"  # too few teams for thirds


def test_price_pick_fallbacks(book):
    assert price_pick(book, "2027", 1, "early") == (4200, "early")
    assert price_pick(book, "2027", 2, "early") == (1400, None)  # no tiered 2nds
    assert price_pick(book, "2028", 2, "mid") == (0, None)  # unpriced round


def test_future_pick_label():
    def label(rnd):
        return FuturePick(season="2027", round=rnd, original_roster_id=1).label

    assert label(1) == "2027 1st"
    assert label(4) == "2027 4th"
    # Startup drafts run 20+ rounds; ordinals must not read "21th"/"12nd".
    assert label(12) == "2027 12th"
    assert label(21) == "2027 21st"
    assert label(23) == "2027 23rd"


def test_traded_round_beyond_rounds_extends_ledger(rosters, book):
    # A traded 2027 3rd proves the rookie draft has >= 3 rounds: the acquired
    # pick must not vanish, and everyone's own 3rd exists by the same logic.
    tp = [
        {"season": "2027", "round": 3, "roster_id": 2, "previous_owner_id": 2, "owner_id": 1},
        {"season": "2029", "round": 5, "roster_id": 2, "previous_owner_id": 2, "owner_id": 1},
    ]
    ledger = pick_ledger(rosters, tp, book, RANKS, seasons=["2027"], rounds=2)
    warriors = _team(ledger, 1)
    keys = {(p.season, p.round, p.original_roster_id) for p in warriors.picks}
    assert ("2027", 3, 2) in keys
    # every team's ORIGINAL 3rd now exists somewhere in the ledger
    all_keys = {(p.season, p.round, p.original_roster_id)
                for t in ledger for p in t.picks}
    assert {("2027", 3, rid) for rid in (1, 2, 3)} <= all_keys
    # ...but a traded pick OUTSIDE the season window must not stretch the board.
    assert not any(p.round > 3 for t in ledger for p in t.picks)
