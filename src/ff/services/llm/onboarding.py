from __future__ import annotations

from pathlib import Path
from typing import Optional

from ff.contracts import Format
from ff.core.config import Config, save_config
from ff.sleeper import client as sleeper_client


def onboard_user(
    username: str,
    config_path: Optional[Path] = None,
    league_id: Optional[str] = None,
) -> Config:
    """Save a league config for `username`.

    Unlike `ff setup`, this is non-interactive: it only writes when the league
    is unambiguous (one league, or an explicit `league_id`). Multiple leagues
    without an id is an error pointing at `ff setup`.
    """
    try:
        user = sleeper_client.get_user(username)
        user_id = user["user_id"] if isinstance(user, dict) else username
    except Exception:
        user_id = username

    leagues = sleeper_client.get_user_leagues(user_id)
    if not leagues:
        raise ValueError(f"No active leagues found for user '{username}'.")

    if league_id:
        league = next((lg for lg in leagues if str(lg.get("league_id")) == str(league_id)), None)
        if league is None:
            raise ValueError(f"league '{league_id}' not found for user '{username}'.")
    elif len(leagues) == 1:
        league = leagues[0]
    else:
        names = ", ".join(
            f"{lg.get('name')} ({lg.get('league_id')})" for lg in leagues
        )
        raise ValueError(
            f"'{username}' is in {len(leagues)} leagues: {names}. "
            "Run `ff setup <username>` to pick one."
        )

    raw_fmt = sleeper_client.detect_format(league)
    if isinstance(raw_fmt, Format):
        fmt = raw_fmt
    elif isinstance(raw_fmt, dict):
        fmt = Format.model_validate(raw_fmt)
    else:
        try:
            fmt = Format.model_validate(raw_fmt)
        except Exception:
            fmt = Format(
                superflex=bool(getattr(raw_fmt, "is_superflex", False) or getattr(raw_fmt, "superflex", False)),
                ppr=float(getattr(raw_fmt, "ppr", 0.5) or 0.5),
            )

    cfg = Config(
        league_id=str(league["league_id"]),
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
