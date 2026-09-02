"""Contracts test: multi-market extensions to Asset, TradeSide, TradeEvaluation, and ArbitrageMover."""

from ff.contracts import ArbitrageMover, Asset, TradeEvaluation, TradeSide


def test_asset_secondary_value():
    a = Asset(id="1", name="Test Player", value=1000, secondary_value=1500)
    assert a.value == 1000
    assert a.secondary_value == 1500
    assert a.ktc_value == 1500
    assert a.dealer_value == 1500


def test_asset_legacy_ktc_value_init():
    a = Asset(id="1", name="Test Player", value=1000, ktc_value=1200)
    assert a.value == 1000
    assert a.secondary_value == 1200
    assert a.ktc_value == 1200
    assert a.dealer_value == 1200


def test_asset_dealer_value_init():
    a = Asset(id="1", name="Test Player", value=1000, dealer_value=1300)
    assert a.value == 1000
    assert a.secondary_value == 1300
    assert a.ktc_value == 1300
    assert a.dealer_value == 1300


def test_asset_secondary_value_default_none():
    a = Asset(id="1", name="Test Player", value=1000)
    assert a.value == 1000
    assert a.secondary_value is None
    assert a.ktc_value is None
    assert a.dealer_value is None


def test_asset_property_setters():
    a = Asset(id="1", name="Test Player", value=1000)
    a.ktc_value = 1400
    assert a.secondary_value == 1400
    assert a.ktc_value == 1400
    assert a.dealer_value == 1400

    a.dealer_value = 1600
    assert a.secondary_value == 1600
    assert a.ktc_value == 1600
    assert a.dealer_value == 1600


def test_trade_side_secondary_total():
    side = TradeSide(assets=[
        Asset(id="1", name="Player A", value=2000, secondary_value=2500),
        Asset(id="2", name="Player B", value=1000, secondary_value=1200),
    ])
    assert side.total == 3000
    assert side.secondary_total == 3700
    assert side.ktc_total == 3700
    assert side.dealer_total == 3700


def test_trade_side_secondary_total_none_when_no_secondary():
    side = TradeSide(assets=[
        Asset(id="1", name="Player A", value=2000),
        Asset(id="2", name="Player B", value=1000),
    ])
    assert side.total == 3000
    assert side.secondary_total is None
    assert side.ktc_total is None
    assert side.dealer_total is None


def test_trade_evaluation_multi_market():
    side_a = TradeSide(assets=[
        Asset(id="1", name="Player A", value=2000, secondary_value=2500)
    ])
    side_b = TradeSide(assets=[
        Asset(id="2", name="Player B", value=1500, secondary_value=1200)
    ])
    eval = TradeEvaluation(side_a=side_a, side_b=side_b, label_a="You", label_b="Them")
    assert eval.delta == 500
    assert eval.secondary_delta == 1300
    assert eval.ktc_delta == 1300
    assert eval.dealer_delta == 1300
    assert eval.secondary_value_a == 2500
    assert eval.secondary_value_b == 1200
    assert eval.ktc_value_a == 2500
    assert eval.ktc_value_b == 1200
    assert eval.dealer_value_a == 2500
    assert eval.dealer_value_b == 1200
    assert round(eval.secondary_pct_diff, 2) == round(1300 / 2500 * 100.0, 2)
    assert round(eval.ktc_pct_diff, 2) == round(1300 / 2500 * 100.0, 2)
    assert round(eval.dealer_pct_diff, 2) == round(1300 / 2500 * 100.0, 2)
    assert eval.secondary_is_fair() is False
    assert eval.secondary_arbitrage_label() == "Consensus Win"
    assert eval.arbitrage_label() == "Consensus Win"
    assert eval.ktc_arbitrage_label() == "Consensus Win"
    assert eval.dealer_arbitrage_label() == "Consensus Win"


def test_trade_evaluation_no_secondary_returns_none():
    side_a = TradeSide(assets=[Asset(id="1", name="Player A", value=2000)])
    side_b = TradeSide(assets=[Asset(id="2", name="Player B", value=1500)])
    eval = TradeEvaluation(side_a=side_a, side_b=side_b)
    assert eval.secondary_value_a is None
    assert eval.secondary_value_b is None
    assert eval.secondary_delta is None
    assert eval.secondary_pct_diff is None
    assert eval.ktc_value_a is None
    assert eval.ktc_value_b is None
    assert eval.ktc_delta is None
    assert eval.ktc_pct_diff is None
    assert eval.dealer_value_a is None
    assert eval.dealer_value_b is None
    assert eval.dealer_delta is None
    assert eval.dealer_pct_diff is None
    assert eval.secondary_is_fair() is False
    assert eval.secondary_arbitrage_label() is None
    assert eval.arbitrage_label() is None
    assert eval.ktc_arbitrage_label() is None
    assert eval.dealer_arbitrage_label() is None


def test_trade_evaluation_secondary_is_fair():
    # 3% difference -> fair at default 5%
    side_a = TradeSide(assets=[Asset(id="1", name="A", value=1000, secondary_value=1000)])
    side_b = TradeSide(assets=[Asset(id="2", name="B", value=1000, secondary_value=970)])
    eval = TradeEvaluation(side_a=side_a, side_b=side_b)
    assert eval.secondary_is_fair() is True
    assert eval.ktc_is_fair() is True
    assert eval.dealer_is_fair() is True
    assert eval.secondary_is_fair(threshold_pct=2.0) is False
    assert eval.ktc_is_fair(threshold_pct=2.0) is False
    assert eval.dealer_is_fair(threshold_pct=2.0) is False


def test_arbitrage_classifications():
    # 1. Consensus Win (FC +, Secondary +)
    side_a = TradeSide(assets=[Asset(id="1", name="A", value=2000, secondary_value=2000)])
    side_b = TradeSide(assets=[Asset(id="2", name="B", value=1000, secondary_value=1000)])
    assert TradeEvaluation(side_a=side_a, side_b=side_b).arbitrage_label() == "Consensus Win"
    assert TradeEvaluation(side_a=side_a, side_b=side_b).secondary_arbitrage_label() == "Consensus Win"

    # 2. Consensus Loss (FC -, Secondary -)
    side_a = TradeSide(assets=[Asset(id="1", name="A", value=1000, secondary_value=1000)])
    side_b = TradeSide(assets=[Asset(id="2", name="B", value=2000, secondary_value=2000)])
    assert TradeEvaluation(side_a=side_a, side_b=side_b).arbitrage_label() == "Consensus Loss"
    assert TradeEvaluation(side_a=side_a, side_b=side_b).secondary_arbitrage_label() == "Consensus Loss"

    # 3. Value Arbitrage (FC +, Secondary - or neutral)
    side_a = TradeSide(assets=[Asset(id="1", name="A", value=2000, secondary_value=1000)])
    side_b = TradeSide(assets=[Asset(id="2", name="B", value=1000, secondary_value=2000)])
    assert TradeEvaluation(side_a=side_a, side_b=side_b).arbitrage_label() == "Value Arbitrage"
    assert TradeEvaluation(side_a=side_a, side_b=side_b).secondary_arbitrage_label() == "Value Arbitrage"

    # 4. Hype Arbitrage (FC - or neutral, Secondary +)
    side_a = TradeSide(assets=[Asset(id="1", name="A", value=1000, secondary_value=2000)])
    side_b = TradeSide(assets=[Asset(id="2", name="B", value=2000, secondary_value=1000)])
    assert TradeEvaluation(side_a=side_a, side_b=side_b).arbitrage_label() == "Hype Arbitrage"
    assert TradeEvaluation(side_a=side_a, side_b=side_b).secondary_arbitrage_label() == "Hype Arbitrage"

    # 5. Fair (both within threshold)
    side_a = TradeSide(assets=[Asset(id="1", name="A", value=1000, secondary_value=1000)])
    side_b = TradeSide(assets=[Asset(id="2", name="B", value=1000, secondary_value=1000)])
    assert TradeEvaluation(side_a=side_a, side_b=side_b).arbitrage_label() == "Fair"
    assert TradeEvaluation(side_a=side_a, side_b=side_b).secondary_arbitrage_label() == "Fair"


def test_arbitrage_mover_secondary_value():
    asset = Asset(id="1", name="Bijan Robinson", value=7000, secondary_value=7500)
    mover = ArbitrageMover(asset=asset)
    assert mover.fc_value == 7000
    assert mover.secondary_value == 7500
    assert mover.ktc_value == 7500
    assert mover.dealer_value == 7500
    assert mover.diff == 500
    assert mover.market_bias == "Dealer"


def test_arbitrage_mover_legacy_ktc_init():
    asset = Asset(id="1", name="Bijan Robinson", value=7000)
    mover = ArbitrageMover(asset=asset, ktc_value=7500)
    assert mover.secondary_value == 7500
    assert mover.ktc_value == 7500
    assert mover.dealer_value == 7500
    assert mover.diff == 500
    assert mover.market_bias == "Dealer"


def test_arbitrage_mover_dealer_init():
    asset = Asset(id="1", name="Bijan Robinson", value=7000)
    mover = ArbitrageMover(asset=asset, dealer_value=7500)
    assert mover.secondary_value == 7500
    assert mover.ktc_value == 7500
    assert mover.dealer_value == 7500
    assert mover.diff == 500
    assert mover.market_bias == "Dealer"


def test_arbitrage_mover_property_setters():
    asset = Asset(id="1", name="Bijan Robinson", value=7000)
    mover = ArbitrageMover(asset=asset, secondary_value=7500)
    mover.ktc_value = 8000
    assert mover.secondary_value == 8000
    assert mover.ktc_value == 8000
    assert mover.dealer_value == 8000

    mover.dealer_value = 8500
    assert mover.secondary_value == 8500
    assert mover.ktc_value == 8500
    assert mover.dealer_value == 8500


def test_arbitrage_mover_market_bias_classes():
    # Dealer bias (secondary > fc)
    m1 = ArbitrageMover(asset=Asset(id="1", name="A", value=1000, secondary_value=1500))
    assert m1.market_bias == "Dealer"

    # FC bias (fc > secondary)
    m2 = ArbitrageMover(asset=Asset(id="2", name="B", value=2000, secondary_value=1500))
    assert m2.market_bias == "FC"

    # EVEN bias
    m3 = ArbitrageMover(asset=Asset(id="3", name="C", value=1000, secondary_value=1000))
    assert m3.market_bias == "EVEN"

    # Explicit bias preserved
    m4 = ArbitrageMover(asset=Asset(id="4", name="D", value=1000, secondary_value=1500), market_bias="Dealer")
    assert m4.market_bias == "Dealer"


def test_asset_injury_and_depth_tags():
    # Healthy starter
    a1 = Asset(id="1", name="Bijan Robinson", position="RB", depth_chart_order=1)
    assert a1.depth_tag == "RB1"
    assert a1.injury_tag == ""
    assert a1.status_label == "RB1"

    # Injured backup with body part
    a2 = Asset(id="2", name="James Conner", position="RB", depth_chart_order=3,
               injury_status="Questionable", injury_body_part="Foot")
    assert a2.depth_tag == "RB3"
    assert a2.injury_tag == "[Q - Foot]"
    assert a2.status_label == "RB3 [Q - Foot]"

    # IR player
    a3 = Asset(id="3", name="Injured Guy", position="WR", depth_chart_order=2,
               status="Injured Reserve", injury_status="IR")
    assert a3.depth_tag == "WR2"
    assert a3.injury_tag == "[IR]"
    assert a3.status_label == "WR2 [IR]"

    # Pick has no depth tag or injury tag
    pick = Asset(id="2027 1st", name="2027 1st", kind="pick", position="PICK")
    assert pick.depth_tag == ""
    assert pick.injury_tag == ""
    assert pick.status_label == ""
