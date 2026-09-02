"""The trade analyzer - value both baskets (players + picks) and judge fairness.

Name the assets on each side and get totals, the gap as a %, who wins, and a
positional breakdown.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ff.contracts import Asset, TradeEvaluation, TradeSide
from ff.values import ValueBook


def _resolve_side(
    tokens: List[str],
    book: ValueBook,
    include_secondary: bool = True,
    include_ktc: bool = True,
    players_meta: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Asset], List[str]]:
    assets: List[Asset] = []
    unresolved: List[str] = []
    should_include = include_secondary and include_ktc
    for tok in tokens:
        tok = tok.strip()
        if not tok:
            continue
        asset = book.resolve(tok)
        if asset is None:
            unresolved.append(tok)
        else:
            asset = asset.model_copy()
            if not should_include and asset.secondary_value is not None:
                asset.secondary_value = None
            if players_meta and not asset.is_pick:
                asset.fill_from_meta(players_meta.get(asset.id))
            assets.append(asset)
    return assets, unresolved


def evaluate_trade(
    give_inputs: Optional[List[str]] = None,
    get_inputs: Optional[List[str]] = None,
    book: Optional[ValueBook] = None,
    *,
    give: Optional[List[str]] = None,
    get: Optional[List[str]] = None,
    include_secondary: bool = True,
    include_ktc: bool = True,
    players_meta: Optional[Dict[str, Any]] = None,
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
        include_secondary=include_secondary,
        include_ktc=include_ktc,
        players_meta=players_meta,
    )
    return evaluation


def analyze_trade(
    side_a_tokens: List[str],
    side_b_tokens: List[str],
    book: ValueBook,
    labels: Tuple[str, str] = ("Side A", "Side B"),
    include_secondary: bool = True,
    include_ktc: bool = True,
    players_meta: Optional[Dict[str, Any]] = None,
) -> Tuple[TradeEvaluation, List[str]]:
    """Returns (evaluation, unresolved_tokens).

    The evaluation is symmetric in the two sides; `delta` is `value_a - value_b`,
    so whichever list you pass as side_a is the side that "wins" when delta > 0.
    The CLI passes what you receive as side_a and what you give as side_b, so a
    positive delta means the trade favors you. Unresolved tokens are surfaced,
    never silently dropped - a missing player would otherwise make a trade look
    lopsided.
    """
    a_assets, a_missing = _resolve_side(
        side_a_tokens, book, include_secondary=include_secondary, include_ktc=include_ktc, players_meta=players_meta
    )
    b_assets, b_missing = _resolve_side(
        side_b_tokens, book, include_secondary=include_secondary, include_ktc=include_ktc, players_meta=players_meta
    )
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


def secondary_position_deltas(evaluation: TradeEvaluation) -> Dict[str, int]:
    """Net secondary market value gained per position from side A's perspective (A minus B)."""
    deltas: Dict[str, int] = {}
    for a in evaluation.side_a.assets:
        if a.secondary_value is not None:
            pos = a.position or "NA"
            deltas[pos] = deltas.get(pos, 0) + a.secondary_value
    for b in evaluation.side_b.assets:
        if b.secondary_value is not None:
            pos = b.position or "NA"
            deltas[pos] = deltas.get(pos, 0) - b.secondary_value
    return deltas


# Backward compatibility aliases
ktc_position_deltas = secondary_position_deltas
dealer_position_deltas = secondary_position_deltas


