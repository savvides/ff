"""Trade analyzer: the headline feature."""

from ff.analysis import analyze_trade, position_deltas


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
