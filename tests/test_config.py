from pathlib import Path

from ff.core.config import Config, load_config, save_config


def test_llm_config_defaults(tmp_path: Path) -> None:
    cfg = Config(league_id="123456", season=2026, llm_backend="gemini")
    assert cfg.llm_backend == "gemini"
    assert cfg.ollama_model == "llama3.2"

    cfg_file = tmp_path / "config.json"
    save_config(cfg, path=cfg_file)
    loaded = load_config(path=cfg_file)
    assert loaded.llm_backend == "gemini"

def test_cache_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FF_HOME", str(tmp_path))
    from ff.core.config import cache_dir

    d = cache_dir()
    assert d == tmp_path / "cache"
    assert d.exists()
    assert d.is_dir()
