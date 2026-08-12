"""The trade analyzer - value both baskets (players + picks) and judge fairness.

Name the assets on each side and get totals, the gap as a %, who wins, and a
positional breakdown.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from ff.contracts import Asset, TradeEvaluation, TradeSide
from ff.values import ValueBook


def _resolve_side(tokens: List[str], book: ValueBook) -> Tuple[List[Asset], List[str]]:
    assets: List[Asset] = []
    unresolved: List[str] = []
    for tok in tokens:
        tok = tok.strip()
        if not tok:
            continue
        asset = book.resolve(tok)
        if asset is None:
            unresolved.append(tok)
        else:
            assets.append(asset)
    return assets, unresolved


def analyze_trade(
    side_a_tokens: List[str],
    side_b_tokens: List[str],
    book: ValueBook,
    labels: Tuple[str, str] = ("Side A", "Side B"),
) -> Tuple[TradeEvaluation, List[str]]:
    """Returns (evaluation, unresolved_tokens).

    The evaluation is symmetric in the two sides; `delta` is `value_a - value_b`,
    so whichever list you pass as side_a is the side that "wins" when delta > 0.
    The CLI passes what you receive as side_a and what you give as side_b, so a
    positive delta means the trade favors you. Unresolved tokens are surfaced,
    never silently dropped - a missing player would otherwise make a trade look
    lopsided.
    """
    a_assets, a_missing = _resolve_side(side_a_tokens, book)
    b_assets, b_missing = _resolve_side(side_b_tokens, book)
    evaluation = TradeEvaluation(
        side_a=TradeSide(assets=a_assets),
        side_b=TradeSide(assets=b_assets),
        label_a=labels[0],
        label_b=labels[1],
    )
    return evaluation, a_missing + b_missing


def position_deltas(evaluation: TradeEvaluation) -> Dict[str, int]:
    """Net value gained per position from side A's perspective (A minus B)."""
    deltas: Dict[str, int] = {}
    for a in evaluation.side_a.assets:
        pos = a.position or "NA"
        deltas[pos] = deltas.get(pos, 0) + a.value
    for b in evaluation.side_b.assets:
        pos = b.position or "NA"
        deltas[pos] = deltas.get(pos, 0) - b.value
    return deltas
