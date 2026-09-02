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


def test_picks_team_detail(fake_clients, league):
    _write_config(league)
    result = runner.invoke(app, ["picks", "Dynasty Warriors"])
    assert result.exit_code == 0, result.output
    assert "9,100" in result.output
    assert "from Gridiron Kings" in result.output  # acquired pick names its origin
    # The tier COLUMN itself, not the footer text: own 2027 1st row reads
    # own | mid | 3,100. (The footer always contains "early/mid/late".)
    assert re.search(r"own\s+│\s+mid\s+│\s+3,100", result.output)


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
    # Must have both FC and Dealer columns
    assert "FC" in result.output
    assert "Dealer" in result.output
    # Must display dual-market verdict banner and arbitrage classification
    assert "Consensus Win" in result.output


def test_cli_trade_market_flag(fake_clients, league):
    _write_config(league)
    # --market fc should only show single market
    res_fc = runner.invoke(app, ["trade", "--give", "Jahmyr Gibbs", "--get", "Bijan Robinson", "--market", "fc"])
    assert res_fc.exit_code == 0, res_fc.output
    assert "Dealer" not in res_fc.output

    # --market dealer should show Dealer evaluation
    res_dealer = runner.invoke(app, ["trade", "--give", "Jahmyr Gibbs", "--get", "Bijan Robinson", "--market", "dealer"])
    assert res_dealer.exit_code == 0, res_dealer.output
    assert "Dealer" in res_dealer.output

    # --market ktc should show Dealer evaluation as alias
    res_ktc = runner.invoke(app, ["trade", "--give", "Jahmyr Gibbs", "--get", "Bijan Robinson", "--market", "ktc"])
    assert res_ktc.exit_code == 0, res_ktc.output
    assert "Dealer" in res_ktc.output

    # Invalid market
    res_inv = runner.invoke(app, ["trade", "--give", "Jahmyr Gibbs", "--get", "Bijan Robinson", "--market", "invalid"])
    assert res_inv.exit_code == 1
    assert "--market must be" in res_inv.output


def test_cli_values_market_flag(fake_clients, league):
    _write_config(league)
    # Default (both) shows FC and Dealer columns
    res_both = runner.invoke(app, ["values", "-p", "WR"])
    assert res_both.exit_code == 0, res_both.output
    assert "FC" in res_both.output
    assert "Dealer" in res_both.output

    # --market fc
    res_fc = runner.invoke(app, ["values", "-p", "WR", "--market", "fc"])
    assert res_fc.exit_code == 0, res_fc.output
    assert "Dealer" not in res_fc.output

    # --market dealer
    res_dealer = runner.invoke(app, ["values", "-p", "WR", "--market", "dealer"])
    assert res_dealer.exit_code == 0, res_dealer.output
    assert "Dealer" in res_dealer.output

    # --market ktc (alias)
    res_ktc = runner.invoke(app, ["values", "-p", "WR", "--market", "ktc"])
    assert res_ktc.exit_code == 0, res_ktc.output
    assert "Dealer" in res_ktc.output

    # Invalid market
    res_inv = runner.invoke(app, ["values", "--market", "bad"])
    assert res_inv.exit_code == 1
    assert "--market must be" in res_inv.output


def test_cli_movers_arbitrage(fake_clients, league):
    """Header-only empty tables must fail: the dual-market book has Gibbs."""
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
    assert "Jahmyr Gibbs [RB1 [Q - Hamstring]]" in res.output


def test_cli_news_command(fake_clients, league):
    _write_config(league)
    res = runner.invoke(app, ["news"])
    assert res.exit_code == 0, res.output
    assert "Backup Tightend" in res.output
    assert "Questionable" in res.output or "Q - Ankle" in res.output
