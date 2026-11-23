"""Waiver-budget (FAB) history: what this league actually pays.

Pure. Reads Sleeper transaction rows: a `waiver` row with status `complete` is
a winning bid (`settings.waiver_bid`); a `failed` row whose note says another
owner claimed the player is a losing bid in the same waiver run. Other failures
(roster full, player locked) say nothing about price and are ignored.
"""

from __future__ import annotations

import statistics
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ff.contracts import FabClaim

_OUTBID = "claimed by another owner"


def _bid(row: Dict[str, Any]) -> Optional[Tuple[str, int, int]]:
    """(player_id, roster_id, bid) for a single-player waiver claim, else None."""
    adds = row.get("adds") or {}
    bid = (row.get("settings") or {}).get("waiver_bid")
    if row.get("type") != "waiver" or len(adds) != 1 or isinstance(bid, bool) or not isinstance(bid, int) or bid < 0:
        return None
    (pid, rid), = adds.items()
    return str(pid), int(rid), bid


def winning_bids(transactions: Sequence[Dict[str, Any]]) -> List[FabClaim]:
    """Every winning bid, newest first, joined to the losing bids it beat."""
    losers: Dict[Tuple[int, str], Dict[int, int]] = {}  # (week, player) -> {roster: best bid}
    for row in transactions:
        parsed = _bid(row)
        note = (row.get("metadata") or {}).get("notes") or ""
        if parsed and row.get("status") == "failed" and _OUTBID in note:
            pid, rid, bid = parsed
            by_team = losers.setdefault((int(row.get("leg") or 0), pid), {})
            by_team[rid] = max(bid, by_team.get(rid, 0))
    out: List[Tuple[int, FabClaim]] = []
    for row in transactions:
        parsed = _bid(row)
        if not parsed or row.get("status") != "complete":
            continue
        pid, rid, bid = parsed
        week = int(row.get("leg") or 0)
        lost = {r: b for r, b in losers.get((week, pid), {}).items() if r != rid}
        out.append((int(row.get("status_updated") or 0), FabClaim(
            player_id=pid, roster_id=rid, week=week, bid=bid,
            runner_up=max(lost.values()) if lost else None, bidders=1 + len(lost))))
    out.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in out]


def bid_summary(bids: Sequence[int]) -> Optional[Dict[str, float]]:
    """n / median / 75th percentile / max of a set of bids, None when empty."""
    if not bids:
        return None
    xs = sorted(bids)
    p75 = xs[min(len(xs) - 1, round(0.75 * (len(xs) - 1)))]
    return {"n": len(xs), "median": statistics.median(xs), "p75": p75, "max": xs[-1]}
