"""End-to-end CLI tests. The two network clients are faked with fixtures; the
real Typer app, config I/O, valuation, and rendering all run for real."""

import re

import pytest
from typer.testing import CliRunner

from ff.cli import app
from ff.core.config import Config, save_config
from ff.sleeper import detect_format

runner = CliRunner()


def _write_config(league):
    save_config(Config(
        league_id="LG1", season="2026", name="Test Dynasty",
        format=detect_format(league), username="alice", user_id="userA",
    ))


def test_setup_writes_config(fake_clients):
    result = runner.invoke(app, ["setup", "alice"])
    assert result.exit_code == 0, result.output
    from ff.core.config import config_exists, load_config
    assert config_exists()
    assert load_config().format.superflex is True


def test_roster_defaults_to_my_team(fake_clients, league):
    _write_config(league)
    result = runner.invoke(app, ["roster"])
    assert result.exit_code == 0, result.output
    assert "Dynasty Warriors" in result.output
    assert "17,500" in result.output


def test_power_lists_all_teams(fake_clients, league):
    _write_config(league)
    result = runner.invoke(app, ["power"])
    assert result.exit_code == 0, result.output
    assert "Gridiron" in result.output
    assert "22,000" in result.output


def test_picks_league_summary(fake_clients, league):
    _write_config(league)
    result = runner.invoke(app, ["picks"])
    assert result.exit_code == 0, result.output
    assert "draft capital" in result.output
    # Latest draft is season 2026 -> the window is 2027-28, rounds=2 (league
    # draft_rounds unset -> the draft settings). Warriors: own mid 1st 3,100 +
    # acquired late 1st 2,400 + acquired flat 2nd 1,400 + flat 2028 1st 2,200.
    assert "9,100" in result.output
    # The full 2027 cell pins the per-pick acquired marker AND the cell order.
    assert "1st, 1st*, 2nd*" in result.output
    # And rounds derivation: 2 rounds means no 3rd/4th anywhere in the window.
    assert "3rd" not in result.output
    assert "2027" in result.output and "2028" in result.output


def test_picks_years_and_rounds_override(fake_clients, league):
    _write_config(league)
    result = runner.invoke(app, ["picks", "--rounds", "3"])
    assert result.exit_code == 0, result.output
    assert "3rd" in result.output  # overrides the latest draft's 2 rounds
    result = runner.invoke(app, ["picks", "--years", "1"])
    assert result.exit_code == 0, result.output
    assert "2027" in result.output and "2028" not in result.output


def test_picks_team_detail(fake_clients, league):
    _write_config(league)
    result = runner.invoke(app, ["picks", "Dynasty Warriors"])
    assert result.exit_code == 0, result.output
    assert "9,100" in result.output
    assert "from Gridiron Kings" in result.output  # acquired pick names its origin
    # The tier COLUMN itself, not the footer text: own 2027 1st row reads
    # own | mid | 3,100. (The footer always contains "early/mid/late".)
    assert re.search(r"own\s+│\s+mid\s+│\s+3,100", result.output)


def test_waivers_pool_size(fake_clients, league, trending, monkeypatch):
    from unittest.mock import Mock
    import ff.cli as cli
    _write_config(league)
    sc = cli.SleeperClient()
    sc.trending = Mock(return_value=trending)
    monkeypatch.setattr(cli, "SleeperClient", lambda: sc)
    result = runner.invoke(app, ["waivers", "--limit", "20"])
    assert result.exit_code == 0, result.output
    sc.trending.assert_called_once_with(kind="add", limit=60)


def test_values_by_position(fake_clients, league):
    _write_config(league)
    result = runner.invoke(app, ["values", "-p", "WR"])
    assert result.exit_code == 0, result.output
    assert "Odunze" in result.output


def test_trade_command(fake_clients, league):
    _write_config(league)
    result = runner.invoke(app, ["trade", "--give", "Jahmyr Gibbs",
                                 "--get", "Bijan Robinson,2027 1st"])
    assert result.exit_code == 0, result.output
    assert "win" in result.output.lower()


def test_cleanup_command(fake_clients, league):
    _write_config(league)
    result = runner.invoke(app, ["cleanup"])
    assert result.exit_code == 0, result.output
    # roster 1: 2 starters + 1 bench kicker, cap 12 -> 9 open
    assert "9 open" in result.output
    assert "taxi 0/2" in result.output
    # the 0-value bench kicker is the drop candidate, and its drop frees an active slot
    assert "Test Kicker" in result.output
    assert "active slot" in result.output


def test_cleanup_offers_ir_for_out_players_when_the_league_allows_it(fake_clients, league,
                                                                     players_meta):
    league["settings"]["reserve_allow_out"] = 1
    players_meta["9999"]["injury_status"] = "Out"  # the bench kicker
    _write_config(league)
    result = runner.invoke(app, ["cleanup"])
    assert result.exit_code == 0, result.output
    assert "move to IR" in result.output
    assert re.search(r"Test Kicker\s.*\sOut\s", result.output)
    assert "or an IR move opens room" in result.output
    assert "Sleeper blocks adds and drops" in result.output


def test_waivers_command(fake_clients, league):
    _write_config(league)
    result = runner.invoke(app, ["waivers"])
    assert result.exit_code == 0, result.output
    assert "Odunze" in result.output


def test_command_without_config_fails_cleanly(fake_clients):
    result = runner.invoke(app, ["roster"])
    assert result.exit_code == 1
    assert "ff setup" in result.output


def test_setup_with_league_id_still_records_user(fake_clients):
    result = runner.invoke(app, ["setup", "alice", "--league-id", "LG1"])
    assert result.exit_code == 0, result.output
    from ff.core.config import load_config
    assert load_config().user_id == "userA"  # not None, so `roster` finds the team


def test_movers_command(fake_clients, league):
    _write_config(league)
    result = runner.invoke(app, ["movers"])
    assert result.exit_code == 0, result.output
    assert "Allen" in result.output  # biggest sell-high in the fixture


def test_network_error_is_a_clean_message(fake_clients, league, monkeypatch):
    _write_config(league)
    import requests

    class Boom:
        def fetch(self, fmt, *args, **kwargs):
            raise requests.exceptions.ConnectionError("no network")

    monkeypatch.setattr("ff.cli.ValuesClient", lambda *a, **k: Boom())
    result = runner.invoke(app, ["values"])
    assert result.exit_code == 1
    assert "could not reach" in result.output


def test_lineup_command(fake_clients, league):
    _write_config(league)
    result = runner.invoke(app, ["lineup"])
    assert result.exit_code == 0, result.output
    assert "optimal lineup" in result.output
    assert "Chase" in result.output  # WR slot filled by the projected starter


# Sleeper flips `week` and `display_week` at different times, in either order:
# on Tuesday 2026-09-29 it returned week 4 / display_week 3 (week 3 was over),
# while its docs example shows week 2 / display_week 3.
@pytest.mark.parametrize("state", [
    {"season": "2026", "week": 4, "display_week": 3},
    {"season": "2026", "week": 3, "display_week": 4},
])
@pytest.mark.parametrize("args", [[], ["--week", "4"]])
def test_lineup_plans_the_open_week(fake_clients, league, monkeypatch, state, args):
    from unittest.mock import Mock

    import ff.cli as cli
    sleeper = cli.SleeperClient()
    sleeper.state = lambda *a, **k: state
    monkeypatch.setattr(cli, "SleeperClient", lambda *a, **k: sleeper)
    projections = Mock(week=Mock(return_value={"7564": {"rec": 8, "rec_yd": 100, "rec_td": 1}}))
    monkeypatch.setattr(cli, "ProjectionsClient", lambda *a, **k: projections)
    _write_config(league)
    result = runner.invoke(app, ["lineup", *args])
    assert result.exit_code == 0, result.output
    projections.week.assert_called_once_with("2026", 4, fresh=True)
    assert "2026 week 4" in result.output
    # the open week gets current injuries and game locks, not a projection-only scenario
    assert "Projection-only scenario" not in result.output


@pytest.mark.parametrize("state, week", [
    ({}, 1),
    ({"week": 0, "display_week": 0}, 1),
    ({"week": None, "display_week": 5}, 5),
    ({"week": 7}, 7),
])
def test_current_week_falls_back_and_never_drops_below_one(state, week):
    from ff.cli import _current_week
    assert _current_week(state) == week


def test_draft_command_resolves_pick_ownership(fake_clients, league):
    """Regression: pick ownership needs slot_to_roster_id, which only the single
    /draft endpoint returns - not the /drafts list. So 'your picks' must populate."""
    _write_config(league)
    result = runner.invoke(app, ["draft", "--limit", "5"])
    assert result.exit_code == 0, result.output
    assert "your picks" in result.output
    assert "#1" in result.output  # used R1 pick (Chase)
    assert "#4" in result.output  # upcoming R2 pick (slot 1, 3 teams -> pick 4)
    assert "best available" in result.output  # substring kept for back-compat
    # team-aware additions: status header first, standing table, fit board, rec
    assert "status" in result.output
    assert "where you stand" in result.output
    assert "FOR YOU" in result.output
    assert "recommend" in result.output


def test_draft_mode_override_sets_status(fake_clients, league):
    """--mode forces the lens deterministically, independent of auto-detection."""
    _write_config(league)
    reb = runner.invoke(app, ["draft", "--mode", "rebuild", "--limit", "5"])
    assert reb.exit_code == 0, reb.output
    assert "REBUILD" in reb.output
    con = runner.invoke(app, ["draft", "--mode", "contend", "--limit", "5"])
    assert con.exit_code == 0, con.output
    assert "CONTEND" in con.output


def test_draft_rejects_unknown_mode(fake_clients, league):
    """A typo'd --mode must fail loudly, not silently fall back to auto-detect."""
    _write_config(league)
    result = runner.invoke(app, ["draft", "--mode", "contnd", "--limit", "5"])
    assert result.exit_code == 1
    assert "--mode must be" in result.output


def test_corrupt_config_is_a_clean_message(fake_clients):
    from ff.core import config as cfgmod
    home = cfgmod.home()
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text("{ this is not valid json")
    result = runner.invoke(app, ["power"])
    assert result.exit_code == 1
    assert "corrupt" in result.output


def test_cli_trade_dual_market_output(fake_clients, league):
    _write_config(league)
    result = runner.invoke(app, ["trade", "--give", "Jahmyr Gibbs", "--get", "Bijan Robinson,2027 1st"])
    assert result.exit_code == 0, result.output
    # Must have both FC and KTC columns
    assert "FC" in result.output
    assert ("KTC" in result.output or "Dealer" in result.output)
    # Must display dual-market verdict banner and arbitrage classification
    assert "Consensus Win" in result.output


def test_cli_trade_shows_site_adjustments_rule_and_provenance(fake_clients, league):
    # 1-for-2: FantasyCalc credits the single-asset side (Gibbs, 8000) with the other
    # side's cheapest piece, floor(min(2027 1st * 0.6982, 753)); ff prints that row,
    # the site totals, the offer rule, and where the values came from.
    _write_config(league)
    result = runner.invoke(app, ["trade", "--give", "Jahmyr Gibbs", "--get", "Bijan Robinson,2027 1st"])
    assert result.exit_code == 0, result.output
    assert "+ site package adjustment" in result.output and "= site total" in result.output
    assert "offer rule: FAIL" in result.output
    assert "values: FantasyCalc" in result.output and "KTC" in result.output


def test_cli_trade_ktc_mode_without_ktc_shows_the_fantasycalc_numbers_it_judges(fake_clients, league,
                                                                              book, monkeypatch):
    class FantasyCalcOnly:
        def fetch(self, fmt, include_secondary=True, include_ktc=True, **kwargs):
            return book

    monkeypatch.setattr("ff.cli.ValuesClient", lambda *a, **k: FantasyCalcOnly())
    _write_config(league)
    result = runner.invoke(app, ["trade", "--give", "Jahmyr Gibbs", "--get", "Bijan Robinson", "-m", "ktc"])
    assert result.exit_code == 0, result.output
    assert "verdict (FantasyCalc - KTC cannot price this)" in result.output
    assert "FC" in result.output and "8,000" in result.output  # Gibbs' FantasyCalc value is shown


def test_cli_trade_cannot_judge_when_a_calculator_changed(fake_clients, league, monkeypatch):
    monkeypatch.setattr("ff.cli.check_calculators", lambda *a, **k: ["KTC adjustPackageNew() changed"])
    _write_config(league)
    result = runner.invoke(app, ["trade", "--give", "Jahmyr Gibbs", "--get", "Bijan Robinson"])
    assert result.exit_code == 0, result.output
    assert "offer rule: cannot judge" in result.output
    assert "KTC adjustPackageNew() changed" in result.output


def test_cli_trade_market_flag(fake_clients, league):
    _write_config(league)
    # --market fc should only show single market
    res_fc = runner.invoke(app, ["trade", "--give", "Jahmyr Gibbs", "--get", "Bijan Robinson", "--market", "fc"])
    assert res_fc.exit_code == 0, res_fc.output
    assert "Dealer" not in res_fc.output and "KTC" not in res_fc.output

    # --market dealer should show secondary evaluation
    res_dealer = runner.invoke(app, ["trade", "--give", "Jahmyr Gibbs", "--get", "Bijan Robinson", "--market", "dealer"])
    assert res_dealer.exit_code == 0, res_dealer.output
    assert ("KTC" in res_dealer.output or "Dealer" in res_dealer.output)

    # --market ktc should show secondary evaluation
    res_ktc = runner.invoke(app, ["trade", "--give", "Jahmyr Gibbs", "--get", "Bijan Robinson", "--market", "ktc"])
    assert res_ktc.exit_code == 0, res_ktc.output
    assert ("KTC" in res_ktc.output or "Dealer" in res_ktc.output)

    # Invalid market
    res_inv = runner.invoke(app, ["trade", "--give", "Jahmyr Gibbs", "--get", "Bijan Robinson", "--market", "invalid"])
    assert res_inv.exit_code == 1
    assert "--market must be" in res_inv.output


def test_cli_values_market_flag(fake_clients, league):
    _write_config(league)
    # Default (both) shows FC and KTC columns
    res_both = runner.invoke(app, ["values", "-p", "WR"])
    assert res_both.exit_code == 0, res_both.output
    assert "FC" in res_both.output
    assert ("KTC" in res_both.output or "Dealer" in res_both.output)

    # --market fc
    res_fc = runner.invoke(app, ["values", "-p", "WR", "--market", "fc"])
    assert res_fc.exit_code == 0, res_fc.output
    assert "Dealer" not in res_fc.output and "KTC" not in res_fc.output

    # --market dealer
    res_dealer = runner.invoke(app, ["values", "-p", "WR", "--market", "dealer"])
    assert res_dealer.exit_code == 0, res_dealer.output
    assert ("KTC" in res_dealer.output or "Dealer" in res_dealer.output)

    # --market ktc (alias)
    res_ktc = runner.invoke(app, ["values", "-p", "WR", "--market", "ktc"])
    assert res_ktc.exit_code == 0, res_ktc.output
    assert ("KTC" in res_ktc.output or "Dealer" in res_ktc.output)

    # Invalid market
    res_inv = runner.invoke(app, ["values", "--market", "bad"])
    assert res_inv.exit_code == 1
    assert "--market must be" in res_inv.output


def test_cli_movers_arbitrage(fake_clients, league, multi_market_book, monkeypatch):
    """Header-only empty tables must fail: the dual-market book has Gibbs.

    The fixture's KTC values follow FC's order exactly, which is no disagreement
    once both markets share one scale, so swap two ranks: KTC here puts Gibbs
    (8,400) above Bijan, FC the reverse."""
    from ff.values import ValueBook
    assets = [a.model_copy() for a in multi_market_book.assets]
    for a in assets:
        if a.name == "Bijan Robinson":
            a.secondary_value = 8300

    class SwappedKtc:
        def fetch(self, fmt, include_secondary=True, include_ktc=True):
            return ValueBook(assets)

    monkeypatch.setattr("ff.cli.ValuesClient", lambda *a, **k: SwappedKtc())
    _write_config(league)
    res = runner.invoke(app, ["movers", "--arbitrage"])
    assert res.exit_code == 0, res.output
    assert "Jahmyr Gibbs" in res.output
    assert "8,000" in res.output  # FC
    assert "8,400" in res.output  # Dealer
    assert "No market arbitrage opportunities found" not in res.output

    # --buy = Dealer > FC; --sell = FC > Dealer
    res_buy = runner.invoke(app, ["movers", "--arbitrage", "--buy"])
    assert res_buy.exit_code == 0, res_buy.output
    assert "Jahmyr Gibbs" in res_buy.output

    res_sell = runner.invoke(app, ["movers", "--arbitrage", "--sell"])
    assert res_sell.exit_code == 0, res_sell.output
    assert "Bijan Robinson" in res_sell.output


def test_ktc_outage_is_reported_not_silent(fake_clients, league, book, monkeypatch):
    """With no KTC values at all, the default dual-market views say so instead of
    quietly falling back to FantasyCalc (or claiming there is no arbitrage)."""
    class FantasyCalcOnly:
        def fetch(self, fmt, include_secondary=True, include_ktc=True):
            return book

    monkeypatch.setattr("ff.cli.ValuesClient", lambda *a, **k: FantasyCalcOnly())
    _write_config(league)
    outage = "KeepTradeCut values are unavailable right now"
    for args in (["trade", "--give", "Jahmyr Gibbs", "--get", "Bijan Robinson"],
                 ["values"], ["movers", "--arbitrage"]):
        res = runner.invoke(app, args)
        assert res.exit_code == 0, res.output
        assert outage in res.output, args
    assert "No market arbitrage opportunities found" not in res.output


def test_cli_roster_shows_depth_and_injury(fake_clients, league):
    _write_config(league)
    # Roster 3 has Backup Tightend with [Q - Ankle] and TE2
    res = runner.invoke(app, ["roster", "carol"])
    assert res.exit_code == 0, res.output
    assert "Backup Tightend" in res.output
    assert "TE2" in res.output
    assert "[Q - Ankle]" in res.output


def test_cli_trade_shows_depth_and_injury(fake_clients, league):
    _write_config(league)
    res = runner.invoke(app, ["trade", "--give", "Jahmyr Gibbs", "--get", "Bijan Robinson", "-m", "fc"])
    assert res.exit_code == 0, res.output
    assert "Bijan Robinson [RB1]" in res.output
    assert "Jahmyr Gibbs [RB1] [Q - Hamstring]" in res.output


def test_cli_news_command(fake_clients, league):
    _write_config(league)
    res = runner.invoke(app, ["news"])
    assert res.exit_code == 0, res.output
    assert "Backup Tightend" in res.output
    assert "Questionable" in res.output or "Q - Ankle" in res.output


def test_cli_config_set_llm_case_insensitive(fake_clients, league):
    _write_config(league)
    res = runner.invoke(app, ["config", "set-llm", "CLAUDE"])
    assert res.exit_code == 0, res.output
    assert "Updated LLM backend to claude" in res.output


def test_cli_doctor_alias(fake_clients, league):
    _write_config(league)
    res = runner.invoke(app, ["doctor"])
    assert res.exit_code == 0, res.output
    assert "System Health Scorecard" in res.output or "QA Report" in res.output or "Checks" in res.output


def test_cli_setup_invalid_league_id(fake_clients, monkeypatch):
    from ff.cli import SleeperClient
    fake_inst = SleeperClient()
    fake_inst.league = lambda lid: None
    monkeypatch.setattr("ff.cli.SleeperClient", lambda *a, **k: fake_inst)
    res = runner.invoke(app, ["setup", "alice", "--league-id", "nonexistent_id"])
    assert res.exit_code == 1
    assert "could not find Sleeper league" in res.output


def test_cli_trade_dealer_positional_swings(fake_clients, league):
    _write_config(league)
    res = runner.invoke(app, ["trade", "--give", "Jahmyr Gibbs", "--get", "Bijan Robinson", "-m", "dealer"])
    assert res.exit_code == 0, res.output
    assert "positional swing" in res.output
    assert ("KTC" in res.output or "Dealer" in res.output)


def test_cli_lineup_handles_unsupported_slots(fake_clients, league, monkeypatch):
    # Add an unsupported slot to the league roster positions
    from ff.cli import SleeperClient
    custom_league = dict(league)
    custom_league["roster_positions"] = list(league.get("roster_positions", [])) + ["IDP"]
    _write_config(custom_league)
    fake_inst = SleeperClient()
    fake_inst.league = lambda lid, **kwargs: custom_league
    monkeypatch.setattr("ff.cli.SleeperClient", lambda *a, **k: fake_inst)
    res = runner.invoke(app, ["lineup"])
    assert res.exit_code == 1, res.output
    assert "Unsupported lineup slots: IDP" in res.output


def test_cli_lazy_context_pick_window(fake_clients, league):
    from ff.cli import _LazyContext, SleeperClient
    from ff.core.config import Config
    cfg = Config(league_id="LG1", season="2026", format=detect_format(league), user_id="userA")
    sc = SleeperClient()
    drafts = sc.drafts
    calls = []
    sc.drafts = lambda lid: calls.append(lid) or drafts(lid)
    ctx = _LazyContext(cfg, sc)
    # Same window as `ff picks`: after the latest (2026) draft, its 2 rounds.
    assert ctx["seasons"] == ["2027", "2028"]
    assert ctx["rounds"] == 2
    assert calls == ["LG1"]


def test_cli_lazy_context_value_book_scope(fake_clients, league, book, multi_market_book):
    from ff.cli import _LazyContext, SleeperClient
    from ff.core.config import Config
    cfg = Config(league_id="LG1", season="2026", format=detect_format(league), user_id="userA")
    assert _LazyContext(cfg, SleeperClient())["value_book"] is multi_market_book
    assert _LazyContext(cfg, SleeperClient(), include_secondary=False)["value_book"] is book


def test_cli_lazy_context(fake_clients, league):
    from ff.cli import _LazyContext, SleeperClient
    from ff.core.config import Config
    cfg = Config(
        league_id="LG1", season="2026", name="Test Dynasty",
        format=detect_format(league), username="alice", user_id="userA",
    )
    sc = SleeperClient()
    ctx = _LazyContext(cfg, sc)
    assert "config" in ctx
    # rosters should not be in keys until accessed
    assert "rosters" not in dict.keys(ctx)
    rosters = ctx["rosters"]
    assert len(rosters) > 0
    assert "rosters" in dict.keys(ctx)


