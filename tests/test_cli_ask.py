from __future__ import annotations

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

        def players(self, sport="nfl"):
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


def test_config_set_llm_command(tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr("ff.core.config._config_path", lambda: cfg_path)

    cfg = Config(league_id="123", season=2026, format=Format(), llm_backend="auto")
    save_config(cfg, path=cfg_path)

    res = runner.invoke(app, ["config", "set-llm", "claude"])
    assert res.exit_code == 0
    assert "claude" in res.output

    updated = load_config(path=cfg_path)
    assert updated.llm_backend == "claude"


def test_config_set_llm_invalid_backend(tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr("ff.core.config._config_path", lambda: cfg_path)

    cfg = Config(league_id="123", season=2026, format=Format(), llm_backend="auto")
    save_config(cfg, path=cfg_path)

    res = runner.invoke(app, ["config", "set-llm", "invalid_backend"])
    assert res.exit_code != 0
    assert "Invalid backend" in res.output


def test_config_set_llm_no_config(tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr("ff.core.config._config_path", lambda: cfg_path)

    res = runner.invoke(app, ["config", "set-llm", "claude"])
    assert res.exit_code != 0
    assert "No league configured" in res.output
