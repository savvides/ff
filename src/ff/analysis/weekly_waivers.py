"""Rank the full projected unrostered pool by this roster's lineup gain."""
from __future__ import annotations

from typing import List, Optional

from ff.analysis.lineup import game_locked, optimal_lineup, project_points, unavailable
from ff.analysis.waivers import waiver_positions
from ff.contracts import Roster
from ff.contracts.models import WeeklyContext, WeeklyWaivers, WeeklyWaiverTarget


def weekly_waivers(roster: Roster, rosters: List[Roster], projections: dict,
                   scoring: dict, roster_positions: List[str], meta: dict,
                   weekly: WeeklyContext, season: str, week: int,
                   position: Optional[str] = None, limit: int = 20,
                   trending_ids: Optional[set] = None) -> WeeklyWaivers:
    baseline = optimal_lineup(roster, projections, scoring, roster_positions, meta,
                              season, week, weekly=weekly)
    owned = {pid for r in rosters for pid in r.player_ids}
    allowed = waiver_positions(roster_positions) - {"BN", "IR", "TAXI"}
    if position and position.upper() not in allowed:
        raise ValueError("Requested position is not a starting position in this league")
    selected = {s.player_id: s.name for s in baseline.slots if s.player_id}
    targets = []
    unverified = 0
    for pid in sorted(projections):
        row = meta.get(pid, {})
        pos = row.get("position")
        if (pid in owned or pos not in allowed or row.get("active") is False
                or (position and pos != position.upper())
                or (trending_ids is not None and pid not in trending_ids)):
            continue
        fact = weekly.players.get(pid)
        if fact is None or fact.game_status == "unknown" or (fact.game_status == "scheduled" and (fact.kickoff is None or fact.kickoff.tzinfo is None)):
            unverified += 1
            continue
        if fact.game_status != "scheduled" or game_locked(fact, weekly) or unavailable(fact):
            continue
        augmented = roster.model_copy(update={"player_ids": roster.player_ids + [pid]})
        lineup = optimal_lineup(augmented, projections, scoring, roster_positions, meta,
                                season, week, weekly=weekly, contingencies=False)
        new_ids = {s.player_id for s in lineup.slots}
        gain = round(max(0, lineup.total - baseline.total), 2)
        name = row.get("full_name") or " ".join(filter(None, [row.get("first_name"), row.get("last_name")])) or pid
        targets.append(WeeklyWaiverTarget(
            player_id=pid, name=name, position=pos,
            projected_points=project_points(projections[pid], scoring), lineup_gain=gain,
            displaced=[name for p, name in selected.items() if p not in new_ids] if gain > 0 else [],
            availability=fact.injury_status or "no injury designation", kickoff=fact.kickoff))
    targets.sort(key=lambda t: (-t.lineup_gain, -t.projected_points, t.name, t.player_id))
    warnings = [f"{unverified} projected unrostered candidates excluded because fresh availability or timing could not be verified."] if unverified else []
    return WeeklyWaivers(baseline=baseline, targets=targets[:max(0, limit)],
                         candidates_evaluated=len(targets), warnings=warnings)
