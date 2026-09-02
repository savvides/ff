"""Unit tests for domain invariant validators."""

import pytest
from ff.contracts import (
    Asset,
    DraftFit,
    DraftPickInfo,
    Format,
    FuturePick,
    Lineup,
    LineupSlot,
    NewsItem,
    Roster,
    RosterAudit,
    RosterSlot,
    RosterValuation,
    TeamContext,
    TeamPicks,
    TradeEvaluation,
    TradeSide,
    WaiverTarget,
    ArbitrageMover,
)
from ff.core.config import Config
from ff.qa.validators import (
    validate_ask,
    validate_cleanup,
    validate_draft,
    validate_lineup,
    validate_movers,
    validate_news,
    validate_picks,
    validate_power,
    validate_roster,
    validate_setup,
    validate_trade,
    validate_values,
    validate_waivers,
)


def test_validate_setup_valid():
    cfg = Config(
        league_id="12345",
        season="2026",
        name="Test Dynasty",
        format=Format(superflex=True, ppr=1.0, num_teams=12, tep=0.5),
        username="alice",
        user_id="u1",
    )
    checks = validate_setup(cfg)
    assert all(c.passed for c in checks)


def test_validate_setup_invalid():
    cfg = Config(
        league_id="",
        season="2026",
        name="Test Dynasty",
        format=Format(superflex=True, ppr=-1.0, num_teams=1, tep=-0.5),
        username="",
        user_id="",
    )
    checks = validate_setup(cfg)
    failed = [c for c in checks if not c.passed]
    assert len(failed) >= 3


def test_validate_roster_valid():
    a1 = Asset(id="1", name="Player 1", value=5000, position="QB")
    a2 = Asset(id="2", name="Player 2", value=3000, position="WR")
    val = RosterValuation(
        roster_id=1,
        team_name="Team A",
        total_value=8000,
        starters_value=5000,
        power_rank=1,
        by_position={"QB": 5000, "WR": 3000},
        assets=[a1, a2],
    )
    roster = Roster(roster_id=1, team_name="Team A", player_ids=["1", "2"])
    checks = validate_roster(val, roster)
    assert all(c.passed for c in checks)


def test_validate_roster_total_mismatch():
    a1 = Asset(id="1", name="Player 1", value=5000, position="QB")
    a2 = Asset(id="2", name="Player 2", value=3000, position="WR")
    val = RosterValuation(
        roster_id=1,
        team_name="Team A",
        total_value=9999,  # Mismatch!
        starters_value=12000,  # Starters > total!
        power_rank=0,  # Invalid rank!
        by_position={"QB": 5000, "WR": 1000},
        assets=[a1, a2],
    )
    checks = validate_roster(val)
    failed = [c for c in checks if not c.passed]
    assert len(failed) >= 2


def test_validate_power_valid():
    v1 = RosterValuation(roster_id=1, team_name="Team A", total_value=10000, power_rank=1)
    v2 = RosterValuation(roster_id=2, team_name="Team B", total_value=8000, power_rank=2)
    r1 = Roster(roster_id=1, team_name="Team A", wins=10, losses=2)
    r2 = Roster(roster_id=2, team_name="Team B", wins=5, losses=7)
    checks = validate_power([v1, v2], [r1, r2])
    assert all(c.passed for c in checks)


def test_validate_power_rank_out_of_order():
    v1 = RosterValuation(roster_id=1, team_name="Team A", total_value=5000, power_rank=1)
    v2 = RosterValuation(roster_id=2, team_name="Team B", total_value=8000, power_rank=2)  # Higher value ranked lower!
    r1 = Roster(roster_id=1, team_name="Team A", wins=10, losses=2)
    r2 = Roster(roster_id=2, team_name="Team B", wins=5, losses=7)
    checks = validate_power([v1, v2], [r1, r2])
    failed = [c for c in checks if not c.passed]
    assert len(failed) >= 1


def test_validate_picks_valid():
    p1 = FuturePick(season="2027", round=1, original_roster_id=1, original_team="Team A", tier="Early", value=4500)
    p2 = FuturePick(season="2027", round=2, original_roster_id=1, original_team="Team A", value=1500)
    tp = TeamPicks(roster_id=1, team_name="Team A", picks=[p1, p2], total_value=6000)
    r1 = Roster(roster_id=1, team_name="Team A")
    checks = validate_picks([tp], [r1])
    assert all(c.passed for c in checks)


def test_validate_picks_invalid_tier():
    p1 = FuturePick(season="2027", round=1, original_roster_id=1, original_team="Team A", tier="INVALID_TIER", value=-100)
    tp = TeamPicks(roster_id=1, team_name="Team A", picks=[p1])
    r1 = Roster(roster_id=1, team_name="Team A")
    checks = validate_picks([tp], [r1])
    failed = [c for c in checks if not c.passed]
    assert len(failed) >= 1


def test_validate_values_valid():
    a1 = Asset(id="1", name="Player 1", value=5000, position="QB", secondary_value=5200)
    a2 = Asset(id="2", name="Player 2", value=4000, position="QB", secondary_value=3900)
    checks = validate_values([a1, a2], position="QB", market="both")
    assert all(c.passed for c in checks)


def test_validate_values_dealer_market():
    a1 = Asset(id="1", name="Player 1", value=5000, position="QB", secondary_value=5200)
    a2 = Asset(id="2", name="Player 2", value=4000, position="QB", secondary_value=3900)
    checks_dealer = validate_values([a1, a2], position="QB", market="dealer")
    assert all(c.passed for c in checks_dealer)

    checks_ktc = validate_values([a1, a2], position="QB", market="ktc")
    assert all(c.passed for c in checks_ktc)


def test_validate_values_invalid_secondary():
    a1 = Asset(id="1", name="Player 1", value=5000, secondary_value=-100)
    checks = validate_values([a1], market="both")
    failed = [c for c in checks if not c.passed]
    assert any("Dual Market" in c.name for c in failed)

    a2 = Asset(id="2", name="Player 2", value=5000, secondary_value=None)
    checks_dealer = validate_values([a2], market="dealer")
    failed_dealer = [c for c in checks_dealer if not c.passed]
    assert any("Secondary Prices Present" in c.name for c in failed_dealer)
    assert any(c.is_warning for c in failed_dealer)


def test_validate_trade_valid():
    a1 = Asset(id="1", name="Player 1", value=5000, secondary_value=5200)
    a2 = Asset(id="2", name="Player 2", value=4000, secondary_value=4100)
    eval = TradeEvaluation(
        side_a=TradeSide(assets=[a1]),
        side_b=TradeSide(assets=[a2]),
        label_a="You get",
        label_b="You give",
    )
    checks = validate_trade(eval)
    assert all(c.passed for c in checks)
    assert any("Trade Secondary Delta Calculation" in c.name for c in checks)


def test_validate_trade_invalid_assets():
    a1 = Asset(id="", name="Player 1", value=-500)
    a2 = Asset(id="2", name="Player 2", value=4000)
    eval = TradeEvaluation(
        side_a=TradeSide(assets=[a1]),
        side_b=TradeSide(assets=[a2]),
        label_a="You get",
        label_b="You give",
    )
    checks = validate_trade(eval)
    failed = [c for c in checks if not c.passed]
    assert any("Integrity" in c.name for c in failed)


def test_validate_movers_arbitrage_valid():
    a1 = Asset(id="1", name="Player 1", value=5000, secondary_value=5500)
    mover = ArbitrageMover(
        asset=a1,
        fc_value=5000,
        secondary_value=5500,
        diff=500,
        pct_diff=9.09,
        market_bias="Dealer",
    )
    checks = validate_movers([mover], mode="arbitrage")
    assert all(c.passed for c in checks)


def test_validate_movers_arbitrage_invalid_bias():
    a1 = Asset(id="1", name="Player 1", value=5000, secondary_value=5500)
    mover = ArbitrageMover(
        asset=a1,
        fc_value=5000,
        secondary_value=5500,
        diff=500,
        pct_diff=9.09,
        market_bias="INVALID_BIAS",
    )
    checks = validate_movers([mover], mode="arbitrage")
    failed = [c for c in checks if not c.passed]
    assert any("Bias" in c.name for c in failed)


def test_validate_lineup_valid():
    s1 = LineupSlot(slot="QB", player_id="1", name="Player 1", position="QB", points=22.5)
    s2 = LineupSlot(slot="WR", player_id="2", name="Player 2", position="WR", points=15.0)
    lu = Lineup(slots=[s1, s2])
    roster = Roster(roster_id=1, team_name="Team A", player_ids=["1", "2"], starters=["1", "2"])
    checks = validate_lineup(lu, target_roster=roster)
    assert all(c.passed for c in checks)


def test_validate_lineup_taxi_started():
    s1 = LineupSlot(slot="QB", player_id="1", name="Player 1", position="QB", points=22.5)
    lu = Lineup(slots=[s1])
    # Player 1 is on taxi squad - should NEVER be started!
    roster = Roster(roster_id=1, team_name="Team A", player_ids=["1"], taxi=["1"])
    checks = validate_lineup(lu, target_roster=roster)
    failed = [c for c in checks if not c.passed]
    assert any("Taxi" in c.name for c in failed)


def test_validate_cleanup_valid():
    s1 = RosterSlot(player_id="1", name="Player 1", position="WR", slot="BENCH", value=100, is_active=True)
    audit = RosterAudit(
        team_name="Team A",
        starter_cap=9,
        bench_cap=11,
        taxi_cap=4,
        ir_cap=2,
        slots=[s1],
        drop_candidates=[s1],
        taxi_candidates=[],
    )
    checks = validate_cleanup(audit)
    assert all(c.passed for c in checks)


def test_validate_waivers_valid():
    a1 = Asset(id="1", name="Free Agent", value=1500, position="RB")
    wt = WaiverTarget(asset=a1, add_count=500, is_rostered=False)
    r1 = Roster(roster_id=1, team_name="Team A", player_ids=["2", "3"])
    checks = validate_waivers([wt], rosters=[r1])
    assert all(c.passed for c in checks)


def test_validate_draft_valid():
    p1 = DraftPickInfo(pick_no=1, round=1, slot=1, used=False)
    a1 = Asset(id="10", name="Rookie A", value=6000, position="WR")
    df = DraftFit(asset=a1, fit_score=6200.0, market_rank=1, why="Upgrade")
    checks = validate_draft(my_picks=[p1], taken={"1", "2"}, fits=[df])
    assert all(c.passed for c in checks)


def test_validate_news_valid():
    item = NewsItem(
        published=1725148800000,
        source="RotoWire",
        title="Active in practice",
        description="Participated in team drills today.",
    )
    checks = validate_news(player_news=[item])
    assert all(c.passed for c in checks)


def test_validate_ask_valid():
    checks = validate_ask("evaluate_trade", {"delta": 500}, "Should I trade?")
    assert all(c.passed for c in checks)


def test_validate_ask_unknown_tool():
    checks = validate_ask("unregistered_tool", {}, "Run query")
    failed = [c for c in checks if not c.passed]
    assert len(failed) >= 1
