"""Unrostered players ranked by dynasty opportunity, with optional trending filter."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ff.analysis.depth import (
    opportunity_score,
    precompute_qb2_promotions,
    precompute_starter_injuries,
)
from ff.analysis.lineup import SLOT_ELIGIBILITY
from ff.contracts import Asset, Roster, WaiverTarget
from ff.sleeper import player_name
from ff.values import ValueBook


def waiver_positions(roster_positions: List[str]) -> set:
    # Overlapping flexes need no lineup optimization here, only eligibility.
    slots = {**SLOT_ELIGIBILITY, "WRRB_FLEX": {"WR", "RB"}, "REC_FLEX": {"WR", "TE"}}
    return set().union(*(slots.get(slot, {slot}) for slot in roster_positions))


def waiver_targets(
    trending: List[Dict[str, Any]],
    book: ValueBook,
    rosters: List[Roster],
    players_meta: Optional[Dict[str, Any]] = None,
    limit: int = 25,
    free_agents_only: bool = True,
    is_superflex: bool = True,
    position: Optional[str] = None,
    roster_positions: Optional[List[str]] = None,
    trending_only: bool = False,
) -> List[WaiverTarget]:
    rostered = {pid for r in rosters for pid in r.player_ids}
    qb2_promoted = precompute_qb2_promotions(players_meta)
    starter_injuries = precompute_starter_injuries(players_meta)

    # Trending is an annotation, not the universe of available players. Include
    # active NFL players and market-valued unsigned prospects even without adds.
    counts = {str(e["player_id"]): int(e.get("count", 0) or 0) for e in trending}
    candidates = set(counts)
    if not trending_only:
        candidates.update(book.by_sleeper_id)
        candidates.update(pid for pid, m in (players_meta or {}).items()
                          if m.get("active") is not False and m.get("team") not in (None, "", "FA"))
    eligible_positions = {"QB", "RB", "WR", "TE", "K", "DEF"}
    if roster_positions is not None:
        eligible_positions = waiver_positions(roster_positions)

    targets: List[WaiverTarget] = []
    for pid in sorted(candidates):
        count = counts.get(pid, 0)
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
        if meta.get("active") is False or asset.position not in eligible_positions:
            continue
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
