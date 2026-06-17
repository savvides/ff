"""Sleeper weekly projections (api.sleeper.com - the v2 host, not api.sleeper.app).

One GET returns every player's projected stat line for a season+week. We index
it by player_id (the same id Sleeper uses on rosters) so it joins onto a roster
directly, and keep only entries that actually carry a projection.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable

from ff.core.http import get_json

BASE = "https://api.sleeper.com"
PROJECTIONS_TTL = 3 * 3600  # projections move during the week; refresh a few times a day
SKILL_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")


class ProjectionsClient:
    def __init__(self, base: str = BASE) -> None:
        self.base = base

    def week(self, season: str, week: int,
             positions: Iterable[str] = SKILL_POSITIONS) -> Dict[str, Dict[str, Any]]:
        """Return {player_id: projected_stats} for the given season + week.

        The position filters are appended to the URL literally (Sleeper expects
        repeated `position[]=` params); building the query by hand keeps the
        bracket encoding unambiguous.
        """
        pos = "".join(f"&position[]={p}" for p in positions)
        url = (f"{self.base}/projections/nfl/{season}/{week}"
               f"?season_type=regular&order_by=ppr{pos}")
        data = get_json(url, ttl=PROJECTIONS_TTL)
        out: Dict[str, Dict[str, Any]] = {}
        for entry in data or []:
            stats = entry.get("stats") or {}
            pid = entry.get("player_id")
            if stats and pid is not None:
                out[str(pid)] = stats
        return out
