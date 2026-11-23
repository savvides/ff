"""Competitive window, duration, and seasonal liquidity filters (pure analysis)."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Literal, Optional, Tuple

from ff.contracts import SeasonPhase

PhaseKey = Literal[
    "in_season_early",
    "in_season_peak",
    "playoffs",
    "offseason_draft",
    "offseason_quiet",
]

_PHASE_META: Dict[PhaseKey, Tuple[str, str, str]] = {
    "in_season_early": (
        "Early Season (Wk 1-4)",
        "caution",
        "Early sample noise: avoid overpaying for short-term spikes before true tiers settle.",
    ),
    "in_season_peak": (
        "Peak In-Season (Oct-Nov)",
        "points_premium",
        "Contenders pay a premium for weekly points; future picks and injured stars trade at a discount.",
    ),
    "playoffs": (
        "Playoff Push / Playoffs",
        "win_now_lock",
        "Trade deadlines and playoff locks favor proven immediate production over speculative upside.",
    ),
    "offseason_draft": (
        "Offseason Rookie Hype (Mar-May)",
        "picks_premium",
        "Rookie picks carry peak seasonal liquidity while proven veterans trade at a discount.",
    ),
    "offseason_quiet": (
        "Offseason Liquidity Window",
        "vet_discount",
        "Quiet market favors acquiring undervalued veterans and offloading aging RB risk before camp.",
    ),
}


def _phase_from_month(month: int) -> PhaseKey:
    if month in (3, 4, 5):
        return "offseason_draft"
    if month == 9:
        return "in_season_early"
    if month in (10, 11):
        return "in_season_peak"
    if month == 12:
        return "playoffs"
    return "offseason_quiet"


def detect_season_phase(
    state: Optional[Dict[str, Any]] = None,
    today: Optional[date] = None,
) -> SeasonPhase:
    """Resolve the NFL seasonal liquidity regime from Sleeper state and date."""
    ref_date = today or date.today()
    month = ref_date.month

    wk: Optional[int] = None
    season_type: Optional[str] = None
    if state:
        raw_wk = max(int(state.get("week") or 0), int(state.get("display_week") or 0))
        wk = raw_wk if raw_wk > 0 else None
        season_type = str(state.get("season_type") or "").strip().lower() or None

    if season_type is None and wk is not None and wk >= 1:
        season_type = "regular"

    phase: PhaseKey
    if season_type == "regular" and wk is not None:
        if wk <= 4:
            phase = "in_season_early"
        elif wk <= 13:
            phase = "in_season_peak"
        else:
            phase = "playoffs"
    elif season_type == "post":
        phase = "playoffs"
    elif season_type == "off":
        phase = "offseason_draft" if month in (3, 4, 5) else "offseason_quiet"
    elif season_type == "pre":
        phase = "offseason_quiet"
    else:
        phase = _phase_from_month(month)

    label, liquidity_bias, summary = _PHASE_META[phase]
    return SeasonPhase(
        phase=phase,
        label=label,
        liquidity_bias=liquidity_bias,
        week=wk,
        season_type=season_type,
        summary=summary,
    )
