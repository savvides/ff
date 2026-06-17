"""Buy-low / sell-high ranking from the dynasty-vs-redraft gap."""

from ff.analysis import top_movers


def test_buy_low_ranks_dynasty_over_redraft_first(book):
    # Rome Odunze: dynasty 4500 >> redraft 3800 -> biggest buy-low.
    buy = top_movers(book, buy=True)
    assert buy[0][0].name == "Rome Odunze"
    assert buy[0][1] > 0  # positive gap


def test_sell_high_ranks_redraft_over_dynasty_first(book):
    # Josh Allen: redraft 7600 >> dynasty 7000 -> biggest sell-high.
    sell = top_movers(book, buy=False)
    assert sell[0][0].name == "Josh Allen"
    assert sell[0][1] < 0  # negative gap


def test_picks_and_unvalued_excluded(book):
    rows = top_movers(book, limit=50)
    assert all(not a.is_pick and a.redraft_value for a, _ in rows)


def test_min_value_floor_excludes_deep_stashes():
    from ff.contracts import Asset
    from ff.values import ValueBook
    b = ValueBook([
        Asset(id="1", name="Real Stud", position="WR", value=5000, redraft_value=3000),
        # near-zero redraft would yield a bogus +74900% gap without the floor
        Asset(id="2", name="Deep Stash", position="WR", value=1500, redraft_value=2),
    ])
    names = [a.name for a, _ in top_movers(b, buy=True, min_value=1000)]
    assert "Deep Stash" not in names
    assert "Real Stud" in names
