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
    """Find QB3s on NFL teams where no QB2 exists (e.g. post-cutdown 2-QB depth charts)."""
    if not players_meta:
        return set()
    by_team_qbs: Dict[str, list[tuple[int, str]]] = {}
    for pid, info in players_meta.items():
        team = info.get("team")
        pos = info.get("position")
        order = info.get("depth_chart_order")
        status = info.get("status")
        if (
            team
            and team not in ("FA", "None")
            and pos == "QB"
            and order is not None
            and status != "Injured Reserve"
        ):
            by_team_qbs.setdefault(team, []).append((int(order), str(pid)))
    promoted: Set[str] = set()
    for team, qbs in by_team_qbs.items():
        orders = {order for order, _ in qbs}
        if 1 in orders and 2 not in orders and 3 in orders:
            for order, pid in qbs:
                if order == 3:
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


def opportunity_score(
    value: int,
    position: Optional[str],
    depth_chart_order: Optional[int],
    team: Optional[str],
    is_superflex: bool = True,
) -> int:
    """Composite heuristic: dynasty value x depth chart multiplier."""
    mult = depth_chart_multiplier(
        position, depth_chart_order, team, is_superflex=is_superflex
    )
    base = value if value > 0 else 50
    return round(base * mult)
