from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from ff.cli import app
from ff.contracts import Format
from ff.core.config import Config, load_config, save_config

runner = CliRunner()


def test_ask_command_with_mock_runner() -> None:
    with patch("ff.services.llm.runner.TerminalRunner.run", return_value="Trade evaluation: Bijan side wins."):
        res = runner.invoke(app, ["ask", "Should I trade Gibbs for Bijan?"])
        assert res.exit_code == 0
        assert "Bijan" in res.output


def test_ask_command_backend_override() -> None:
    with patch("ff.cli.TerminalRunner") as MockRunner:
        mock_inst = MagicMock()
        mock_inst.run.return_value = "Mock answer"
        MockRunner.return_value = mock_inst

        res = runner.invoke(app, ["ask", "Who to draft?", "--backend", "gemini"])
        assert res.exit_code == 0
        MockRunner.assert_called_once_with(backend="gemini", ollama_model="llama3.2")
        mock_inst.run.assert_called_once()
        assert "Mock answer" in res.output


def test_ask_command_tool_execution_loop(
    monkeypatch: pytest.MonkeyPatch,
    book,
    league,
    rosters_raw,
    users_raw,
    players_meta,
    trending,
    traded_picks,
) -> None:
    save_config(Config(
        league_id="LG1", season=2026, format=Format(),
        username="alice", user_id="userA",
    ))

    class FakeSleeper:
        def state(self, sport="nfl"):
            return {"season": "2026", "week": 1, "display_week": 1}

        def league(self, lid):
            return league

        def rosters(self, lid):
            return rosters_raw

        def league_users(self, lid):
            return users_raw

        def players(self, sport="nfl", *, fresh=False):
            return players_meta

        def trending(self, sport="nfl", kind="add", lookback_hours=24, limit=25):
            return trending

        def traded_picks(self, lid):
            return traded_picks

    class FakeValues:
        def fetch(self, fmt, include_ktc=True):
            return book

    class FakeProj:
        def week(self, season, week, positions=None):
            return {}

    monkeypatch.setattr("ff.cli.SleeperClient", lambda *a, **k: FakeSleeper())
    monkeypatch.setattr("ff.cli.ValuesClient", lambda *a, **k: FakeValues())
    monkeypatch.setattr("ff.cli.ProjectionsClient", lambda *a, **k: FakeProj())

    tool_call_json = (
        '{"tool": "evaluate_trade", "kwargs": '
        '{"give": ["Jahmyr Gibbs"], "get": ["Bijan Robinson"]}}'
    )
    with patch("ff.cli.TerminalRunner") as MockRunner:
        mock_inst = MagicMock()
        mock_inst.run.side_effect = [
            tool_call_json,
            "Final synthesized trade analysis: Bijan side is better.",
        ]
        MockRunner.return_value = mock_inst
        res = runner.invoke(app, ["ask", "Should I trade Gibbs for Bijan?"])

    assert res.exit_code == 0, res.output
    assert "Bijan side is better" in res.output
    assert mock_inst.run.call_count == 2
    synth = mock_inst.run.call_args_list[1].kwargs.get("prompt")
    if synth is None:
        synth = mock_inst.run.call_args_list[1].args[0]
    assert "Bijan" in synth
    assert "evaluate_trade" in synth


def test_ask_picks_uses_league_pick_window(fake_clients) -> None:
    save_config(Config(league_id="LG1", season=2026, format=Format(), user_id="userA"))
    with patch("ff.cli.TerminalRunner") as MockRunner:
        mock_inst = MagicMock()
        mock_inst.run.side_effect = ['{"tool": "get_picks", "kwargs": {}}', "Your picks."]
        MockRunner.return_value = mock_inst
        res = runner.invoke(app, ["ask", "what picks do I own"])
    assert res.exit_code == 0, res.output
    synth = mock_inst.run.call_args_list[1].kwargs["prompt"]
    assert '"season": "2027"' in synth
    assert '"season": "2026"' not in synth
    assert '"round": 3' not in synth


def test_ask_waivers_pool_follows_limit(fake_clients, trending, monkeypatch) -> None:
    import ff.cli as cli
    save_config(Config(league_id="LG1", season=2026, format=Format(), user_id="userA"))
    sc = cli.SleeperClient()
    mock_trending = MagicMock(return_value=trending)
    monkeypatch.setattr(sc, "trending", mock_trending)
    monkeypatch.setattr(cli, "SleeperClient", lambda: sc)
    with patch("ff.cli.TerminalRunner") as MockRunner:
        mock_inst = MagicMock()
        mock_inst.run.side_effect = ['{"tool": "get_waivers", "kwargs": {"limit": 30}}', "Targets."]
        MockRunner.return_value = mock_inst
        res = runner.invoke(app, ["ask", "who should I add"])
    assert res.exit_code == 0, res.output
    mock_trending.assert_called_once_with(kind="add", limit=90)


def test_ask_waivers_bad_limit_is_a_tool_error(fake_clients) -> None:
    save_config(Config(league_id="LG1", season=2026, format=Format(), user_id="userA"))
    with patch("ff.cli.TerminalRunner") as MockRunner:
        mock_inst = MagicMock()
        mock_inst.run.return_value = '{"tool": "get_waivers", "kwargs": {"limit": "abc"}}'
        MockRunner.return_value = mock_inst
        res = runner.invoke(app, ["ask", "who should I add"])
    assert res.exit_code == 0, res.output
    assert "Error executing tool calculation" in res.output


def test_ask_rejects_unknown_tool() -> None:
    with patch("ff.cli.TerminalRunner") as MockRunner:
        mock_inst = MagicMock()
        mock_inst.run.return_value = '{"tool": "os_system", "kwargs": {"cmd": "id"}}'
        MockRunner.return_value = mock_inst
        res = runner.invoke(app, ["ask", "run a shell command"])
    assert res.exit_code == 0, res.output
    assert "Unknown tool" in res.output
    assert mock_inst.run.call_count == 1


def test_ask_missing_backend_is_a_clean_error() -> None:
    with patch("ff.services.llm.runner.shutil.which", return_value=None):
        res = runner.invoke(app, ["ask", "hello", "--backend", "claude"])
    assert res.exit_code == 1
    assert "not found" in res.output.lower() or "LLM runner" in res.output


def test_config_set_llm_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr("ff.core.config._config_path", lambda: cfg_path)

    cfg = Config(league_id="123", season=2026, format=Format(), llm_backend="auto")
    save_config(cfg, path=cfg_path)

    res = runner.invoke(app, ["config", "set-llm", "claude"])
    assert res.exit_code == 0
    assert "claude" in res.output

    updated = load_config(path=cfg_path)
    assert updated.llm_backend == "claude"


def test_config_set_llm_invalid_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr("ff.core.config._config_path", lambda: cfg_path)

    cfg = Config(league_id="123", season=2026, format=Format(), llm_backend="auto")
    save_config(cfg, path=cfg_path)

    res = runner.invoke(app, ["config", "set-llm", "invalid_backend"])
    assert res.exit_code != 0
    assert "Invalid backend" in res.output


def test_config_set_llm_no_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr("ff.core.config._config_path", lambda: cfg_path)

    res = runner.invoke(app, ["config", "set-llm", "claude"])
    assert res.exit_code != 0
    assert "No league configured" in res.output


def test_ask_multi_tool_batch_shares_context(fake_clients, monkeypatch: pytest.MonkeyPatch) -> None:
    import ff.cli as cli
    save_config(Config(league_id="LG1", season=2026, format=Format(), user_id="userA"))
    sc = cli.SleeperClient()
    state_calls = []
    orig_state = sc.state
    monkeypatch.setattr(sc, "state", lambda *a, **k: state_calls.append(1) or orig_state(*a, **k))
    monkeypatch.setattr(cli, "SleeperClient", lambda *a, **k: sc)

    vc = cli.ValuesClient()
    fetch_calls = []
    orig_fetch = vc.fetch
    monkeypatch.setattr(vc, "fetch", lambda *a, **k: fetch_calls.append(1) or orig_fetch(*a, **k))
    monkeypatch.setattr(cli, "ValuesClient", lambda *a, **k: vc)

    batch = '{"tools": [{"tool": "get_team_window", "kwargs": {}}, {"tool": "get_movers", "kwargs": {"buy": true, "limit": 5}}]}'
    with patch("ff.cli.TerminalRunner") as MockRunner:
        mock_inst = MagicMock()
        mock_inst.run.side_effect = [batch, "Combined strategy answer."]
        MockRunner.return_value = mock_inst
        res = runner.invoke(app, ["ask", "Should I buy low or pivot?"])
    assert res.exit_code == 0, res.output
    assert "Combined strategy answer" in res.output
    synth = mock_inst.run.call_args_list[1].kwargs["prompt"]
    assert "get_team_window" in synth and "get_movers" in synth
    assert len(state_calls) == 1
    assert len(fetch_calls) == 1


def test_ask_multi_tool_dedup_cap_and_partial_failure(fake_clients, monkeypatch: pytest.MonkeyPatch) -> None:
    save_config(Config(league_id="LG1", season=2026, format=Format(), user_id="userA"))
    monkeypatch.setenv("FF_QA", "strict")
    # 5 calls with duplicate and 1 unknown-team failure; deduplicates and caps at 3
    batch = (
        '{"tools": ['
        '{"tool": "get_team_window", "kwargs": {}},'
        '{"tool": "get_team_window", "kwargs": {}},'
        '{"tool": "get_roster", "kwargs": {"team": "nonexistent"}},'
        '{"tool": "get_movers", "kwargs": {"limit": 3}},'
        '{"tool": "get_picks", "kwargs": {}}'
        ']}'
    )
    with patch("ff.cli.TerminalRunner") as MockRunner:
        mock_inst = MagicMock()
        mock_inst.run.side_effect = [batch, "Partial synthesis."]
        MockRunner.return_value = mock_inst
        res = runner.invoke(app, ["ask", "Analyze everything"])
    assert res.exit_code == 0, res.output
    synth = mock_inst.run.call_args_list[1].kwargs["prompt"]
    assert "get_team_window" in synth
    assert "get_movers" in synth
    assert "get_picks" not in synth  # capped at 3 unique calls
    assert "could not find that team" in synth

    # Batch containing an unknown tool rejects immediately before synthesis
    monkeypatch.delenv("FF_QA", raising=False)
    with patch("ff.cli.TerminalRunner") as MockRunner:
        mock_inst = MagicMock()
        mock_inst.run.return_value = '{"tools": [{"tool": "get_team_window", "kwargs": {}}, {"tool": "os_system", "kwargs": {}}]}'
        MockRunner.return_value = mock_inst
        bad_res = runner.invoke(app, ["ask", "Bad batch"])
    assert "Unknown tool" in bad_res.output
    assert mock_inst.run.call_count == 1

    # Batch where every tool fails prints error cleanly without calling synthesis
    with patch("ff.cli.TerminalRunner") as MockRunner:
        mock_inst = MagicMock()
        mock_inst.run.return_value = '{"tools": [{"tool": "get_roster", "kwargs": {"team": "nope1"}}, {"tool": "get_roster", "kwargs": {"team": "nope2"}}]}'
        MockRunner.return_value = mock_inst
        fail_res = runner.invoke(app, ["ask", "Both fail"])
    assert fail_res.exit_code == 0, fail_res.output
    assert "Error executing tool calculation" in fail_res.output
    assert mock_inst.run.call_count == 1


def test_ask_setup_league_not_batched(fake_clients, monkeypatch: pytest.MonkeyPatch) -> None:
    import ff.cli as cli
    monkeypatch.setattr("ff.sleeper.client.SleeperClient", cli.SleeperClient)
    batch = '{"tools": [{"tool": "setup_league", "kwargs": {"username": "alice"}}, {"tool": "get_team_window", "kwargs": {}}]}'
    with patch("ff.cli.TerminalRunner") as MockRunner:
        mock_inst = MagicMock()
        mock_inst.run.return_value = batch
        MockRunner.return_value = mock_inst
        res = runner.invoke(app, ["ask", "setup alice and check window"])
    assert res.exit_code == 0, res.output
    assert "Successfully onboarded Sleeper league" in res.output
    assert mock_inst.run.call_count == 1


def test_ask_fenced_multi_tool_json_parsed(fake_clients) -> None:
    save_config(Config(league_id="LG1", season=2026, format=Format(), user_id="userA"))
    batch = (
        "```json\n"
        '{"tools": [{"tool": "get_team_window", "kwargs": {}}, {"tool": "get_picks", "kwargs": {}}]}\n'
        "```"
    )
    with patch("ff.cli.TerminalRunner") as MockRunner:
        mock_inst = MagicMock()
        mock_inst.run.side_effect = [batch, "Fenced synthesis."]
        MockRunner.return_value = mock_inst
        res = runner.invoke(app, ["ask", "Check window and picks"])
    assert res.exit_code == 0, res.output
    assert "Fenced synthesis" in res.output
    assert mock_inst.run.call_count == 2
