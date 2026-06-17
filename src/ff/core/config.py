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
    season: str
    name: str = ""
    format: Format = Format()
    username: Optional[str] = None
    user_id: Optional[str] = None


def load_config() -> Config:
    path = _config_path()
    if not path.exists():
        raise FileNotFoundError(
            "No league configured yet. Run `ff setup <sleeper-username>` first."
        )
    return Config.model_validate_json(path.read_text())


def save_config(cfg: Config) -> Path:
    home().mkdir(parents=True, exist_ok=True)
    path = _config_path()
    path.write_text(cfg.model_dump_json(indent=2))
    return path


def config_exists() -> bool:
    return _config_path().exists()
