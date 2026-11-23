"""Trade stance for a team, and the players that stance says to sell or buy.

Pure. The stance comes from this season's playoff odds when games exist (a team
with no path to the playoffs gains nothing from points scored this year), else
from roster strength. Sell and buy signals use two things the value book
already carries: age against the point where each position's production
typically falls off, and the gap between a player's dynasty and redraft value
(what he is worth to a team that only cares about this season).

Decline ages follow published aging studies: running backs fall off steeply in
their late twenties, receivers and tight ends hold up to around 29-30, and
quarterbacks age slowest. Values lead the decline, so a player is flagged one
year before it.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Set, Tuple

from ff.analysis.fit import detect_status
from ff.analysis.movers import value_redraft_gap
from ff.contracts import Asset
from ff.values import ValueBook

DECLINE_AGE = {"RB": 27, "WR": 29, "TE": 30, "QB": 33}
_GAP = 15.0  # % dynasty-vs-redraft gap that counts as a real premium
_FUTURE_SHARE = 0.25  # share of dynasty value not backed by this season's production
_YOUNG = {"QB": 26}  # default 24


def trade_stance(power_rank: Optional[int], num_teams: int,
                 playoff_odds: Optional[float]) -> str:
    """'seller', 'buyer' or 'hold'."""
    if playoff_odds is not None:
        return "seller" if playoff_odds < 0.10 else "buyer" if playoff_odds >= 0.50 else "hold"
    return {"rebuild": "seller", "contend": "buyer"}.get(detect_status(power_rank, num_teams), "hold")


def sell_candidates(assets: Iterable[Asset], stance: str, *,
                    min_value: int = 1000) -> List[Tuple[Asset, str]]:
    """(asset, why) on your roster worth shopping, most valuable first. A buyer
    sells nothing: the veterans this would flag are the ones winning for him."""
    if stance == "buyer":
        return []
    out: List[Tuple[Asset, str]] = []
    for a in assets:
        if a.is_pick or a.value < min_value:
            continue
        why = []
        decline = DECLINE_AGE.get(a.position or "")
        if decline and a.age is not None and a.age >= decline - 1:
            why.append(f"age {a.age:.0f}, {a.position}s decline from about {decline}")
        gap = value_redraft_gap(a, min_value)
        if stance == "seller" and gap is not None and gap <= -_GAP:
            premium = ((a.redraft_value or 0) - a.value) / a.value * 100
            why.append(f"worth {premium:.0f}% more to a team winning now")
        if why:
            out.append((a, "; ".join(why)))
    out.sort(key=lambda x: x[0].value, reverse=True)
    return out


def buy_candidates(book: ValueBook, exclude: Set[str], stance: str, *,
                   min_value: int = 1500, limit: int = 8) -> List[Tuple[Asset, str]]:
    """(asset, why) to target, skipping ids in `exclude`. A seller wants young
    players whose price is mostly future value (a contender gives up few points
    by moving them); a buyer wants production priced below its points."""
    out: List[Tuple[Asset, float, str]] = []
    for a in book.assets:
        if a.is_pick or a.id in exclude or a.value < min_value or a.redraft_value is None:
            continue
        gap = value_redraft_gap(a, min_value)
        future = (a.value - a.redraft_value) / a.value
        if stance == "seller" and future >= _FUTURE_SHARE and a.age is not None \
                and a.age <= _YOUNG.get(a.position or "", 24):
            out.append((a, float(a.value), f"age {a.age:.0f}, {future:.0%} of his price is future value"))
        elif stance == "buyer" and gap is not None and gap <= -_GAP:
            out.append((a, float(a.redraft_value or 0),
                        f"scores like a {a.redraft_value:,} player, costs {a.value:,}"))
    out.sort(key=lambda x: x[1], reverse=True)
    return [(a, why) for a, _, why in out[:limit]]
