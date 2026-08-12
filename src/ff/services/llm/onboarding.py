from __future__ import annotations

from pathlib import Path
from typing import Optional, Any

from ff.contracts import Format
from ff.core.config import Config, save_config
from ff.sleeper import client as sleeper_client


def onboard_user(username: str, config_path: Optional[Path] = None) -> Config:
    try:
        user = sleeper_client.get_user(username)
        user_id = user["user_id"] if isinstance(user, dict) else username
    except Exception:
        user_id = username

    leagues = sleeper_client.get_user_leagues(user_id)
    if not leagues:
        raise ValueError(f"No active leagues found for user '{username}'.")

    league = leagues[0]  # Default to first league
    league_id = league["league_id"]

    try:
        raw_fmt: Any = sleeper_client.detect_format(league_id)
    except Exception:
        raw_fmt = sleeper_client.detect_format(league)

    if isinstance(raw_fmt, Format):
        fmt = raw_fmt
    elif isinstance(raw_fmt, dict):
        fmt = Format(**raw_fmt)
    else:
        is_sf = getattr(raw_fmt, "superflex", getattr(raw_fmt, "is_superflex", False))
        ppr_val = getattr(raw_fmt, "ppr", 1.0)
        fmt = Format(superflex=bool(is_sf), ppr=float(ppr_val) if ppr_val is not None else 1.0)

    cfg = Config(
        league_id=league_id,
        season=int(league.get("season", 2026)),
        user_id=user_id,
        user_name=username,
        username=username,
        league_name=league.get("name", ""),
        name=league.get("name", ""),
        format=fmt,
    )
    save_config(cfg, path=config_path)
    return cfg
