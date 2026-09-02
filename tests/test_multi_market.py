"""Comprehensive multi-market integration & gate verification test suite.

Covers:
- End-to-end multi-market trade evaluation across players and tiered picks
- Offline degradation, network failure resilience, and malformed payload handling
- Unmapped asset handling (missing players/picks in secondary market, asymmetric trade sides)
- Pick tier resolution (early/mid/late) under dual markets and draft ledger integration
- Arbitrage classification boundaries, 2D decision matrix, and extreme delta thresholds
- Secondary market arbitrage scanner / movers ranking, market filtering, and roster attribution
- End-to-end CLI integration for multi-market trade, values, and movers commands
"""

from unittest.mock import patch
import pytest
import requests
from typer.testing import CliRunner

from ff.analysis import (
    analyze_trade,
    evaluate_trade,
    find_arbitrage_movers,
    ktc_position_deltas,
    pick_ledger,
    pick_tier,
    position_deltas,
    price_pick,
)
from ff.cli import app
from ff.contracts import Asset, Format, FuturePick, Roster, TradeEvaluation, TradeSide
from ff.core.config import Config, save_config
from ff.sleeper import build_rosters, detect_format
from ff.values import ValueBook, ValuesClient
from ff.values.client import _asset_from_entry, normalize_pick


# =============================================================================
# 1. End-to-End Multi-Market Trade Evaluation
# =============================================================================


def test_e2e_multi_market_trade_evaluation_mixed_assets(multi_market_book):
    """Evaluate a realistic trade with elite players and tiered future picks."""
    # Side A (You get): Bijan Robinson (FC 9000, KTC 8900) + 2027 1st Early (FC 4200, KTC 4500)
    # Side B (You give): Jahmyr Gibbs (FC 8000, KTC 8400) + 2026 1st (FC 4000, KTC 4100) + 2027 2nd (FC 1400, KTC 1450)
    evaluation, unresolved = analyze_trade(
        side_a_tokens=["Bijan Robinson", "2027 1st (Early)"],
        side_b_tokens=["Jahmyr Gibbs", "2026 1st", "2027 2nd"],
        book=multi_market_book,
        labels=("You get", "You give"),
    )

    assert not unresolved
    # FC values
    assert evaluation.value_a == 9000 + 4200  # 13200
    assert evaluation.value_b == 8000 + 4000 + 1400  # 13400
    assert evaluation.delta == -200
    assert round(evaluation.pct_diff, 2) == round(200 / 13400 * 100, 2)
    assert evaluation.is_fair(threshold_pct=5.0) is True

    # KTC values
    assert evaluation.ktc_value_a == 8900 + 4500  # 13400
    assert evaluation.ktc_value_b == 8400 + 4100 + 1450  # 13950
    assert evaluation.ktc_delta == -550
    assert round(evaluation.ktc_pct_diff, 2) == round(550 / 13950 * 100, 2)

    # Position deltas
    fc_deltas = position_deltas(evaluation)
    assert fc_deltas["RB"] == 9000 - 8000  # +1000
    assert fc_deltas["PICK"] == 4200 - (4000 + 1400)  # -1200

    ktc_deltas = ktc_position_deltas(evaluation)
    assert ktc_deltas["RB"] == 8900 - 8400  # +500
    assert ktc_deltas["PICK"] == 4500 - (4100 + 1450)  # -1050

    # Both markets within 5% threshold -> Fair
    assert evaluation.arbitrage_label() == "Fair"


def test_e2e_multi_market_evaluate_trade_helper(multi_market_book):
    """evaluate_trade helper produces full multi-market evaluation."""
    eval_res = evaluate_trade(
        give=["Josh Allen"],  # FC 7000, KTC 7200
        get=["Ja'Marr Chase"],  # FC 9500, KTC 9600
        book=multi_market_book,
    )
    assert eval_res.delta == 2500  # 9500 - 7000
    assert eval_res.ktc_delta == 2400  # 9600 - 7200
    assert eval_res.winner() == "You get"
    assert eval_res.arbitrage_label() == "Consensus Win"


# =============================================================================
# 2. Offline Degradation & Network Resilience
# =============================================================================


def test_offline_degradation_ktc_network_error():
    """ValuesClient degrades gracefully when secondary endpoint raises network errors."""
    fc_entries = [
        {"player": {"sleeperId": "7564", "name": "Ja'Marr Chase", "position": "WR"}, "value": 9500},
        {"player": {"sleeperId": "8138", "name": "Bijan Robinson", "position": "RB"}, "value": 9000},
    ]

    for exception in [
        requests.exceptions.ConnectTimeout("Connection timed out"),
        requests.exceptions.ConnectionError("Failed to establish a new connection"),
        requests.exceptions.HTTPError("500 Server Error: Internal Server Error"),
        requests.exceptions.ReadTimeout("Read timed out"),
    ]:
        with patch("ff.values.client.get_json", return_value=fc_entries), \
             patch("ff.values.dealer.get_json", side_effect=exception):
            client = ValuesClient()
            book = client.fetch(Format(), include_ktc=True)

            chase = book.resolve("Ja'Marr Chase")
            assert chase is not None
            assert chase.value == 9500
            assert chase.ktc_value is None

            # Trade evaluation works in single-market fallback mode
            eval_res = evaluate_trade(give=["Bijan Robinson"], get=["Ja'Marr Chase"], book=book)
            assert eval_res.delta == 500
            assert eval_res.ktc_delta is None
            assert eval_res.arbitrage_label() is None


def test_offline_degradation_ktc_malformed_payloads():
    """ValuesClient handles non-standard, malformed, or empty payloads from secondary API."""
    fc_entries = [
        {"player": {"sleeperId": "7564", "name": "Ja'Marr Chase", "position": "WR"}, "value": 9500},
    ]

    malformed_responses = [
        "Internal Server Error (raw text)",
        None,
        False,
        12345,
        {"status": "error", "message": "Rate limit exceeded"},
        {"players": [{"corrupt_entry": True}]},  # Missing ID and name
        {"players": [{"sleeper_id": "7564", "current_value": "invalid_number"}]},  # Non-integer value
    ]

    for bad_resp in malformed_responses:
        with patch("ff.values.client.get_json", return_value=fc_entries), \
             patch("ff.values.dealer.get_json", return_value=bad_resp):
            client = ValuesClient()
            book = client.fetch(Format(), include_ktc=True)
            chase = book.resolve("Ja'Marr Chase")
            assert chase is not None
            assert chase.value == 9500
            assert chase.ktc_value is None


def test_include_ktc_false_skips_secondary_market():
    """When include_ktc=False, secondary market is not contacted and values are single-market."""
    fc_entries = [
        {"player": {"sleeperId": "7564", "name": "Ja'Marr Chase", "position": "WR"}, "value": 9500},
    ]
    with patch("ff.values.client.get_json", return_value=fc_entries), \
         patch("ff.values.dealer.DynastyDealerClient.fetch_values") as mock_dealer_fetch:
        client = ValuesClient()
        book = client.fetch(Format(), include_ktc=False)
        mock_dealer_fetch.assert_not_called()
        chase = book.resolve("Ja'Marr Chase")
        assert chase is not None
        assert chase.value == 9500
        assert chase.ktc_value is None



# =============================================================================
# 3. Unmapped Assets & Partial Coverage
# =============================================================================


def test_unmapped_assets_in_trade_evaluation():
    """Handles assets missing from secondary market and asymmetric KTC coverage."""
    book = ValueBook([
        Asset(id="1", name="Mapped Player A", position="WR", value=5000, ktc_value=5500),
        Asset(id="2", name="Unmapped Player B", position="RB", value=3000, ktc_value=None),
        Asset(id="3", name="Mapped Player C", position="QB", value=7000, ktc_value=6800),
        Asset(id="4", name="Unmapped Player D", position="TE", value=2000, ktc_value=None),
    ])

    # Side A has 1 mapped + 1 unmapped; Side B has 1 mapped
    # Side A: Mapped Player A (5000 FC, 5500 KTC) + Unmapped Player B (3000 FC, None KTC)
    # Side B: Mapped Player C (7000 FC, 6800 KTC)
    eval_res = evaluate_trade(
        give=["Mapped Player C"],
        get=["Mapped Player A", "Unmapped Player B"],
        book=book,
    )
    assert eval_res.value_a == 8000
    assert eval_res.value_b == 7000
    assert eval_res.delta == 1000
    # KTC totals: Side A includes mapped (5500), Side B has (6800)
    assert eval_res.ktc_value_a == 5500
    assert eval_res.ktc_value_b == 6800
    assert eval_res.ktc_delta == -1300
    assert eval_res.arbitrage_label() == "Value Arbitrage"  # FC win (+1000), KTC loss (-1300)


def test_completely_unmapped_side_returns_none_for_ktc():
    """When an entire side has no KTC values, KTC trade metrics degrade to None."""
    book = ValueBook([
        Asset(id="1", name="Mapped Player A", position="WR", value=5000, ktc_value=5500),
        Asset(id="2", name="Unmapped Player B", position="RB", value=3000, ktc_value=None),
    ])

    eval_res = evaluate_trade(
        give=["Unmapped Player B"],
        get=["Mapped Player A"],
        book=book,
    )
    assert eval_res.value_a == 5000
    assert eval_res.value_b == 3000
    assert eval_res.delta == 2000
    assert eval_res.ktc_value_a == 5500
    assert eval_res.ktc_value_b is None
    assert eval_res.ktc_delta is None
    assert eval_res.ktc_pct_diff is None
    assert eval_res.arbitrage_label() is None


def test_unmapped_draft_picks_in_value_book():
    """Unmapped draft picks retain FC value with ktc_value=None."""
    fc_entry = {"player": {"id": 200, "name": "2029 4th", "position": "PICK"}, "value": 300}
    ktc_map = {"2027 1": 3200}

    asset = _asset_from_entry(fc_entry, ktc_map=ktc_map)
    assert asset.id == "2029 4"
    assert asset.value == 300
    assert asset.ktc_value is None


# =============================================================================
# 4. Pick Tier Resolution Under Dual Markets
# =============================================================================


def test_pick_tier_resolution_with_dual_market(fc_entries, dealer_map):
    """Canonical pick normalization matches tiered entries across FC and secondary market."""
    book = ValueBook([_asset_from_entry(e, secondary_map=dealer_map) for e in fc_entries])


    # 2027 1st (Early) -> "2027 1 early"
    early_pick = book.resolve("2027 1st (Early)")
    assert early_pick is not None
    assert early_pick.value == 4200
    assert early_pick.ktc_value == 4500

    # 2027 1st (Mid) -> "2027 1 mid"
    mid_pick = book.resolve("2027 1st (Mid)")
    assert mid_pick is not None
    assert mid_pick.value == 3100
    assert mid_pick.ktc_value == 3300

    # 2027 1st (Late) -> "2027 1 late"
    late_pick = book.resolve("2027 1st (Late)")
    assert late_pick is not None
    assert late_pick.value == 2400
    assert late_pick.ktc_value == 2500

    # Generic "2027 1st" resolves to mid tier when only tiered entries exist
    generic_pick = book.resolve("2027 1st")
    assert generic_pick is not None
    # In fantasycalc_sf fixture, there is a flat "2027 1st" entry with value 3000, KTC 3200
    assert generic_pick.value in (3000, 3100)
    assert generic_pick.ktc_value in (3200, 3300)


def test_pick_tier_ledger_integration(rosters_raw, users_raw, traded_picks, multi_market_book):
    """pick_ledger reconciles future pick ownership and applies tier valuation."""
    rosters = build_rosters(rosters_raw, users_raw)
    ranks = {1: 2, 2: 1, 3: 3}  # Roster 2: #1 (late), Roster 1: #2 (mid), Roster 3: #3 (early)

    ledger = pick_ledger(
        rosters=rosters,
        traded_picks=traded_picks,
        book=multi_market_book,
        power_ranks=ranks,
        seasons=["2027", "2028"],
        rounds=2,
    )

    warriors = next(t for t in ledger if t.roster_id == 1)
    by_key = {(p.season, p.round, p.original_roster_id): p for p in warriors.picks}

    # Own 2027 1st: rank 2 -> mid tier
    own_1st = by_key[("2027", 1, 1)]
    assert own_1st.tier == "mid"
    assert own_1st.value == 3100

    # Gridiron's 2027 1st: rank 1 -> late tier
    gridiron_1st = by_key[("2027", 1, 2)]
    assert gridiron_1st.tier == "late"
    assert gridiron_1st.value == 2400

    # Carol's 2027 2nd: flat round value (no tiered 2nd in fixture)
    carol_2nd = by_key[("2027", 2, 3)]
    assert carol_2nd.tier is None
    assert carol_2nd.value == 1400


# =============================================================================
# 5. Arbitrage Classification Boundaries & 2D Decision Matrix
# =============================================================================


@pytest.mark.parametrize(
    "fc_a,fc_b,ktc_a,ktc_b,threshold,expected_label",
    [
        # Consensus Win: FC Win (> threshold) and KTC Win (> threshold)
        (3000, 2000, 3000, 2000, 5.0, "Consensus Win"),
        (2500, 2000, 2600, 2000, 5.0, "Consensus Win"),

        # Consensus Loss: FC Loss (<-threshold) and KTC Loss (<-threshold)
        (2000, 3000, 2000, 3000, 5.0, "Consensus Loss"),
        (2000, 2500, 2000, 2600, 5.0, "Consensus Loss"),

        # Value Arbitrage: FC Win and KTC Loss
        (3000, 2000, 2000, 3000, 5.0, "Value Arbitrage"),
        # Value Arbitrage: FC Win and KTC Fair
        (3000, 2000, 2000, 2000, 5.0, "Value Arbitrage"),

        # Hype Arbitrage: FC Loss and KTC Win
        (2000, 3000, 3000, 2000, 5.0, "Hype Arbitrage"),
        # Hype Arbitrage: FC Fair and KTC Win
        (2000, 2000, 3000, 2000, 5.0, "Hype Arbitrage"),

        # Fair: Both FC and KTC within threshold
        (2000, 2000, 2000, 2000, 5.0, "Fair"),
        (2050, 2000, 2040, 2000, 5.0, "Fair"),  # 2.4% diff <= 5%

        # Consensus Loss: FC Loss and KTC Fair
        (2000, 3000, 2000, 2000, 5.0, "Consensus Loss"),
        # Consensus Loss: FC Fair and KTC Loss
        (2000, 2000, 2000, 3000, 5.0, "Consensus Loss"),
    ],
)
def test_arbitrage_decision_matrix(fc_a, fc_b, ktc_a, ktc_b, threshold, expected_label):
    """Exhaustively verify the 2D decision matrix of arbitrage labels."""
    side_a = TradeSide(assets=[Asset(id="1", name="Asset A", value=fc_a, ktc_value=ktc_a)])
    side_b = TradeSide(assets=[Asset(id="2", name="Asset B", value=fc_b, ktc_value=ktc_b)])
    eval_res = TradeEvaluation(side_a=side_a, side_b=side_b)
    assert eval_res.arbitrage_label(threshold_pct=threshold) == expected_label


def test_arbitrage_threshold_boundary_precision():
    """Verify behavior at exact threshold boundaries (e.g. 5.00% vs 5.01%)."""
    # Exactly 5% of larger: 2000 vs 1900 -> larger=2000, delta=100 -> 100/2000 = 5.00% (<= 5.0%)
    side_a = TradeSide(assets=[Asset(id="1", name="A", value=2000, ktc_value=2000)])
    side_b = TradeSide(assets=[Asset(id="2", name="B", value=1900, ktc_value=1900)])
    eval_res = TradeEvaluation(side_a=side_a, side_b=side_b)
    assert eval_res.pct_diff == 5.0
    assert eval_res.is_fair(threshold_pct=5.0) is True
    assert eval_res.arbitrage_label(threshold_pct=5.0) == "Fair"

    # 5.05% of larger: 2000 vs 1899 -> larger=2000, delta=101 -> 101/2000 = 5.05% (> 5.0%)
    side_b_uneven = TradeSide(assets=[Asset(id="2", name="B", value=1899, ktc_value=1899)])
    eval_uneven = TradeEvaluation(side_a=side_a, side_b=side_b_uneven)
    assert eval_uneven.pct_diff > 5.0
    assert eval_uneven.is_fair(threshold_pct=5.0) is False
    assert eval_uneven.arbitrage_label(threshold_pct=5.0) == "Consensus Win"


# =============================================================================
# 6. Extreme Market Delta Thresholds
# =============================================================================


def test_extreme_market_delta_thresholds():
    """Handle edge cases like empty baskets, 100% blowout trades, and huge disparities."""
    # 1. Empty trade (0 vs 0)
    empty_eval = TradeEvaluation(
        side_a=TradeSide(assets=[]),
        side_b=TradeSide(assets=[]),
    )
    assert empty_eval.value_a == 0
    assert empty_eval.value_b == 0
    assert empty_eval.delta == 0
    assert empty_eval.pct_diff == 0.0
    assert empty_eval.winner() == "even"
    assert empty_eval.is_fair() is True
    assert empty_eval.ktc_value_a is None
    assert empty_eval.arbitrage_label() is None

    # 2. Total blowout (asset vs nothing: 10,000 vs 0)
    blowout_eval = TradeEvaluation(
        side_a=TradeSide(assets=[Asset(id="1", name="Elite", value=10000, ktc_value=12000)]),
        side_b=TradeSide(assets=[]),
    )
    assert blowout_eval.value_a == 10000
    assert blowout_eval.value_b == 0
    assert blowout_eval.delta == 10000
    assert blowout_eval.pct_diff == 100.0
    assert blowout_eval.ktc_value_a == 12000
    assert blowout_eval.ktc_value_b is None
    assert blowout_eval.arbitrage_label() is None

    # 3. Massive asymmetry (10,000 vs 10)
    asym_eval = TradeEvaluation(
        side_a=TradeSide(assets=[Asset(id="1", name="Stud", value=10000, ktc_value=10000)]),
        side_b=TradeSide(assets=[Asset(id="2", name="Scrub", value=10, ktc_value=10)]),
    )
    assert round(asym_eval.pct_diff, 2) == 99.90
    assert asym_eval.arbitrage_label() == "Consensus Win"

    # 4. Extreme cross-market inversion (FC: 10000 vs 1000, KTC: 1000 vs 10000)
    invert_eval = TradeEvaluation(
        side_a=TradeSide(assets=[Asset(id="1", name="A", value=10000, ktc_value=1000)]),
        side_b=TradeSide(assets=[Asset(id="2", name="B", value=1000, ktc_value=10000)]),
    )
    assert invert_eval.delta == 9000
    assert invert_eval.ktc_delta == -9000
    assert invert_eval.arbitrage_label() == "Value Arbitrage"


# =============================================================================
# 7. Secondary Market Arbitrage Scanner (Movers)
# =============================================================================


def test_arbitrage_movers_scanner_ranking_and_filters(multi_market_book, rosters_raw, users_raw):
    """Scanner ranks discrepancies by absolute delta, supports market filters and roster mapping."""
    rosters = build_rosters(rosters_raw, users_raw)

    # 1. Full scan with rosters attached
    all_movers = find_arbitrage_movers(rosters, multi_market_book, min_value=1000)
    assert len(all_movers) > 0
    # Ranked by abs(diff) descending
    for i in range(len(all_movers) - 1):
        assert abs(all_movers[i].diff) >= abs(all_movers[i + 1].diff)

    # 2. Filter market='ktc' (assets where secondary > FC)
    ktc_movers = find_arbitrage_movers(rosters, multi_market_book, market="ktc", min_value=1000)
    assert all(m.diff > 0 for m in ktc_movers)
    assert all(m.market_bias in ("Dealer", "KTC") for m in ktc_movers)

    # 3. Filter market='fc' (assets where FC > secondary)
    fc_movers = find_arbitrage_movers(rosters, multi_market_book, market="fc", min_value=1000)
    assert all(m.diff < 0 for m in fc_movers)
    assert all(m.market_bias == "FC" for m in fc_movers)


    # 4. min_value threshold filtering
    high_floor_movers = find_arbitrage_movers(rosters, multi_market_book, min_value=8000)
    assert all(max(m.fc_value, m.ktc_value) >= 8000 for m in high_floor_movers)


# =============================================================================
# 8. End-to-End CLI Integration with Multi-Market
# =============================================================================


def test_cli_e2e_multi_market_trade_and_arbitrage(monkeypatch, multi_market_book, league, rosters_raw, users_raw, players_meta):
    """Verify CLI commands render dual-market columns and arbitrage badges end-to-end."""
    runner = CliRunner()

    class FakeSleeper:
        def state(self, sport="nfl"):
            return {"season": "2026", "previous_season": "2025"}

        def user(self, u):
            return {"user_id": "userA", "username": u}

        def user_leagues(self, uid, season, sport="nfl"):
            return [league]

        def league(self, lid):
            return league

        def rosters(self, lid):
            return rosters_raw

        def league_users(self, lid):
            return users_raw

        def players(self, sport="nfl"):
            return players_meta

    class FakeValues:
        def fetch(self, fmt, include_ktc=True):
            return multi_market_book

    monkeypatch.setattr("ff.cli.SleeperClient", lambda *a, **k: FakeSleeper())
    monkeypatch.setattr("ff.cli.ValuesClient", lambda *a, **k: FakeValues())
    monkeypatch.setenv("COLUMNS", "200")

    save_config(Config(
        league_id="LG1", season="2026", name="Test Dynasty",
        format=detect_format(league), username="alice", user_id="userA",
    ))

    # 1. ff trade command with dual market
    trade_res = runner.invoke(app, ["trade", "--give", "Jahmyr Gibbs", "--get", "Bijan Robinson,2027 1st (Early)"])
    assert trade_res.exit_code == 0, trade_res.output
    assert "FC" in trade_res.output
    assert ("Dealer" in trade_res.output or "KTC" in trade_res.output)
    assert "Consensus Win" in trade_res.output or "Fair" in trade_res.output

    # 2. ff movers --arbitrage
    movers_res = runner.invoke(app, ["movers", "--arbitrage"])
    assert movers_res.exit_code == 0, movers_res.output
    assert "FC" in movers_res.output
    assert ("Dealer" in movers_res.output or "KTC" in movers_res.output)
    assert "DIFF" in movers_res.output.upper()

    # 3. ff values with WR position
    values_res = runner.invoke(app, ["values", "-p", "WR"])
    assert values_res.exit_code == 0, values_res.output
    assert "FC" in values_res.output
    assert ("Dealer" in values_res.output or "KTC" in values_res.output)
