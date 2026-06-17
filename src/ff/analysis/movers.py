"""Buy-low / sell-high candidates from the dynasty-vs-redraft value gap.

FantasyCalc gives every player both a dynasty value and a win-now (redraft)
value. When win-now far exceeds dynasty the player is an aging asset to sell
high; the reverse is a young, ascending buy-low. The data is already on each
Asset; this just ranks by the gap.
"""

from __future__ import annotations

from typing import List, Tuple

from ff.contracts import Asset
from ff.values import ValueBook


def top_movers(book: ValueBook, buy: bool = False, limit: int = 20,
               min_value: int = 1000) -> List[Tuple[Asset, float]]:
    """Return (asset, gap_pct) ranked.

    gap_pct = (dynasty - redraft) / redraft * 100.
      buy=True  -> dynasty >> redraft first (buy-low, young upside).
      buy=False -> redraft >> dynasty first (sell-high, aging win-now value).

    `min_value` floors BOTH values so the list is real contributors. Without it,
    deep stashes with redraft ~1 produce meaningless +100000% gaps and bury the
    genuine buy-lows. Players below the floor in either value are dropped.
    """
    scored: List[Tuple[Asset, float]] = []
    for a in book.assets:
        if a.is_pick or not a.redraft_value:
            continue
        if a.value < min_value or a.redraft_value < min_value:
            continue
        pct = (a.value - a.redraft_value) / a.redraft_value * 100.0
        scored.append((a, pct))
    scored.sort(key=lambda x: x[1], reverse=buy)
    return scored[:limit]
