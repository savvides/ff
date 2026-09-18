from pathlib import Path

import pytest

from ff.core.config import Config, load_config, save_config, cache_dir


def test_llm_config_defaults(tmp_path: Path) -> None:
    cfg = Config(league_id="123456", season=2026, llm_backend="gemini")
    assert cfg.llm_backend == "gemini"
    assert cfg.ollama_model == "llama3.2"

    cfg_file = tmp_path / "config.json"
    save_config(cfg, path=cfg_file)
    loaded = load_config(path=cfg_file)
    assert loaded.llm_backend == "gemini"


def test_cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Point FF_HOME to our temporary directory to isolate state
    ff_home = tmp_path / ".ff"
    monkeypatch.setenv("FF_HOME", str(ff_home))

    # Test directory creation
    d = cache_dir()

    assert d == ff_home / "cache"
    assert d.exists()
    assert d.is_dir()

    # Test idempotence (exist_ok=True)
    d2 = cache_dir()
    assert d2 == d
    assert d2.exists()
