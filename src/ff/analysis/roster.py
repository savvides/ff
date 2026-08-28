"""Price a Sleeper roster with dynasty values."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ff.contracts import Asset, Roster, RosterValuation
from ff.sleeper import player_name
from ff.values import ValueBook



def value_roster(
    roster: Roster,
    book: ValueBook,
    players_meta: Optional[Dict[str, Any]] = None,
) -> RosterValuation:
    """Build a priced valuation for one roster.

    Players FantasyCalc covers contribute their dynasty value; everyone else
    (kickers, defenses, deep bench) is listed under `unvalued` at value 0 so the
    roster view is still complete.
    """
    assets: List[Asset] = []
    unvalued: List[str] = []
    by_position: Dict[str, int] = {}
    starters = set(roster.starters)
    starters_value = 0

    for pid in roster.player_ids:
        valued = book.value_for_sleeper_id(pid)
        if valued is not None:
            asset = valued.model_copy()
        else:
            asset = Asset(
                id=pid,
                name=player_name(pid, players_meta),
                position=(players_meta or {}).get(pid, {}).get("position"),
                value=0,
            )
            unvalued.append(pid)

        asset.fill_from_meta((players_meta or {}).get(pid))
        assets.append(asset)
        pos = asset.position or "NA"
        by_position[pos] = by_position.get(pos, 0) + asset.value
        if pid in starters:
            starters_value += asset.value

    assets.sort(key=lambda a: a.value, reverse=True)
    return RosterValuation(
        roster_id=roster.roster_id,
        team_name=roster.team_name,
        total_value=sum(a.value for a in assets),
        starters_value=starters_value,
        by_position=by_position,
        assets=assets,
        unvalued=unvalued,
    )


def value_all_rosters(
    rosters: List[Roster],
    book: ValueBook,
    players_meta: Optional[Dict[str, Any]] = None,
) -> List[RosterValuation]:
    """Value every roster and assign power ranks (1 = most valuable)."""
    valuations = [value_roster(r, book, players_meta) for r in rosters]
    ordered = sorted(valuations, key=lambda v: v.total_value, reverse=True)
    for rank, v in enumerate(ordered, start=1):
        v.power_rank = rank
    return ordered
