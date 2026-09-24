"""Waiver / trending targets: who is being added across Sleeper, joined to
dynasty value and to whether they are already rostered in *your* league.

The useful signal is the intersection: high dynasty value + trending up + still
a free agent in your league = grab them.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ff.analysis.depth import (
    opportunity_score,
    precompute_qb2_promotions,
    precompute_starter_injuries,
)
from ff.contracts import Asset, Roster, WaiverTarget
from ff.sleeper import player_name
from ff.values import ValueBook


def waiver_targets(
    trending: List[Dict[str, Any]],
    book: ValueBook,
    rosters: List[Roster],
    players_meta: Optional[Dict[str, Any]] = None,
    limit: int = 25,
    free_agents_only: bool = True,
    is_superflex: bool = True,
    position: Optional[str] = None,
) -> List[WaiverTarget]:
    rostered = {pid for r in rosters for pid in r.player_ids}
    qb2_promoted = precompute_qb2_promotions(players_meta)
    starter_injuries = precompute_starter_injuries(players_meta)

    targets: List[WaiverTarget] = []
    for entry in trending:
        pid = str(entry.get("player_id"))
        count = int(entry.get("count", 0) or 0)
        valued = book.value_for_sleeper_id(pid)
        if valued is not None:
            asset = valued.model_copy()
        else:
            name, pos = pid, None
            if players_meta and pid in players_meta:
                m = players_meta[pid]
                name = player_name(pid, players_meta)
                pos = m.get("position")
            asset = Asset(id=pid, name=name, position=pos, value=0)
        meta = (players_meta or {}).get(pid, {})
        if meta:
            asset.fill_from_meta(meta)
        team = meta.get("team")
        order = 2 if str(pid) in qb2_promoted else meta.get("depth_chart_order")
        starter_inj = (
            starter_injuries.get((team, asset.position))
            if team and asset.position and order == 2
            else None
        )
        opp_score = opportunity_score(
            asset.value,
            asset.position,
            order,
            team,
            is_superflex=is_superflex,
            injury_status=meta.get("injury_status"),
            status=meta.get("status"),
            starter_injury=starter_inj,
        )
        targets.append(
            WaiverTarget(
                asset=asset,
                add_count=count,
                is_rostered=pid in rostered,
                team=team,
                depth_chart_order=order,
                opportunity_score=opp_score,
            )
        )

    if free_agents_only:
        targets = [t for t in targets if not t.is_rostered]
    if position:
        targets = [t for t in targets if t.asset.position == position.upper()]

    # Highest opportunity score first (dynasty value x depth chart), with raw value
    # and add_count breaking ties.
    targets.sort(
        key=lambda t: (
            t.opportunity_score if t.opportunity_score is not None else t.asset.value,
            t.asset.value,
            t.add_count,
        ),
        reverse=True,
    )
    return targets[:limit]
