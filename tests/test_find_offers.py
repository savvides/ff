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
