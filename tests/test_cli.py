"""End-to-end CLI tests. The two network clients are faked with fixtures; the
real Typer app, config I/O, valuation, and rendering all run for real."""

import pytest
from typer.testing import CliRunner

from ff.cli import app
from ff.core.config import Config, save_config
from ff.sleeper import detect_format

runner = CliRunner()


@pytest.fixture
def fake_clients(monkeypatch, book, league, rosters_raw, users_raw, players_meta, trending):
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

        def trending(self, sport="nfl", kind="add", lookback_hours=24, limit=25):
            return trending

        def drafts(self, lid):
            # The list endpoint summary deliberately omits slot_to_roster_id,
            # mirroring the real API; the command must fetch full detail.
            return [{"draft_id": "DR1", "status": "drafting", "type": "linear",
                     "season": "2026", "settings": {"teams": 3, "rounds": 2}}]

        def draft(self, did):
            return {"draft_id": "DR1", "status": "drafting", "type": "linear",
                    "settings": {"teams": 3, "rounds": 2, "reversal_round": 0},
                    "slot_to_roster_id": {"1": 1, "2": 2, "3": 3}}

        def draft_picks(self, did):
            return [{"pick_no": 1, "round": 1, "draft_slot": 1, "roster_id": 1,
                     "player_id": "7564",
                     "metadata": {"first_name": "Ja'Marr", "last_name": "Chase",
                                  "position": "WR"}}]

        def draft_traded_picks(self, did):
            return []

    class FakeValues:
        def fetch(self, fmt):
            return book

    class FakeProjections:
        def week(self, season, week, positions=None):
            return {"7564": {"rec": 8, "rec_yd": 100, "rec_td": 1},
                    "9221": {"rush_yd": 90, "rush_td": 1}}

    monkeypatch.setattr("ff.cli.SleeperClient", lambda *a, **k: FakeSleeper())
    monkeypatch.setattr("ff.cli.ValuesClient", lambda *a, **k: FakeValues())
    monkeypatch.setattr("ff.cli.ProjectionsClient", lambda *a, **k: FakeProjections())
    monkeypatch.setenv("COLUMNS", "200")  # keep rich from wrapping cells


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
        def fetch(self, fmt):
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
