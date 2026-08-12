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


def test_ask_command_tool_execution_loop(tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr("ff.core.config._config_path", lambda: cfg_path)
    cfg = Config(league_id="123", season=2026, format=Format(), llm_backend="auto")
    save_config(cfg, path=cfg_path)

    tool_call_json = '{"tool": "evaluate_trade", "kwargs": {"give": ["Gibbs"], "get": ["Bijan"]}}'
    
    with patch("ff.cli.TerminalRunner") as MockRunner, \
         patch("ff.cli.build_rosters", return_value=[]), \
         patch("ff.cli.ValuesClient") as MockValuesClient, \
         patch("ff.cli.dispatch_tool", return_value={"give_total": 5000, "get_total": 5500}) as mock_dispatch:
        
        mock_inst = MagicMock()
        # First call returns tool call json, second call returns final text
        mock_inst.run.side_effect = [tool_call_json, "Final synthesized trade analysis: Bijan side is better."]
        MockRunner.return_value = mock_inst
        MockValuesClient.return_value.get_value_book.return_value = MagicMock()

        res = runner.invoke(app, ["ask", "Should I trade Gibbs for Bijan?"])
        assert res.exit_code == 0
        assert mock_dispatch.called
        assert "Bijan side is better" in res.output


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
