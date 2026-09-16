"""Depth chart opportunity multipliers and composite heuristic.

Formula: dynasty value x depth chart opportunity.

Translates NFL depth chart status and format scarcity into a continuous multiplier:
- Starters (order 1) carry full baseline opportunity (1.0).
- Primary backups / handcuffs (order 2) retain strong contingent value (e.g. RB2 0.80,
  Superflex QB2 0.75, WR2 0.90 in 3-WR sets).
- Rotational players (order 3) reflect realistic snap shares (WR3 0.75, RB3 0.45).
- Deep depth (order 4+) and unsigned free agents (team=None/FA) are appropriately discounted.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Set


def precompute_qb2_promotions(players_meta: Optional[Dict[str, Any]]) -> Set[str]:
    """Find QB3s on NFL teams where no active QB2 exists (post-cutdown gaps or QB2 ruled Out/IR)."""
    if not players_meta:
        return set()
    by_team_qbs: Dict[str, list[tuple[int, str, bool]]] = {}
    for pid, info in players_meta.items():
        team = info.get("team")
        pos = info.get("position")
        order = info.get("depth_chart_order")
        status = info.get("status")
        inj = info.get("injury_status")
        if (
            team
            and team not in ("FA", "None", "")
            and pos == "QB"
            and order is not None
        ):
            is_inactive = (
                status in ("Injured Reserve", "Out", "PUP", "DNR")
                or inj in ("Out", "IR", "PUP")
            )
            by_team_qbs.setdefault(team, []).append((int(order), str(pid), is_inactive))
    promoted: Set[str] = set()
    for team, qbs in by_team_qbs.items():
        has_qb1 = any(order == 1 for order, _, _ in qbs)
        has_active_qb2 = any(order == 2 and not is_inactive for order, _, is_inactive in qbs)
        if has_qb1 and not has_active_qb2:
            for order, pid, is_inactive in qbs:
                if order == 3 and not is_inactive:
                    promoted.add(pid)
    return promoted


def depth_chart_multiplier(
    position: Optional[str],
    depth_chart_order: Optional[int],
    team: Optional[str],
    is_superflex: bool = True,
) -> float:
    """Return depth chart opportunity multiplier (0.10 to 1.0)."""
    if not team or team in ("FA", "None", ""):
        return 0.25

    pos = (position or "").upper()
    order = depth_chart_order

    if order is None:
        if pos == "WR":
            return 0.25
        if pos == "QB":
            return 0.20 if is_superflex else 0.10
        if pos == "RB":
            return 0.20
        if pos == "TE":
            return 0.15
        return 0.10

    if pos == "QB":
        if order == 1:
            return 1.0
        if order == 2:
            return 0.75 if is_superflex else 0.35
        if order == 3:
            return 0.30 if is_superflex else 0.25
        return 0.10

    if pos == "RB":
        if order == 1:
            return 1.0
        if order == 2:
            return 0.80
        if order == 3:
            return 0.45
        if order == 4:
            return 0.20
        return 0.10

    if pos == "WR":
        if order == 1:
            return 1.0
        if order == 2:
            return 0.90
        if order == 3:
            return 0.75
        if order == 4:
            return 0.40
        return 0.15

    if pos == "TE":
        if order == 1:
            return 1.0
        if order == 2:
            return 0.55
        if order == 3:
            return 0.25
        return 0.10

    if order == 1:
        return 1.0
    return 0.10


def precompute_starter_injuries(
    players_meta: Optional[Dict[str, Any]],
) -> Dict[tuple[str, str], str]:
    """Find injuries to starters (depth_chart_order == 1) by (team, position)."""
    if not players_meta:
        return {}
    injuries: Dict[tuple[str, str], str] = {}
    for pid, info in players_meta.items():
        team = info.get("team")
        pos = info.get("position")
        order = info.get("depth_chart_order")
        injury = info.get("injury_status")
        status = info.get("status")
        if team and team not in ("FA", "None", "") and pos and order == 1:
            if injury:
                injuries[(team, pos)] = str(injury)
            elif status in ("Injured Reserve", "Out", "PUP", "DNR"):
                injuries[(team, pos)] = str(status)
    return injuries


def opportunity_score(
    value: int,
    position: Optional[str],
    depth_chart_order: Optional[int],
    team: Optional[str],
    is_superflex: bool = True,
    injury_status: Optional[str] = None,
    status: Optional[str] = None,
    starter_injury: Optional[str] = None,
) -> int:
    """Composite heuristic: dynasty value x depth chart opportunity x news/health factor."""
    pos = (position or "").upper()
    mult = depth_chart_multiplier(
        position, depth_chart_order, team, is_superflex=is_superflex
    )

    # Starter injury boost for direct backups / handcuffs (order == 2)
    if depth_chart_order == 2 and starter_injury:
        sinj = starter_injury.lower()
        if any(w in sinj for w in ("out", "ir", "injured reserve", "pup", "dnr")):
            mult = min(1.0, mult + 0.25)
        elif "doubtful" in sinj:
            mult = min(1.0, mult + 0.15)
        elif "questionable" in sinj:
            mult = min(1.0, mult + 0.10)

    # Base value with positional scarcity protection
    base = value if value > 0 else 50
    if (
        is_superflex
        and pos == "QB"
        and depth_chart_order == 2
        and team
        and team not in ("FA", "None", "")
    ):
        base = max(base, 400)

    # Player health/injury discount
    pinj = (
        injury_status
        or (status if status in ("Injured Reserve", "Out", "PUP", "DNR") else "")
    ).lower()
    if any(w in pinj for w in ("out", "ir", "injured reserve", "pup", "dnr")):
        health_factor = 0.50
    elif "doubtful" in pinj:
        health_factor = 0.70
    elif "questionable" in pinj:
        health_factor = 0.85
    else:
        health_factor = 1.0

    return round(base * mult * health_factor)
