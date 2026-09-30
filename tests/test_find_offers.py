"""scripts/find_offers.py: only packages that pass the offer rule on site-adjusted
numbers come back, best rebuild fit first."""

import importlib.util
from pathlib import Path

from ff.contracts import Asset

_spec = importlib.util.spec_from_file_location(
    "find_offers", Path(__file__).resolve().parent.parent / "scripts" / "find_offers.py")
find_offers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(find_offers)

TOP = 9999
SALE = Asset(id="1", name="Vet QB", position="QB", age=38, value=3000, secondary_value=5000, redraft_value=2800)


def _theirs():
    return [
        Asset(id="2", name="Young Twin", position="WR", age=24, value=3000, secondary_value=5000),
        Asset(id="3", name="Old Twin", position="WR", age=31, value=3000, secondary_value=5000),
        Asset(id="4", name="Stud", position="RB", age=23, value=8000, secondary_value=9000),
        Asset(id="5", name="Half A", position="WR", age=24, value=1500, secondary_value=2500),
        Asset(id="6", name="Half B", position="WR", age=24, value=1500, secondary_value=2500),
    ]


def test_only_passing_packages_come_back_and_each_re_judges_as_pass():
    rows = find_offers.search([SALE], _theirs(), [], top=TOP)
    assert [r["get"] for r in rows] == [["Young Twin"]]
    for r in rows:
        _, verdict = find_offers.judge([SALE], [a for a in _theirs() if a.name in r["get"]], top=TOP)
        assert verdict.passes and r["fc_pct"] < 10 and r["ktc_pct"] < 10


def test_older_players_are_never_offered_back():
    names = {n for r in find_offers.search([SALE], _theirs(), [], top=TOP, limit=50) for n in r["get"]}
    assert "Old Twin" not in names


def test_a_raw_even_two_for_one_fails_once_the_sites_adjust_it():
    # 3000 vs 1500 + 1500 sums even, but FantasyCalc credits the single-asset side
    # floor(min(1500 * 0.6982, 753)) = 753 -> 3753 vs 3000, a 20% gap.
    _, verdict = find_offers.judge([SALE], [a for a in _theirs() if a.name.startswith("Half")], top=TOP)
    assert verdict.status == "FAIL" and round(verdict.fc_pct, 1) == 20.1
    rows = find_offers.search([SALE], _theirs(), [], top=TOP, limit=50)
    assert ["Half A", "Half B"] not in [r["get"] for r in rows]


def test_ledger_picks_are_priced_at_their_projected_tier_and_labeled_by_origin():
    from ff.contracts import FuturePick
    from ff.values import ValueBook
    flat = Asset(id="2028 4", name="2028 4th", kind="pick", position="PICK", value=800,
                 secondary_value=1600, secondary_approx=True)
    book = ValueBook([flat], secondary_top=9999,
                     secondary_map={"2028 4 early": 1900, "2028 4 mid": 1600, "2028 4 late": 1300})
    picks = [FuturePick(season="2028", round=4, original_roster_id=7),
             FuturePick(season="2028", round=4, original_roster_id=8)]  # both project Late
    origins = {}
    assets = find_offers._roster_assets(book, [], picks, lambda rid: "late",
                                        lambda rid: f"from roster {rid}", origins)
    assert [(a.name, a.value, a.secondary_value, a.secondary_approx) for a in assets] == [
        ("2028 4th (Late)", 800, 1300, False), ("2028 4th (Late) #2", 800, 1300, False)]
    assert origins == {"2028 4th (Late)": "from roster 7", "2028 4th (Late) #2": "from roster 8"}


def test_two_picks_at_the_same_tier_can_both_be_asked_for_and_are_not_listed_twice():
    pick = Asset(id="2028 2 late", name="2028 2nd (Late)", kind="pick", position="PICK",
                 value=3000, secondary_value=5000)
    twin = pick.model_copy(update={"name": "2028 2nd (Late) #2"})
    assert [r["get"] for r in find_offers.search([SALE], [pick, twin], [], top=TOP)] == [["2028 2nd (Late)"]]
    other = Asset(id="1b", name="Vet WR", position="WR", age=33, value=3000, secondary_value=5000)
    assert [r["get"] for r in find_offers.search([SALE, other], [pick, twin], [], top=TOP)] == [
        ["2028 2nd (Late)", "2028 2nd (Late) #2"]]


RPOS = ["QB", "RB", "WR", "TE", "FLEX", "SUPER_FLEX", "BN", "BN"]
MY_PLAYERS = [  # a weak QB room, two strong TEs
    SALE.model_copy(update={"position": "WR"}),
    Asset(id="m1", name="My QB", position="QB", age=30, value=500, secondary_value=1200),
    Asset(id="m2", name="My TE1", position="TE", age=23, value=6000, secondary_value=7000),
    Asset(id="m3", name="My TE2", position="TE", age=24, value=5000, secondary_value=6000),
    Asset(id="m4", name="My RB", position="RB", age=24, value=4000, secondary_value=5500),
    Asset(id="m5", name="My RB2", position="RB", age=25, value=3500, secondary_value=5000),
    Asset(id="m6", name="My WR", position="WR", age=24, value=4500, secondary_value=6000),
]


def test_a_young_starter_at_a_need_outranks_a_surplus_piece_of_equal_value():
    theirs = [
        Asset(id="q", name="Young QB", position="QB", age=24, value=3000, secondary_value=5000),
        Asset(id="t", name="Young TE", position="TE", age=23, value=3000, secondary_value=5000),
    ]
    rows = find_offers.search([SALE], theirs, [], top=TOP, my_players=MY_PLAYERS,
                              roster_positions=RPOS, needs={"QB"}, limit=50)
    singles = [r for r in rows if len(r["get"]) == 1]
    assert [r["get"] for r in singles] == [["Young QB"], ["Young TE"]]  # both pass; the QB fills the need
    assert singles[0]["roles"]["Young QB"] == "starts at QB"
    assert singles[1]["roles"]["Young TE"] == "surplus TE, behind My TE1, My TE2"  # TE2 starts at FLEX
    assert singles[1]["net_youth"] == 0  # a surplus piece is not counted as gained young value


def test_warnings_for_injured_falling_or_dropped_pieces():
    hurt = Asset(id="f", name="Hurt TE", position="TE", age=23, value=1800, secondary_value=3600,
                 injury_status="Questionable", injury_body_part="Ankle", trend_30day=-715)
    warn = find_offers.flags(hurt, dropped={"f"})
    assert warn[0].startswith("Q") and "value -715 in 30 days" in warn
    assert "among Sleeper's most-dropped players today" in warn


def test_a_flagged_starter_is_not_counted_as_young_value():
    theirs = [
        Asset(id="q", name="Young QB", position="QB", age=24, value=3000, secondary_value=5000),
        Asset(id="f", name="Hurt QB", position="QB", age=24, value=3000, secondary_value=5000,
              injury_status="Questionable", injury_body_part="Ankle"),
    ]
    rows = find_offers.search([SALE], theirs, [], top=TOP, my_players=MY_PLAYERS,
                              roster_positions=RPOS, needs={"QB"}, dropped=set(), limit=50)
    singles = [r for r in rows if len(r["get"]) == 1]
    assert [r["get"] for r in singles] == [["Young QB"], ["Hurt QB"]]
    assert singles[1]["roles"]["Hurt QB"] == "starts at QB" and singles[1]["net_youth"] == 0
