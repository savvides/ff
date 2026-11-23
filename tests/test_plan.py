from ff.analysis.plan import buy_candidates, sell_candidates, trade_stance
from ff.contracts import Asset
from ff.values import ValueBook


def _a(i, pos, age, value, redraft):
    return Asset(id=i, name=i, position=pos, age=age, value=value, redraft_value=redraft)


OLD_RB = _a("old_rb", "RB", 28, 3000, 4500)      # aging and worth more to a contender
PRIME_WR = _a("prime_wr", "WR", 25, 6000, 6000)
YOUNG_WR = _a("young_wr", "WR", 22, 4000, 2000)   # priced for the future
OLD_QB = _a("old_qb", "QB", 38, 2000, 2100)
CHEAP = _a("cheap", "RB", 30, 500, 900)
ASSETS = [OLD_RB, PRIME_WR, YOUNG_WR, OLD_QB, CHEAP]


def test_stance_prefers_playoff_odds_over_roster_strength():
    assert trade_stance(1, 12, 0.02) == "seller"   # strong roster, dead season
    assert trade_stance(12, 12, 0.80) == "buyer"
    assert trade_stance(6, 12, 0.30) == "hold"
    assert [trade_stance(r, 12, None) for r in (1, 6, 12)] == ["buyer", "hold", "seller"]


def test_seller_shops_aging_and_win_now_players():
    sells = sell_candidates(ASSETS, "seller")
    assert [a.id for a, _ in sells] == ["old_rb", "old_qb"]
    assert "age 28" in sells[0][1] and "50% more" in sells[0][1]
    # Holding: age alone is a reason, a win-now premium is not.
    assert [a.id for a, _ in sell_candidates([PRIME_WR, _a("x", "WR", 26, 3000, 4500)], "hold")] == []
    assert sell_candidates(ASSETS, "buyer") == []


def test_buy_targets_follow_the_stance():
    book = ValueBook(ASSETS)
    young = buy_candidates(book, set(), "seller")
    assert [a.id for a, _ in young] == ["young_wr"] and "50% of his price" in young[0][1]
    assert [a.id for a, _ in buy_candidates(book, set(), "buyer")] == ["old_rb"]
    assert buy_candidates(book, {"young_wr"}, "seller") == []
    assert buy_candidates(book, set(), "hold") == []
