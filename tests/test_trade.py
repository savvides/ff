from ff.analysis import analyze_trade, evaluate_trade, ktc_position_deltas, position_deltas
from ff.contracts import Asset
from ff.values import ValueBook


def make_mock_multi_market_book() -> ValueBook:
    return ValueBook([
        Asset(id="1", name="Player A", position="WR", value=2000, ktc_value=2500),
        Asset(id="2", name="Player B", position="RB", value=1500, ktc_value=1200),
        Asset(id="3", name="Player C", position="QB", value=3000, ktc_value=2000),
        Asset(id="4", name="Player D", position="TE", value=1000, ktc_value=1800),
    ])


def test_trade_with_players_and_picks(book):
    # You give Gibbs + a 2026 2nd; you get Bijan + a 2027 1st.
    evaluation, unresolved = analyze_trade(
        side_a_tokens=["Bijan Robinson", "2027 1st"],   # you get
        side_b_tokens=["Jahmyr Gibbs", "2026 2nd"],      # you give
        book=book,
        labels=("You get", "You give"),
    )
    assert not unresolved
    assert evaluation.value_a == 12000   # 9000 + 3000
    assert evaluation.value_b == 9500    # 8000 + 1500
    assert evaluation.delta == 2500
    assert round(evaluation.pct_diff) == 21
    assert evaluation.winner() == "You get"
    assert evaluation.is_fair(threshold_pct=5) is False
    assert evaluation.is_fair(threshold_pct=25) is True


def test_trade_unresolved_surfaced(book):
    evaluation, unresolved = analyze_trade(
        ["Bijan Robinson"], ["Madeup Guy"], book
    )
    assert unresolved == ["Madeup Guy"]
    assert evaluation.value_b == 0   # unmatched asset contributes nothing


def test_even_trade_is_fair(book):
    evaluation, _ = analyze_trade(["Bijan Robinson"], ["Bijan Robinson"], book)
    assert evaluation.delta == 0
    assert evaluation.winner() == "even"
    assert evaluation.is_fair()


def test_position_deltas(book):
    evaluation, _ = analyze_trade(
        ["Bijan Robinson"], ["Ja'Marr Chase"], book  # get RB, give WR
    )
    deltas = position_deltas(evaluation)
    assert deltas["RB"] == 9000
    assert deltas["WR"] == -9500


def test_trade_with_dual_market():
    book = make_mock_multi_market_book()
    eval = evaluate_trade(give=["Player B"], get=["Player A"], book=book)
    assert eval.ktc_delta is not None
    assert eval.arbitrage_label() in ["Consensus Win", "Hype Arbitrage", "Value Arbitrage", "Consensus Loss", "Fair"]
    assert eval.delta == 500
    assert eval.ktc_delta == 1300
    assert eval.arbitrage_label() == "Consensus Win"


def test_evaluate_trade_parameter_aliases():
    book = make_mock_multi_market_book()
    # Test (give, get, book)
    e1 = evaluate_trade(give=["Player B"], get=["Player A"], book=book)
    # Test (give_inputs, get_inputs, book)
    e2 = evaluate_trade(give_inputs=["Player B"], get_inputs=["Player A"], book=book)
    # Test positional (give_inputs, get_inputs, book)
    e3 = evaluate_trade(["Player B"], ["Player A"], book)
    assert e1.delta == e2.delta == e3.delta == 500
    assert e1.ktc_delta == e2.ktc_delta == e3.ktc_delta == 1300


def test_evaluate_trade_include_ktc_false():
    book = make_mock_multi_market_book()
    eval = evaluate_trade(give=["Player B"], get=["Player A"], book=book, include_ktc=False)
    assert eval.delta == 500
    assert eval.ktc_delta is None
    assert eval.arbitrage_label() is None


def test_trade_arbitrage_classifications_in_evaluation():
    book = ValueBook([
        Asset(id="1", name="Hype Buy", value=1000, ktc_value=2000),
        Asset(id="2", name="Hype Sell", value=2000, ktc_value=1000),
        Asset(id="3", name="Value Buy", value=2000, ktc_value=1000),
        Asset(id="4", name="Value Sell", value=1000, ktc_value=2000),
        Asset(id="5", name="Fair A", value=1000, ktc_value=1000),
        Asset(id="6", name="Fair B", value=1000, ktc_value=1000),
    ])
    # Hype Arbitrage: You get Hype Buy (FC 1000, KTC 2000) for Hype Sell (FC 2000, KTC 1000)
    eval_hype = evaluate_trade(give=["Hype Sell"], get=["Hype Buy"], book=book)
    assert eval_hype.arbitrage_label() == "Hype Arbitrage"

    # Value Arbitrage: You get Value Buy (FC 2000, KTC 1000) for Value Sell (FC 1000, KTC 2000)
    eval_val = evaluate_trade(give=["Value Sell"], get=["Value Buy"], book=book)
    assert eval_val.arbitrage_label() == "Value Arbitrage"

    # Fair:
    eval_fair = evaluate_trade(give=["Fair B"], get=["Fair A"], book=book)
    assert eval_fair.arbitrage_label() == "Fair"


def test_ktc_position_deltas():
    book = make_mock_multi_market_book()
    # Get Player A (WR 2500 KTC), Give Player B (RB 1200 KTC)
    eval = evaluate_trade(give=["Player B"], get=["Player A"], book=book)
    deltas = ktc_position_deltas(eval)
    assert deltas["WR"] == 2500
    assert deltas["RB"] == -1200


def test_trade_enriches_player_metadata():
    book = ValueBook([
        Asset(id="8138", name="Bijan Robinson", position="RB", value=9000),
        Asset(id="4137", name="James Conner", position="RB", value=600),
    ])
    players_meta = {
        "8138": {"full_name": "Bijan Robinson", "position": "RB", "depth_chart_order": 1},
        "4137": {"full_name": "James Conner", "position": "RB", "depth_chart_order": 3, "injury_status": "Questionable", "injury_body_part": "Foot"},
    }
    eval, _ = analyze_trade(
        side_a_tokens=["Bijan Robinson"],
        side_b_tokens=["James Conner"],
        book=book,
        players_meta=players_meta,
    )
    bijan = eval.side_a.assets[0]
    assert bijan.depth_tag == "RB1"
    assert bijan.injury_tag == ""

    conner = eval.side_b.assets[0]
    assert conner.depth_tag == "RB3"
    assert conner.injury_tag == "[Q - Foot]"
    assert conner.status_label == "RB3 [Q - Foot]"


