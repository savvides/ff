"""Parity with the trade-calculator sites.

Every vector in fixtures/calculator_vectors.json was produced by executing
FantasyCalc's and KeepTradeCut's own live JavaScript (scripts/calculator_oracle.mjs),
so these tests pin ff's Python ports to what the sites actually compute, not to a
re-typed formula. Offline: the fixture is data; regenerate it with the oracle.
"""

import json
import math
from pathlib import Path

from ff.analysis import calculators as C

VECTORS = json.loads((Path(__file__).parent / "fixtures" / "calculator_vectors.json").read_text())


def _same(py, js):
    if js is None:  # JSON has no NaN: the site produced NaN
        return isinstance(py, float) and math.isnan(py)
    return py == js


def _ktc_mismatch(v):
    got = C.ktc_adjustment(v["side1"], v["side2"], v["top"], v["variance"])
    if v["error"]:
        return None if got is None else f"expected a solve error, got {got}"
    if got is None:
        return "no result"
    t1 = sum(v["side1"]) + got.adj1
    t2 = sum(v["side2"]) + got.adj2
    ok = (_same(got.adj1, v["adj1"]) and _same(got.adj2, v["adj2"]) and got.side == v["side"]
          and got.shown == v["shown"] and C.ktc_site_fair(t1, t2, v["variance"]) == v["fair"]
          and _same(C._max(0, t1), v["total1"]) and _same(C._max(0, t2), v["total2"]))
    return None if ok else f"got {got} fair={C.ktc_site_fair(t1, t2, v['variance'])}"


# One test per market (not one per vector) keeps the gate fast; every mismatch is
# still reported with its inputs.
def test_fantasycalc_adjustment_matches_the_site_on_every_vector():
    bad = [(v["side1"], v["side2"], C.fc_adjustment(v["side1"], v["side2"]), (v["adj1"], v["adj2"]))
           for v in VECTORS["fc_dynasty"]
           if C.fc_adjustment(v["side1"], v["side2"]) != (v["adj1"], v["adj2"])]
    assert len(VECTORS["fc_dynasty"]) >= 200 and not bad, bad[:10]


def test_ktc_adjustment_and_verdict_match_the_site_on_every_vector():
    bad = [(v["side1"], v["side2"], v["top"], msg) for v in VECTORS["ktc"]
           for msg in [_ktc_mismatch(v)] if msg]
    assert len(VECTORS["ktc"]) >= 400 and not bad, bad[:10]


def test_the_screenshot_trade():
    # fantasycalc.com: Cousins 1446 + Pittman 1344 = 2790 vs Judkins 3068 + 753 = 3821
    assert C.fc_adjustment([1446, 1344], [3068]) == (0, 753)
    ktc = C.ktc_adjustment([2484, 2815], [4736], top=9999)
    assert (ktc.adj1, ktc.adj2, ktc.shown) == (0, 3186, True)
    assert not C.ktc_site_fair(2484 + 2815, 4736 + 3186)


def test_equal_counts_and_empty_sides():
    assert C.fc_adjustment([5000, 1], [2500, 2500]) == (0, 0)
    assert C.fc_adjustment([], [5000]) == (0, 0)
    assert C.ktc_adjustment([], [5000], top=9999) is None  # the site shows a hint, no verdict


def test_js_rounding_semantics():
    assert C.js_round(2.5) == 3 and C.js_round(-2.5) == -2 and C.js_round(0.49) == 0
    assert math.isnan(C._max(0, C.NAN)) and math.isnan(C._min(100, C.NAN))
    assert math.isnan(C._div(0, 0)) and C._div(1, 0) == math.inf


def test_every_reachable_ktc_branch_has_vectors():
    hits = VECTORS["meta"]["ktc"]["branch_hits"]
    unreached = set(VECTORS["meta"]["ktc"]["unreached_branches"])
    for tag, h in enumerate(hits, start=1):
        assert tag in unreached or h >= 5, f"branch {tag} has {h} vectors"


def test_fingerprints_match_the_fixture_run():
    meta = VECTORS["meta"]
    assert C.FINGERPRINTS["fc"]["chunk"] == meta["fantasycalc"]["chunk"]
    assert C.FINGERPRINTS["fc"]["main"] == meta["fantasycalc"]["main"]
    assert C.FINGERPRINTS["ktc"]["version"] == meta["ktc"]["version"]


def test_normalized_hash_ignores_renames_but_not_formula_changes():
    a = C.normalized_hash("function f(a,b){return Math.min(a*.6982,753+b)}")
    renamed = C.normalized_hash("function f(x, y) { return Math.min(x*.6982, 753+y) }")
    changed = C.normalized_hash("function f(a,b){return Math.min(a*.7,753+b)}")
    assert a == renamed and a != changed


def test_extract_functions_skips_calls_and_string_braces():
    js = 'x.go(1);function go(a){var s="}{";return a}go(2);class K{go(b){return b}}'
    assert C.extract_functions(js, "go") == ['go(a){var s="}{";return a}', "go(b){return b}"]


def test_a_changed_bundle_is_reported_as_drift():
    assert C.fingerprint_problems("ktc", "var nothing=1;")  # every function gone
    assert C.fingerprint_problems("fc", "")
