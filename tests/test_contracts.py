"""Contracts test: multi-market extensions to Asset, TradeSide, and TradeEvaluation."""

from ff.contracts import Asset, TradeEvaluation, TradeSide


def test_asset_ktc_value():
    a = Asset(id="1", name="Test Player", value=1000, ktc_value=1200)
    assert a.value == 1000
    assert a.ktc_value == 1200


def test_asset_ktc_value_default_none():
    a = Asset(id="1", name="Test Player", value=1000)
    assert a.value == 1000
    assert a.ktc_value is None


def test_trade_evaluation_multi_market():
    side_a = TradeSide(assets=[
        Asset(id="1", name="Player A", value=2000, ktc_value=2500)
    ])
    side_b = TradeSide(assets=[
        Asset(id="2", name="Player B", value=1500, ktc_value=1200)
    ])
    eval = TradeEvaluation(side_a=side_a, side_b=side_b, label_a="You", label_b="Them")
    assert eval.delta == 500
    assert eval.ktc_delta == 1300
    assert eval.arbitrage_label() == "Consensus Win"


def test_trade_side_ktc_total():
    side = TradeSide(assets=[
        Asset(id="1", name="Player A", value=2000, ktc_value=2500),
        Asset(id="2", name="Player B", value=1000, ktc_value=1200),
    ])
    assert side.total == 3000
    assert side.ktc_total == 3700


def test_trade_side_ktc_total_none_when_no_ktc():
    side = TradeSide(assets=[
        Asset(id="1", name="Player A", value=2000),
        Asset(id="2", name="Player B", value=1000),
    ])
    assert side.total == 3000
    assert side.ktc_total is None


def test_trade_evaluation_no_ktc_returns_none():
    side_a = TradeSide(assets=[Asset(id="1", name="Player A", value=2000)])
    side_b = TradeSide(assets=[Asset(id="2", name="Player B", value=1500)])
    eval = TradeEvaluation(side_a=side_a, side_b=side_b)
    assert eval.ktc_value_a is None
    assert eval.ktc_value_b is None
    assert eval.ktc_delta is None
    assert eval.ktc_pct_diff is None
    assert eval.arbitrage_label() is None


def test_arbitrage_classifications():
    # 1. Consensus Win (FC +, KTC +)
    side_a = TradeSide(assets=[Asset(id="1", name="A", value=2000, ktc_value=2000)])
    side_b = TradeSide(assets=[Asset(id="2", name="B", value=1000, ktc_value=1000)])
    assert TradeEvaluation(side_a=side_a, side_b=side_b).arbitrage_label() == "Consensus Win"

    # 2. Consensus Loss (FC -, KTC -)
    side_a = TradeSide(assets=[Asset(id="1", name="A", value=1000, ktc_value=1000)])
    side_b = TradeSide(assets=[Asset(id="2", name="B", value=2000, ktc_value=2000)])
    assert TradeEvaluation(side_a=side_a, side_b=side_b).arbitrage_label() == "Consensus Loss"

    # 3. Value Arbitrage (FC +, KTC - or neutral)
    side_a = TradeSide(assets=[Asset(id="1", name="A", value=2000, ktc_value=1000)])
    side_b = TradeSide(assets=[Asset(id="2", name="B", value=1000, ktc_value=2000)])
    assert TradeEvaluation(side_a=side_a, side_b=side_b).arbitrage_label() == "Value Arbitrage"

    # 4. Hype Arbitrage (FC - or neutral, KTC +)
    side_a = TradeSide(assets=[Asset(id="1", name="A", value=1000, ktc_value=2000)])
    side_b = TradeSide(assets=[Asset(id="2", name="B", value=2000, ktc_value=1000)])
    assert TradeEvaluation(side_a=side_a, side_b=side_b).arbitrage_label() == "Hype Arbitrage"

    # 5. Fair (both within threshold)
    side_a = TradeSide(assets=[Asset(id="1", name="A", value=1000, ktc_value=1000)])
    side_b = TradeSide(assets=[Asset(id="2", name="B", value=1000, ktc_value=1000)])
    assert TradeEvaluation(side_a=side_a, side_b=side_b).arbitrage_label() == "Fair"
