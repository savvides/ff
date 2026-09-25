"""Unambiguous player lookup and whole-lineup start/sit comparisons."""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List

from ff.analysis.lineup import optimal_lineup, project_points
from ff.contracts import Roster
from ff.contracts.models import ComparisonOption, PlayerComparison, WeeklyContext


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9 ]", "", text).split())


def _aliases(pid: str, row: dict) -> set:
    first, last = row.get("first_name") or "", row.get("last_name") or ""
    full = row.get("full_name") or f"{first} {last}"
    aliases = {_normalize(full), _normalize(f"{first} {last}")}
    if not last and full:
        parts = full.split()
        if parts:
            first, last = parts[0], " ".join(parts[1:])
    if last:
        aliases |= {_normalize(first), _normalize(last), _normalize(f"{first[:1]} {last}")}
    # Common typed omission of a suffix is safe only when it stays unique.
    aliases |= {re.sub(r"\s+(jr|sr|ii|iii|iv)$", "", a) for a in list(aliases)}
    return (aliases | {pid}) - {""}


def resolve_player(text: str, players_meta: Dict[str, Any]) -> str:
    query = _normalize(text)
    matches = [pid for pid, row in players_meta.items() if query in _aliases(pid, row)]
    if len(matches) != 1:
        raise ValueError(f"Player '{text}' is {'ambiguous' if matches else 'not found'}; use a full name or Sleeper player ID.")
    return matches[0]


def comparison_players(query: str, players_meta: Dict[str, Any]) -> List[str]:
    """Find exactly two names, preferring full-name spans over contained surnames."""
    text = re.sub(r"\b(?:roster|team)\s*\d+\b", " ", _normalize(query))
    matches = []
    for pid, row in players_meta.items():
        for alias in _aliases(pid, row):
            for match in re.finditer(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", text):
                matches.append((match.start(), match.end(), pid))
    spans = [(a, b, p) for a, b, p in matches if not any(
        c <= a and d >= b and (c < a or d > b) for c, d, _ in matches)]
    grouped: Dict[tuple, set] = {}
    for a, b, pid in spans:
        grouped.setdefault((a, b), set()).add(pid)
    if any(len(pids) > 1 for pids in grouped.values()):
        raise ValueError("A player name is ambiguous; use both full names or Sleeper IDs.")
    ids = list(dict.fromkeys(next(iter(pids)) for _, pids in sorted(grouped.items())))
    if len(ids) != 2:
        raise ValueError("Name exactly two players for a start/sit comparison, using full names or Sleeper IDs.")
    return ids


def compare_players(player_ids: List[str], roster: Roster, projections: dict,
                    scoring: dict, roster_positions: List[str], meta: dict,
                    weekly: WeeklyContext, season: str, week: int) -> PlayerComparison:
    if len(player_ids) != 2 or len(set(player_ids)) != 2:
        raise ValueError("A comparison requires two different players")
    if any(pid not in roster.player_ids for pid in player_ids):
        raise ValueError("Start/sit comparisons require both players on the selected roster")
    baseline = optimal_lineup(roster, projections, scoring, roster_positions, meta,
                              season, week, weekly=weekly)
    options = []
    for pid, other in (player_ids, player_ids[::-1]):
        row = meta.get(pid, {})
        name = row.get("full_name") or " ".join(filter(None, [row.get("first_name"), row.get("last_name")])) or pid
        fact = weekly.players.get(pid)
        option = ComparisonOption(player_id=pid, name=name,
                                  projected_points=project_points(projections.get(pid, {}), scoring),
                                  availability=(fact.injury_status or "no injury designation") if fact else "unverified")
        try:
            option.lineup = optimal_lineup(roster, projections, scoring, roster_positions, meta,
                                           season, week, weekly=weekly, required_start=pid, exclude={other}, contingencies=False)
        except ValueError as exc:
            option.reason = str(exc)
        options.append(option)
    both = set(player_ids) <= {s.player_id for s in baseline.slots}
    legal = [o for o in options if o.lineup is not None]
    winner = max(legal, key=lambda o: o.lineup.total if o.lineup else float("-inf")) if legal else None
    totals = [o.lineup.total for o in legal if o.lineup is not None]
    difference = round(abs(totals[0] - totals[1]), 2) if len(totals) == 2 else None
    if both:
        recommendation = "Both players belong in the best available lineup. The table shows the cost of sitting either one."
    elif winner and difference == 0:
        recommendation = "The two legal choices have equal projected lineup totals."
    elif winner:
        recommendation = f"Start {winner.name}" + (f": +{difference:.2f} lineup points." if difference is not None else "; the other choice is unavailable or unverified.")
        if any(s.player_id == winner.player_id and s.locked for s in baseline.slots):
            recommendation = f"Keep {winner.name} in the locked slot; that starter can no longer be swapped."
        elif winner.availability.lower() in {"questionable", "doubtful"}:
            recommendation = "If active, " + recommendation[0].lower() + recommendation[1:]
    else:
        recommendation = "Neither exclusive choice is currently available; see the lock, eligibility or availability reasons."
    return PlayerComparison(options=options, baseline=baseline, recommendation=recommendation,
                            difference=difference)
