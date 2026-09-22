from pathlib import Path

import pytest

from ff.core.config import Config, cache_dir, config_exists, home, load_config, save_config


def test_home_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FF_HOME", raising=False)
    assert home() == Path.cwd() / ".ff"


def test_home_custom_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FF_HOME", "/tmp/custom_ff_home")
    assert home() == Path("/tmp/custom_ff_home")


def test_home_expanduser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FF_HOME", "~/custom_ff_home")
    assert home() == Path("~/custom_ff_home").expanduser()


def test_cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ff_home = tmp_path / ".ff"
    monkeypatch.setenv("FF_HOME", str(ff_home))

    d = cache_dir()
    assert d == ff_home / "cache"
    assert d.exists()
    assert d.is_dir()

    d2 = cache_dir()
    assert d2 == d
    assert d2.exists()


def test_config_exists(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.json"
    assert not config_exists(path=cfg_file)

    cfg = Config(league_id="123456", season=2026, llm_backend="gemini")
    save_config(cfg, path=cfg_file)

    assert config_exists(path=cfg_file)


def test_llm_config_defaults(tmp_path: Path) -> None:
    cfg = Config(league_id="123456", season=2026, llm_backend="gemini")
    assert cfg.llm_backend == "gemini"
    assert cfg.ollama_model == "llama3.2"

    cfg_file = tmp_path / "config.json"
    save_config(cfg, path=cfg_file)
    loaded = load_config(path=cfg_file)
    assert loaded.llm_backend == "gemini"
