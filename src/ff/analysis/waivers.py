"""Waiver / trending targets: who is being added across Sleeper, joined to
dynasty value and to whether they are already rostered in *your* league.

The useful signal is the intersection: high dynasty value + trending up + still
a free agent in your league = grab them.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

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
) -> List[WaiverTarget]:
    rostered = {pid for r in rosters for pid in r.player_ids}

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
        targets.append(
            WaiverTarget(asset=asset, add_count=count, is_rostered=pid in rostered)
        )

    if free_agents_only:
        targets = [t for t in targets if not t.is_rostered]

    # Most valuable first, then hottest; value is what separates a real dynasty
    # add from a one-week-streamer add.
    targets.sort(key=lambda t: (t.asset.value, t.add_count), reverse=True)
    return targets[:limit]
