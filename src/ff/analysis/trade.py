"""The trade analyzer - value both baskets (players + picks) and judge fairness.

Name the assets on each side and get totals, the gap as a %, who wins, and a
positional breakdown.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ff.contracts import Asset, TradeEvaluation, TradeSide
from ff.values import ValueBook


def _resolve_side(
    tokens: List[str],
    book: ValueBook,
    include_ktc: bool = True,
) -> Tuple[List[Asset], List[str]]:
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
            if not include_ktc and asset.ktc_value is not None:
                asset = asset.model_copy(update={"ktc_value": None})
            assets.append(asset)
    return assets, unresolved


def evaluate_trade(
    give_inputs: Optional[List[str]] = None,
    get_inputs: Optional[List[str]] = None,
    book: Optional[ValueBook] = None,
    *,
    give: Optional[List[str]] = None,
    get: Optional[List[str]] = None,
    include_ktc: bool = True,
) -> TradeEvaluation:
    """Evaluate trade given assets to give and assets to receive."""
    give_list = give if give is not None else (give_inputs or [])
    get_list = get if get is not None else (get_inputs or [])
    if book is None:
        raise ValueError("ValueBook is required for trade evaluation.")
    evaluation, _ = analyze_trade(
        side_a_tokens=get_list,
        side_b_tokens=give_list,
        book=book,
        labels=("You get", "You give"),
        include_ktc=include_ktc,
    )
    return evaluation


def analyze_trade(
    side_a_tokens: List[str],
    side_b_tokens: List[str],
    book: ValueBook,
    labels: Tuple[str, str] = ("Side A", "Side B"),
    include_ktc: bool = True,
) -> Tuple[TradeEvaluation, List[str]]:
    """Returns (evaluation, unresolved_tokens).

    The evaluation is symmetric in the two sides; `delta` is `value_a - value_b`,
    so whichever list you pass as side_a is the side that "wins" when delta > 0.
    The CLI passes what you receive as side_a and what you give as side_b, so a
    positive delta means the trade favors you. Unresolved tokens are surfaced,
    never silently dropped - a missing player would otherwise make a trade look
    lopsided.
    """
    a_assets, a_missing = _resolve_side(side_a_tokens, book, include_ktc=include_ktc)
    b_assets, b_missing = _resolve_side(side_b_tokens, book, include_ktc=include_ktc)
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


def ktc_position_deltas(evaluation: TradeEvaluation) -> Dict[str, int]:
    """Net KTC value gained per position from side A's perspective (A minus B)."""
    deltas: Dict[str, int] = {}
    for a in evaluation.side_a.assets:
        if a.ktc_value is not None:
            pos = a.position or "NA"
            deltas[pos] = deltas.get(pos, 0) + a.ktc_value
    for b in evaluation.side_b.assets:
        if b.ktc_value is not None:
            pos = b.position or "NA"
            deltas[pos] = deltas.get(pos, 0) - b.ktc_value
    return deltas

