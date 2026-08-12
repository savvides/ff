"""Local state: where ff keeps its config + cache, and the saved-league config.

Everything lives under FF_HOME (default `./.ff`, gitignored). Nothing here is
machine-shared, so two checkouts never collide.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from ff.contracts import Format


def home() -> Path:
    """Root for all local ff state. Override with FF_HOME."""
    root = os.environ.get("FF_HOME")
    return Path(root).expanduser() if root else Path.cwd() / ".ff"


def cache_dir() -> Path:
    d = home() / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _config_path() -> Path:
    return home() / "config.json"


class Config(BaseModel):
    """The saved league. Written once by `ff setup`, read by every command."""

    league_id: str
    season: int
    name: str = ""
    format: Format = Format()
    username: Optional[str] = None
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    league_name: Optional[str] = None
    # LLM Terminal Runner settings
    llm_backend: str = "auto"  # "auto" | "agy" | "gemini" | "claude" | "ollama"
    ollama_model: str = "llama3.2"


def load_config(path: Optional[Path] = None) -> Config:
    p = path or _config_path()
    if not p.exists():
        raise FileNotFoundError(
            "No league configured yet. Run `ff setup <sleeper-username>` first."
        )
    return Config.model_validate_json(p.read_text())


def save_config(cfg: Config, path: Optional[Path] = None) -> Path:
    p = path or _config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(cfg.model_dump_json(indent=2))
    return p


def config_exists(path: Optional[Path] = None) -> bool:
    p = path or _config_path()
    return p.exists()

