"""Fresh I/O for weekly decisions. Calculations remain in analysis/.

The public schedule/player feeds are undocumented. Validate joins and fail closed
on unknown timing; never substitute a stale full-player cache for fresh status.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

from ff.contracts import Roster, NewsItem
from ff.contracts.models import WeeklyContext, WeeklyPlayer
from ff.core.http import get_json
from ff.sleeper import SleeperClient

SCHEDULE = "https://api.sleeper.com/schedule/nfl/regular"
SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
TEAM_ALIASES = {"WSH": "WAS", "LA": "LAR"}


def _team(value: str) -> str:
    return TEAM_ALIASES.get(value, value)


def game_facts(schedule: List[dict], scoreboard: dict, season: str,
               week: int) -> Dict[str, Tuple[str, Any]]:
    """Cross-check week and opponents before trusting an exact kickoff."""
    if not isinstance(schedule, list) or not isinstance(scoreboard, dict):
        raise ValueError("Schedule feed returned an unexpected shape")
    if (str(scoreboard.get("season", {}).get("year")) != season
            or scoreboard.get("season", {}).get("type") != 2
            or scoreboard.get("week", {}).get("number") != week):
        raise ValueError("Scoreboard season/week does not match the requested regular-season week")
    scheduled = [g for g in schedule if g.get("week") == week]
    if not scheduled:
        raise ValueError("No verified schedule for this week")
    espn = {}
    for event in scoreboard.get("events", []):
        for competition in event.get("competitions", []):
            pair = frozenset(_team(c["team"]["abbreviation"]) for c in competition.get("competitors", []))
            if len(pair) != 2 or pair in espn:
                raise ValueError("Ambiguous scoreboard team pairing")
            espn[pair] = competition
    out: Dict[str, Tuple[str, Any]] = {}
    for game in scheduled:
        pair = frozenset((_team(game["home"]), _team(game["away"])))
        competition = espn.get(pair, {})
        kind = competition.get("status", {}).get("type", {})
        kickoff = None
        try:
            kickoff = datetime.fromisoformat(competition["date"].replace("Z", "+00:00"))
            if kickoff.tzinfo is None:
                kickoff = None
        except (ValueError, KeyError, TypeError):
            pass
        status = "unknown"
        sleeper_status = game.get("status")
        if kind.get("name") == "STATUS_SCHEDULED" and sleeper_status == "pre_game" and kickoff:
            status = "scheduled"
        elif kind.get("completed") is True and sleeper_status == "complete":
            status = "final"
        elif kind.get("state") == "in" and sleeper_status in {"in_progress", "in_game", "halftime"}:
            status = "live"
        for team in pair:
            if team in out:
                raise ValueError("Multiple games for one team in this week")
            out[team] = status, kickoff
    if set(espn) != {frozenset((_team(g["home"]), _team(g["away"]))) for g in scheduled}:
        raise ValueError("Schedule sources disagree about this week's games")
    return out


def build_weekly(roster: Roster, meta: Dict[str, Any], games: Dict[str, tuple],
                 matchup: dict, settings: dict, roster_positions: List[str],
                 as_of: datetime) -> WeeklyContext:
    context = WeeklyContext(as_of=as_of)
    if settings.get("best_ball"):
        context.blocked_reason = "Best-ball leagues do not use manual start/sit decisions"
    if settings.get("max_subs"):
        context.blocked_reason = "AutoSubs are enabled; pairing locks cannot yet be verified through these feeds"
    matchup_starters = [str(p) if p else "0" for p in (matchup.get("starters") or [])]
    if matchup_starters != roster.starters:
        raise ValueError("Roster and matchup starters changed or disagree; rerun for a fresh snapshot")
    for pid, row in meta.items():
        team = _team(row.get("team") or "")
        status, kickoff = games.get(team, ("bye", None)) if team else ("unknown", None)
        injury = row.get("injury_status")
        if row.get("status") in {"Injured Reserve", "Suspended", "PUP", "Inactive"}:
            injury = row["status"]
        context.players[pid] = WeeklyPlayer(
            game_status=status, kickoff=kickoff, injury_status=injury,
            actual=(matchup.get("players_points") or {}).get(pid),
            source=f"https://api.sleeper.com/players/nfl/{pid}",
        )
    for pid in roster.player_ids:
        if pid not in context.players:
            context.players[pid] = WeeklyPlayer()
    # A now-healthy IR occupant can block *all* roster changes on Sleeper.
    ir_allowed = {"ir", "injured reserve", "pup", "physically unable to perform"}
    for key, statuses in {"out": {"out"}, "sus": {"sus", "suspended"}, "doubtful": {"doubtful"},
                          "na": {"na", "inactive"}, "dnr": {"dnr"}, "cov": {"cov"}}.items():
        if settings.get("reserve_allow_" + key):
            ir_allowed |= statuses
    for pid in roster.reserve:
        if (context.players[pid].injury_status or "").lower() not in ir_allowed:
            context.blocked_reason = "IR eligibility is unverified or invalid; resolve the roster lock in Sleeper first"
    active_count = len(set(roster.player_ids) - set(roster.reserve) - set(roster.taxi))
    capacity = sum(s not in {"IR", "TAXI"} for s in roster_positions)
    if active_count > capacity or settings.get("capacity_override"):
        context.blocked_reason = "Roster capacity must be resolved in Sleeper before lineup changes"
    return context


def load_weekly(sc: SleeperClient, league_id: str, roster: Roster, season: str,
                week: int, league: dict, meta: Dict[str, Any],
                candidate_meta: Optional[Dict[str, Any]] = None) -> Tuple[WeeklyContext, Dict[str, Any]]:
    schedule = get_json(f"{SCHEDULE}/{season}", ttl=0)
    scoreboard = get_json(SCOREBOARD, params={"dates": season, "seasontype": 2, "week": week}, ttl=0)
    games = game_facts(schedule, scoreboard, season, week)
    fresh = dict(meta)
    fresh.update(candidate_meta or {})
    for pid in roster.player_ids:
        row = sc.player(pid)
        if not isinstance(row, dict) or str(row.get("player_id")) != pid or "injury_status" not in row:
            raise ValueError(f"Fresh availability unavailable for player {pid}")
        fresh[pid] = row
    matchups = sc.matchups(league_id, week)
    matchup = next((m for m in matchups if m.get("roster_id") == roster.roster_id), None)
    if matchup is None:
        raise ValueError("No current-week matchup snapshot for this roster")
    verified = {**(candidate_meta or {}), **{p: fresh[p] for p in roster.player_ids}}
    context = build_weekly(roster, verified, games, matchup, league.get("settings") or {},
                           league.get("roster_positions") or [], datetime.now(timezone.utc))
    for pid in set(candidate_meta or {}) - set(roster.player_ids):
        context.players[pid].source = f"https://api.sleeper.com/projections/nfl/{season}/{week}?season_type=regular"
    for pid in roster.player_ids:
        if (context.players[pid].injury_status or "").lower() not in {"questionable", "doubtful"}:
            continue
        name = " ".join(filter(None, [fresh[pid].get("first_name"), fresh[pid].get("last_name")])) or pid
        try:
            reports = [NewsItem.from_payload(item) for item in sc.player_news(pid)]
            dated = sorted((r for r in reports if r.published and r.url), key=lambda r: r.published or 0, reverse=True)
            if dated:
                item = dated[0]
                context.warnings.append(f"Reporting context for {name} ({item.published_date}, {item.source}): {item.title} {item.url}")
            else:
                context.warnings.append(f"{name}: no dated reporting available; availability uses Sleeper's current designation.")
        except (requests.RequestException, ValueError, TypeError):
            context.warnings.append(f"{name}: news unavailable; availability uses Sleeper's current designation.")
    return context, fresh
