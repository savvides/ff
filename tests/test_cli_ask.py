from typer.testing import CliRunner
from unittest.mock import MagicMock, patch
import pytest

from ff.cli import app
from ff.core.config import Config, save_config, load_config
from ff.contracts import Format

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
        MockRunner.assert_called_once_with(backend="gemini")
        mock_inst.run.assert_called_once()
        assert "Mock answer" in res.output


def test_config_set_llm_command(tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr("ff.cli._config_path", lambda: cfg_path)
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
    monkeypatch.setattr("ff.cli._config_path", lambda: cfg_path)
    monkeypatch.setattr("ff.core.config._config_path", lambda: cfg_path)

    cfg = Config(league_id="123", season=2026, format=Format(), llm_backend="auto")
    save_config(cfg, path=cfg_path)

    res = runner.invoke(app, ["config", "set-llm", "invalid_backend"])
    assert res.exit_code != 0
    assert "Invalid backend" in res.output
