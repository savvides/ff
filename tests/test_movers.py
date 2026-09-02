from ff.analysis import find_arbitrage_movers, top_movers
from ff.contracts import ArbitrageMover, Asset, Roster
from ff.values import ValueBook


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
    b = ValueBook([
        Asset(id="1", name="Real Stud", position="WR", value=5000, redraft_value=3000),
        # near-zero redraft would yield a bogus +74900% gap without the floor
        Asset(id="2", name="Deep Stash", position="WR", value=1500, redraft_value=2),
    ])
    names = [a.name for a, _ in top_movers(b, buy=True, min_value=1000)]
    assert "Deep Stash" not in names
    assert "Real Stud" in names


def test_find_arbitrage_movers_basic():
    book = ValueBook([
        Asset(id="1", name="Hype Stud", position="WR", value=4000, secondary_value=6000),  # diff +2000
        Asset(id="2", name="Old Producer", position="RB", value=5000, secondary_value=3500),  # diff -1500
        Asset(id="3", name="Consensus Pick", position="QB", value=7000, secondary_value=7000),  # diff 0
        Asset(id="4", name="No Secondary Player", position="TE", value=3000, secondary_value=None),  # no secondary
        Asset(id="5", name="Deep Stash", position="WR", value=200, secondary_value=300),  # below min_value 1000
    ])
    movers = find_arbitrage_movers(book=book, min_value=1000)
    assert len(movers) == 3
    # Ranked by abs(diff) descending:
    # 1. Hype Stud: abs(2000)
    # 2. Old Producer: abs(-1500)
    # 3. Consensus Pick: abs(0)
    assert movers[0].asset.name == "Hype Stud"
    assert movers[0].diff == 2000
    assert movers[0].fc_value == 4000
    assert movers[0].secondary_value == 6000
    assert movers[0].dealer_value == 6000
    assert movers[0].ktc_value == 6000
    assert movers[0].market_bias == "Dealer"

    assert movers[1].asset.name == "Old Producer"
    assert movers[1].diff == -1500
    assert movers[1].fc_value == 5000
    assert movers[1].secondary_value == 3500
    assert movers[1].dealer_value == 3500
    assert movers[1].ktc_value == 3500
    assert movers[1].market_bias == "FC"

    assert movers[2].asset.name == "Consensus Pick"
    assert movers[2].diff == 0
    assert movers[2].market_bias == "EVEN"


def test_find_arbitrage_movers_with_rosters():
    book = ValueBook([
        Asset(id="1", name="Player One", position="WR", value=4000, secondary_value=6000),
        Asset(id="2", name="Player Two", position="RB", value=5000, secondary_value=3500),
    ])
    rosters = [
        Roster(roster_id=1, team_name="Team Alpha", player_ids=["1"]),
        Roster(roster_id=2, team_name="Team Beta", player_ids=["2"]),
    ]
    movers = find_arbitrage_movers(rosters, book)
    assert movers[0].asset.name == "Player One"
    assert movers[0].roster_id == 1
    assert movers[0].team_name == "Team Alpha"

    assert movers[1].asset.name == "Player Two"
    assert movers[1].roster_id == 2
    assert movers[1].team_name == "Team Beta"


def test_find_arbitrage_movers_filter_market():
    book = ValueBook([
        Asset(id="1", name="Hype Player", position="WR", value=4000, secondary_value=6000),  # Dealer > FC
        Asset(id="2", name="Value Veteran", position="RB", value=5000, secondary_value=3500),  # FC > Dealer
    ])
    dealer_movers = find_arbitrage_movers(book=book, market="dealer")
    assert len(dealer_movers) == 1
    assert dealer_movers[0].asset.name == "Hype Player"

    ktc_movers = find_arbitrage_movers(book=book, market="ktc")
    assert len(ktc_movers) == 1
    assert ktc_movers[0].asset.name == "Hype Player"

    fc_movers = find_arbitrage_movers(book=book, market="fc")
    assert len(fc_movers) == 1
    assert fc_movers[0].asset.name == "Value Veteran"


def test_find_arbitrage_movers_positional_args_flexibility():
    book = ValueBook([
        Asset(id="1", name="Player One", position="WR", value=4000, secondary_value=6000),
    ])
    # Call as find_arbitrage_movers(book)
    m1 = find_arbitrage_movers(book)
    assert len(m1) == 1
    # Call as find_arbitrage_movers(None, book)
    m2 = find_arbitrage_movers(None, book)
    assert len(m2) == 1


