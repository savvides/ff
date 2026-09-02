from __future__ import annotations

from typing import Dict, List, Optional, Tuple, Union

from ff.contracts import ArbitrageMover, Asset, Roster
from ff.values import ValueBook


def value_redraft_gap(a: Asset, min_value: int = 1000) -> Optional[float]:
    """(dynasty - redraft) / redraft * 100, or None when not comparable.

    None for a pick, a player with no redraft value, or either value below
    `min_value` - so callers (movers, fit) degrade to a neutral signal instead of
    a meaningless +100000% gap on a deep stash with redraft ~1. Positive means
    dynasty > redraft (young/ascending); negative means aging win-now value.
    """
    if a.is_pick or not a.redraft_value:
        return None
    if a.value < min_value or a.redraft_value < min_value:
        return None
    return (a.value - a.redraft_value) / a.redraft_value * 100.0


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
        gap = value_redraft_gap(a, min_value)
        if gap is None:
            continue
        scored.append((a, gap))
    scored.sort(key=lambda x: x[1], reverse=buy)
    return scored[:limit]


def find_arbitrage_movers(
    rosters: Optional[Union[List[Roster], ValueBook]] = None,
    book: Optional[ValueBook] = None,
    min_value: int = 1000,
    limit: int = 20,
    market: Optional[str] = None,
) -> List[ArbitrageMover]:
    """Scan and rank assets with market valuation discrepancies between FC and secondary market (Dynasty Dealer).

    If rosters is supplied, attaches owning team info to each arbitrage opportunity.
    market can be 'dealer' (assets where Dealer > FC) or 'fc' (assets where FC > Dealer).
    Accepts 'ktc' as a legacy alias for 'dealer'.
    """
    actual_book: Optional[ValueBook] = None
    actual_rosters: Optional[List[Roster]] = None

    if isinstance(rosters, ValueBook):
        actual_book = rosters
        actual_rosters = book if isinstance(book, list) else None
    elif isinstance(book, ValueBook):
        actual_book = book
        actual_rosters = rosters if isinstance(rosters, list) else None
    elif rosters is None and book is None:
        return []

    if actual_book is None:
        return []

    # Map player_id to (roster_id, team_name) if rosters provided
    owner_map: Dict[str, Tuple[int, str]] = {}
    if actual_rosters:
        for r in actual_rosters:
            all_ids = set(r.player_ids + r.starters + r.taxi + r.reserve)
            for pid in all_ids:
                owner_map[pid] = (r.roster_id, r.team_name)

    scored: List[ArbitrageMover] = []
    norm_market = market.lower() if market else None

    for a in actual_book.assets:
        if a.secondary_value is None:
            continue
        fc_val = a.value
        sec_val = a.secondary_value

        if min_value > 0 and max(fc_val, sec_val) < min_value:
            continue

        diff = sec_val - fc_val

        if norm_market in ("dealer", "ktc") and diff <= 0:
            continue
        if norm_market == "fc" and diff >= 0:
            continue

        larger = max(fc_val, sec_val)
        pct_diff = (abs(diff) / larger * 100.0) if larger > 0 else 0.0
        diff_pct = ((sec_val - fc_val) / fc_val * 100.0) if fc_val > 0 else 0.0

        r_info = owner_map.get(a.id)
        roster_id, team_name = r_info if r_info else (None, None)

        mover = ArbitrageMover(
            asset=a,
            fc_value=fc_val,
            secondary_value=sec_val,
            diff=diff,
            pct_diff=pct_diff,
            diff_pct=diff_pct,
            roster_id=roster_id,
            team_name=team_name,
            market_bias="Dealer" if diff > 0 else ("FC" if diff < 0 else "EVEN"),
        )
        scored.append(mover)

    scored.sort(key=lambda m: (abs(m.diff), m.pct_diff), reverse=True)
    return scored[:limit] if limit > 0 else scored


