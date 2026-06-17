"""Sleeper public API (https://docs.sleeper.com/).

Only the endpoints ff needs. Everything is a plain GET of JSON; the value-add
here is (a) caching via ff.core.http and (b) translating Sleeper's settings into
our `Format` so FantasyCalc gets queried correctly.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ff.contracts import Format, Roster
from ff.core.http import get_json

BASE = "https://api.sleeper.app/v1"

# Per Sleeper's docs: fetch the players file at most once a day; it is ~15MB.
PLAYERS_TTL = 24 * 3600
TRENDING_TTL = 3600
LEAGUE_TTL = 1800  # rosters/transactions move during the season


class SleeperClient:
    """Thin, cached wrapper over the Sleeper REST API."""

    def __init__(self, base: str = BASE) -> None:
        self.base = base

    # --- generic ---------------------------------------------------------
    def _get(self, path: str, *, ttl: Optional[float] = LEAGUE_TTL,
             params: Optional[Dict[str, Any]] = None) -> Any:
        return get_json(f"{self.base}/{path}", params=params, ttl=ttl)

    # --- state / users ---------------------------------------------------
    def state(self, sport: str = "nfl") -> Dict[str, Any]:
        return self._get(f"state/{sport}", ttl=3600)

    def user(self, username_or_id: str) -> Optional[Dict[str, Any]]:
        return self._get(f"user/{username_or_id}", ttl=24 * 3600)

    def user_leagues(self, user_id: str, season: str,
                     sport: str = "nfl") -> List[Dict[str, Any]]:
        return self._get(f"user/{user_id}/leagues/{sport}/{season}", ttl=3600) or []

    # --- league ----------------------------------------------------------
    def league(self, league_id: str) -> Dict[str, Any]:
        return self._get(f"league/{league_id}", ttl=LEAGUE_TTL)

    def rosters(self, league_id: str) -> List[Dict[str, Any]]:
        return self._get(f"league/{league_id}/rosters", ttl=LEAGUE_TTL) or []

    def league_users(self, league_id: str) -> List[Dict[str, Any]]:
        return self._get(f"league/{league_id}/users", ttl=LEAGUE_TTL) or []

    def matchups(self, league_id: str, week: int) -> List[Dict[str, Any]]:
        return self._get(f"league/{league_id}/matchups/{week}", ttl=LEAGUE_TTL) or []

    def transactions(self, league_id: str, week: int) -> List[Dict[str, Any]]:
        return self._get(f"league/{league_id}/transactions/{week}", ttl=LEAGUE_TTL) or []

    def traded_picks(self, league_id: str) -> List[Dict[str, Any]]:
        return self._get(f"league/{league_id}/traded_picks", ttl=LEAGUE_TTL) or []

    # --- players / trending ---------------------------------------------
    def players(self, sport: str = "nfl") -> Dict[str, Any]:
        return self._get(f"players/{sport}", ttl=PLAYERS_TTL)

    def trending(self, sport: str = "nfl", kind: str = "add",
                 lookback_hours: int = 24, limit: int = 25) -> List[Dict[str, Any]]:
        return self._get(
            f"players/{sport}/trending/{kind}",
            ttl=TRENDING_TTL,
            params={"lookback_hours": lookback_hours, "limit": limit},
        ) or []


# --- pure helpers (no I/O) ----------------------------------------------

def detect_format(league: Dict[str, Any]) -> Format:
    """Derive a `Format` from a Sleeper league object.

    This is the keystone: we never ask the user for superflex/PPR/team count -
    Sleeper already knows, so the values we pull are always right for the league.
    """
    positions: List[str] = league.get("roster_positions") or []
    superflex = "SUPER_FLEX" in positions
    num_qbs = positions.count("QB") + positions.count("SUPER_FLEX")
    num_qbs = max(1, min(2, num_qbs))  # FantasyCalc supports 1 or 2

    scoring = league.get("scoring_settings") or {}
    rec = float(scoring.get("rec", 0.0) or 0.0)
    ppr = 1.0 if rec >= 1.0 else (0.5 if rec >= 0.5 else 0.0)

    settings = league.get("settings") or {}
    league_type = settings.get("type", 2)  # 0 redraft, 1 keeper, 2 dynasty

    return Format(
        is_dynasty=league_type == 2,
        superflex=superflex,
        num_qbs=num_qbs,
        num_teams=int(league.get("total_rosters") or 12),
        ppr=ppr,
        tep=float(scoring.get("bonus_rec_te", 0.0) or 0.0),
    )


def team_names(users: List[Dict[str, Any]]) -> Dict[str, str]:
    """owner_id -> display name (team name if set, else username)."""
    out: Dict[str, str] = {}
    for u in users:
        meta = u.get("metadata") or {}
        name = meta.get("team_name") or u.get("display_name") or "Unknown"
        out[u["user_id"]] = name
    return out


def build_rosters(rosters: List[Dict[str, Any]],
                  users: List[Dict[str, Any]]) -> List[Roster]:
    """Combine /rosters + /users into the contract's `Roster` list."""
    names = team_names(users)
    out: List[Roster] = []
    for r in rosters:
        settings = r.get("settings") or {}
        pts = float(settings.get("fpts", 0) or 0)
        pts += float(settings.get("fpts_decimal", 0) or 0) / 100.0
        out.append(
            Roster(
                roster_id=r["roster_id"],
                owner_id=r.get("owner_id"),
                team_name=names.get(r.get("owner_id"), f"Team {r['roster_id']}"),
                player_ids=[p for p in (r.get("players") or []) if p],
                starters=[p for p in (r.get("starters") or []) if p and p != "0"],
                wins=int(settings.get("wins", 0) or 0),
                losses=int(settings.get("losses", 0) or 0),
                ties=int(settings.get("ties", 0) or 0),
                points_for=pts,
            )
        )
    return out
