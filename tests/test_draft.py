"""Live draft board: pick-number math, pick ownership through trades, and the
available-player ranking. All pure/offline (gate lane)."""

import responses

from ff.analysis import available, my_picks, pick_number
from ff.sleeper import SleeperClient


# --- pick_number ---------------------------------------------------------

def test_pick_number_linear():
    # Linear: slot order is identical every round (slot 1 always picks first).
    assert pick_number(1, 1, 12) == 1
    assert pick_number(1, 12, 12) == 12
    assert pick_number(3, 1, 12) == 25
    assert pick_number(3, 5, 12) == 29
    assert pick_number(3, 11, 12) == 35
    assert pick_number(4, 1, 12) == 37


def test_pick_number_snake():
    # Snake: even rounds reverse the order.
    assert pick_number(1, 1, 12, snake=True) == 1
    assert pick_number(2, 12, 12, snake=True) == 13   # first pick of round 2
    assert pick_number(2, 1, 12, snake=True) == 24    # last pick of round 2
    assert pick_number(3, 1, 12, snake=True) == 25


def test_pick_number_third_round_reversal():
    # 3RR: round 3 keeps round 2's reversed direction instead of flipping back.
    assert pick_number(2, 1, 12, snake=True, reversal_round=3) == 24
    assert pick_number(3, 12, 12, snake=True, reversal_round=3) == 25  # round 3 reversed
    assert pick_number(3, 1, 12, snake=True, reversal_round=3) == 36
    assert pick_number(4, 1, 12, snake=True, reversal_round=3) == 37  # round 4 flips back


# --- my_picks (ownership through trades) ---------------------------------

# The real 2026 rookie-draft scenario for roster 3 (linear, 12 teams, 4 rounds):
# traded away its own R1, acquired roster 4's and roster 6's R3 picks.
SLOT_TO_ROSTER = {1: 3, 2: 10, 3: 5, 4: 12, 5: 4, 6: 11, 7: 8,
                  8: 2, 9: 9, 10: 7, 11: 6, 12: 1}
TRADED = [
    {"round": 1, "roster_id": 3, "owner_id": 12, "previous_owner_id": 3},   # my R1 -> roster 12
    {"round": 1, "roster_id": 11, "owner_id": 3, "previous_owner_id": 11},  # roster11 R1 -> me
    {"round": 1, "roster_id": 8, "owner_id": 3, "previous_owner_id": 8},    # roster8 R1 -> me
    {"round": 3, "roster_id": 4, "owner_id": 3, "previous_owner_id": 2},    # roster4 R3 -> me
    {"round": 3, "roster_id": 6, "owner_id": 3, "previous_owner_id": 2},    # roster6 R3 -> me
]
# Roster 3's three made picks, keyed by overall pick number.
_DETAIL = {
    6: {"roster_id": 3, "player_id": "2569",
        "metadata": {"first_name": "Ty", "last_name": "Simpson", "position": "QB"}},
    7: {"roster_id": 3, "player_id": "2788",
        "metadata": {"first_name": "Kenyon", "last_name": "Sadiq", "position": "TE"}},
    13: {"roster_id": 3, "player_id": "1843",
         "metadata": {"first_name": "Nicholas", "last_name": "Singleton", "position": "RB"}},
}
# 24 picks made so far (2 of 4 rounds done); picks land in pick_no order, which is
# what makes the count-based "used" flag correct.
PICKS_MADE = [
    {"pick_no": n, "round": (n - 1) // 12 + 1, **_DETAIL.get(n, {})}
    for n in range(1, 25)
]


def test_my_picks_computes_full_ownership_through_trades():
    picks = my_picks(3, SLOT_TO_ROSTER, TRADED, PICKS_MADE,
                     teams=12, rounds=4, snake=False)
    assert [p.pick_no for p in picks] == [6, 7, 13, 25, 29, 35, 37]


def test_my_picks_marks_used_and_upcoming():
    picks = my_picks(3, SLOT_TO_ROSTER, TRADED, PICKS_MADE,
                     teams=12, rounds=4, snake=False)
    used = {p.pick_no: p for p in picks if p.used}
    upcoming = [p.pick_no for p in picks if not p.used]
    assert set(used) == {6, 7, 13}
    assert upcoming == [25, 29, 35, 37]
    assert used[6].player_name == "Ty Simpson"
    assert used[7].position == "TE"


def test_my_picks_excludes_pick_traded_away():
    # My own R1 (pick #1, slot 1) was traded away -> not mine.
    picks = my_picks(3, SLOT_TO_ROSTER, TRADED, PICKS_MADE,
                     teams=12, rounds=4, snake=False)
    assert 1 not in [p.pick_no for p in picks]


def test_my_picks_other_roster_sees_acquired_pick():
    # Roster 12 acquired my R1 (slot 1, pick #1).
    picks = my_picks(12, SLOT_TO_ROSTER, TRADED, PICKS_MADE,
                     teams=12, rounds=4, snake=False)
    assert 1 in [p.pick_no for p in picks]


# --- available -----------------------------------------------------------

def test_available_excludes_taken_and_sorts_by_value(book):
    taken = set()
    top = available(book, taken)
    assert top == sorted(top, key=lambda a: a.value, reverse=True)
    assert all(not a.is_pick for a in top)
    # exclude the most valuable available player and confirm it drops out
    best = top[0]
    rest = available(book, {best.id})
    assert best.id not in {a.id for a in rest}


def test_available_position_filter(book):
    qbs = available(book, set(), position="QB")
    assert qbs and all(a.position == "QB" for a in qbs)


def test_available_limit(book):
    assert len(available(book, set(), limit=3)) == 3


# --- SleeperClient draft endpoints (mocked) ------------------------------

@responses.activate
def test_draft_endpoints_hit_correct_urls():
    base = "https://api.sleeper.app/v1"
    responses.add(responses.GET, f"{base}/league/LG1/drafts", json=[{"draft_id": "D1"}], status=200)
    responses.add(responses.GET, f"{base}/draft/D1", json={"draft_id": "D1"}, status=200)
    responses.add(responses.GET, f"{base}/draft/D1/picks", json=[{"pick_no": 1}], status=200)
    responses.add(responses.GET, f"{base}/draft/D1/traded_picks", json=[{"round": 1}], status=200)
    sc = SleeperClient()
    assert sc.drafts("LG1") == [{"draft_id": "D1"}]
    assert sc.draft("D1") == {"draft_id": "D1"}
    assert sc.draft_picks("D1") == [{"pick_no": 1}]
    assert sc.draft_traded_picks("D1") == [{"round": 1}]
