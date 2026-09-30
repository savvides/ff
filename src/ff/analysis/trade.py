"""The trade analyzer - value both baskets (players + picks) and judge fairness.

Name the assets on each side and get totals, the gap as a %, who wins, and a
positional breakdown. Totals are the ones fantasycalc.com and keeptradecut.com
would show: raw sums plus each site's package adjustment (analysis/calculators.py),
so `ff trade` and the offer rule never disagree with the sites on an uneven deal.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ff.analysis.calculators import fc_adjustment, ktc_adjustment
from ff.contracts import Asset, OfferVerdict, TradeEvaluation, TradeSide
from ff.values import ValueBook

OFFER_THRESHOLD_PCT = 10.0


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
    if isinstance(give_list, str):
        give_list = [t.strip() for t in give_list.split(",") if t.strip()]
    if isinstance(get_list, str):
        get_list = [t.strip() for t in get_list.split(",") if t.strip()]
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
        is_dynasty=book.format.is_dynasty if book.format is not None else True,
        secondary_top=book.secondary_top,
        unresolved=a_missing + b_missing,
    )
    apply_site_adjustments(evaluation)
    return evaluation, a_missing + b_missing


def apply_site_adjustments(evaluation: TradeEvaluation) -> TradeEvaluation:
    """Set both sites' package adjustments on the sides (side_a = the site's Team 1).

    FantasyCalc: its dynasty waiver adjustment (redraft is not modeled, so it stays
    None there). KTC: its value adjustment, only when every asset has a KTC value
    and KTC's top value is known; a failed solve leaves it None."""
    a, b = evaluation.side_a, evaluation.side_b
    if evaluation.is_dynasty:
        a.adjustment, b.adjustment = fc_adjustment([x.value for x in a.assets],
                                                   [x.value for x in b.assets])
    if a.secondary_complete and b.secondary_complete and evaluation.secondary_top:
        res = ktc_adjustment([x.secondary_value or 0 for x in a.assets],
                             [x.secondary_value or 0 for x in b.assets], evaluation.secondary_top)
        if res is not None and math.isfinite(res.adj1) and math.isfinite(res.adj2):
            a.secondary_adjustment, b.secondary_adjustment = int(res.adj1), int(res.adj2)
            evaluation.secondary_hidden = bool((res.adj1 or res.adj2) and not res.shown)
    evaluation.adjusted = True
    return evaluation


def offer_verdict(evaluation: TradeEvaluation, threshold_pct: float = OFFER_THRESHOLD_PCT,
                  calculator_problems: Sequence[str] = ()) -> OfferVerdict:
    """The offer rule, judged only on numbers the sites themselves would show.

    PASS: on the site-adjusted totals the gap is under `threshold_pct` of the larger
    side in FantasyCalc AND in KTC, and KTC's own verdict reads "Fair Trade".
    CANNOT_JUDGE when any input the sites would need is missing, or when a site's
    calculator code has changed since ff's port was verified (`calculator_problems`,
    from ff.values.calculators_live)."""
    assets = evaluation.side_a.assets + evaluation.side_b.assets
    reasons: List[str] = []
    if evaluation.unresolved:
        reasons.append("unresolved: " + ", ".join(evaluation.unresolved))
    if not evaluation.side_a.assets or not evaluation.side_b.assets:
        reasons.append("one side is empty")
    if not evaluation.adjusted:
        reasons.append("site adjustments were not computed")
    elif not evaluation.is_dynasty:
        reasons.append("redraft calculators are not modeled")
    unpriced = [x.name for x in assets if x.secondary_value is None]
    if unpriced:
        reasons.append("KTC has no value for " + ", ".join(unpriced))
    elif evaluation.adjusted and assets and (evaluation.side_a.secondary_adjustment is None
                                             or evaluation.side_b.secondary_adjustment is None):
        reasons.append("KTC's adjustment could not be computed")
    reasons.extend(calculator_problems)
    approximations = [f"{x.name} (priced on KTC by a stand-in)" for x in assets
                      if x.secondary_source == "approx"]
    verdict = OfferVerdict(status="CANNOT_JUDGE", threshold_pct=threshold_pct,
                           reasons=reasons, approximations=approximations)
    if reasons:
        return verdict
    verdict.fc_pct = evaluation.pct_diff
    verdict.ktc_pct = evaluation.secondary_pct_diff
    verdict.ktc_site_pct = evaluation.secondary_site_pct
    verdict.ktc_site_fair = evaluation.secondary_is_fair()
    ok = (verdict.fc_pct < threshold_pct and verdict.ktc_pct is not None
          and verdict.ktc_pct < threshold_pct and verdict.ktc_site_fair)
    verdict.status = "PASS" if ok else "FAIL"
    return verdict


def position_deltas(evaluation: TradeEvaluation) -> Dict[str, int]:
    """Net RAW value gained per position from side A's perspective (A minus B);
    package adjustments belong to no position."""
    deltas: Dict[str, int] = {}
    for a in evaluation.side_a.assets:
        pos = a.position or "NA"
        deltas[pos] = deltas.get(pos, 0) + a.value
    for b in evaluation.side_b.assets:
        pos = b.position or "NA"
        deltas[pos] = deltas.get(pos, 0) - b.value
    return deltas


def secondary_position_deltas(evaluation: TradeEvaluation) -> Dict[str, int]:
    """Net RAW secondary market value gained per position from side A's perspective (A minus B)."""
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


