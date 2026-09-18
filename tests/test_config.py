import os
from pathlib import Path

import pytest

from ff.core.config import Config, home, load_config, save_config


def test_home_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FF_HOME", raising=False)
    assert home() == Path.cwd() / ".ff"


def test_home_custom_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FF_HOME", "/tmp/custom_ff_home")
    assert home() == Path("/tmp/custom_ff_home")


def test_home_expanduser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FF_HOME", "~/custom_ff_home")
    assert home() == Path("~/custom_ff_home").expanduser()


def test_llm_config_defaults(tmp_path: Path) -> None:
    cfg = Config(league_id="123456", season=2026, llm_backend="gemini")
    assert cfg.llm_backend == "gemini"
    assert cfg.ollama_model == "llama3.2"

    cfg_file = tmp_path / "config.json"
    save_config(cfg, path=cfg_file)
    loaded = load_config(path=cfg_file)
    assert loaded.llm_backend == "gemini"
