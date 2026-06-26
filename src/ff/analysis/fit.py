"""Team-relative draft fit: market value re-expressed through *your* roster.

FantasyCalc's dynasty value already prices format scarcity (the book is fetched
per league format - superflex, team count, ppr). What it cannot see is your
specific roster and competitive status. This module keeps that market value as
the anchor and layers three bounded, status-weighted tilts on top:

  * starter-upgrade - how much a player raises YOUR optimal starting lineup,
    measured over your own roster's replacement level. This is deliberately
    orthogonal to league-format scarcity, so it never re-applies what is already
    inside the value.
  * horizon - rebuild rewards the future (dynasty > redraft), contend rewards
    win-now (redraft >= dynasty). Degrades to neutral when redraft value is
    missing or floor-noise, which is most rookies.
  * standing - for contenders only, a mild premium to fill a genuine startable
    hole vs the league. Rebuilders see standing but never chase need (a dynasty
    anti-pattern).

Age is never scored here: it is already inside the dynasty value, so the horizon
tilt is the only youth/now lever and youth is never counted twice.
"""
from __future__ import annotations

from statistics import median
from typing import Dict, List, Optional, Tuple

from ff.analysis.lineup import _assign, starting_slots
from ff.analysis.movers import value_redraft_gap
from ff.contracts import (
    Asset,
    DraftFit,
    PositionStanding,
    RosterValuation,
    TeamContext,
)

HORIZON_FLOOR = 1000  # mirrors movers: redraft gaps below this are floor-noise

# mode -> tilt weights. up = starter-upgrade, h = horizon, s = standing.
WEIGHTS: Dict[str, Dict[str, float]] = {
    "contend": {"up": 0.30, "h": 0.15, "s": 0.10},
    "rebuild": {"up": 0.05, "h": 0.15, "s": 0.00},
    "balanced": {"up": 0.17, "h": 0.10, "s": 0.05},
}

# The positions the standing table compares; FLEX/SUPER_FLEX value rolls up into
# the player's base position.
STANDING_POSITIONS = ("QB", "RB", "WR", "TE")


def detect_status(power_rank: Optional[int], num_teams: int) -> str:
    """Top third of the league -> contend, bottom third -> rebuild, else
    balanced. Unknown rank -> balanced."""
    if not power_rank or not num_teams:
        return "balanced"
    third = num_teams / 3.0
    if power_rank <= third:
        return "contend"
    if power_rank > num_teams - third:
        return "rebuild"
    return "balanced"


def startable_value(assets: List[Asset],
                    roster_positions: List[str]) -> Tuple[int, Dict[str, int]]:
    """Optimal starting-lineup value over `assets`, scored by dynasty value.

    Returns (total starter value, {player_position: starter value}). Reuses the
    laminar greedy assignment from `lineup`, so a WR filling a FLEX still counts
    under WR.
    """
    starting = starting_slots(roster_positions)
    by_id = {a.id: a for a in assets}
    positions = {a.id: a.position for a in assets}
    scores = {a.id: float(a.value) for a in assets}
    chosen = _assign(positions, scores, starting)
    total = 0
    by_pos: Dict[str, int] = {}
    for pid in chosen.values():
        if pid is None:
            continue
        a = by_id[pid]
        total += a.value
        pos = a.position or "?"
        by_pos[pos] = by_pos.get(pos, 0) + a.value
    return total, by_pos


def positional_standing(my_val: RosterValuation, all_vals: List[RosterValuation],
                        roster_positions: List[str]) -> List[PositionStanding]:
    """Your startable value per position vs the league median startable value."""
    _, mine_by = startable_value(my_val.assets, roster_positions)
    league_by: Dict[str, List[int]] = {p: [] for p in STANDING_POSITIONS}
    for v in all_vals:
        _, by = startable_value(v.assets, roster_positions)
        for p in STANDING_POSITIONS:
            league_by[p].append(by.get(p, 0))
    out: List[PositionStanding] = []
    for p in STANDING_POSITIONS:
        vals = league_by[p]
        med = int(median(vals)) if vals else 0
        out.append(PositionStanding(position=p, mine=mine_by.get(p, 0), median=med))
    return out


def _why(fit: DraftFit, status: str) -> str:
    anchor = fit.asset.value or 1
    up = anchor * fit.upgrade_tilt
    hz = anchor * abs(fit.horizon_tilt)
    st = anchor * fit.standing_tilt
    # Dynasty-timeline signals (horizon, standing) lead the rationale over the
    # win-now upgrade; "starts now" is only the headline for a contender.
    if hz > 0 and hz >= up and hz >= st:
        return ("young: dynasty > redraft, a building block" if fit.horizon_tilt > 0
                else "win-now value, ready to contribute")
    if st > 0 and st >= up:
        return f"fills your thinnest startable spot ({fit.asset.position})"
    if up > 0:
        if status == "contend":
            return f"starts for you now (+{fit.marginal_starter:,} to your lineup)"
        return f"best value left (+{fit.marginal_starter:,} to your lineup)"
    return "top market value available"


def score_candidate(candidate: Asset, base_starter_value: int,
                    my_assets: List[Asset], roster_positions: List[str],
                    standing_by_pos: Dict[str, PositionStanding],
                    weights: Dict[str, float], status: str,
                    market_rank: int) -> DraftFit:
    """Score one available player for this team. Anchor = dynasty value; the
    tilts are bounded fractions of that anchor."""
    anchor = candidate.value
    fit = DraftFit(asset=candidate, fit_score=float(anchor), market_rank=market_rank)
    if candidate.is_pick or anchor <= 0:
        fit.why = "top market value available"
        return fit

    # 1. starter-upgrade over YOUR own roster (orthogonal to format scarcity).
    new_total, _ = startable_value(my_assets + [candidate], roster_positions)
    delta = max(0, new_total - base_starter_value)
    fit.marginal_starter = delta
    fit.upgrade_tilt = weights["up"] * (delta / anchor)

    # 2. horizon: rebuild rewards future, contend rewards win-now; neutral when
    #    redraft is missing/floor-noise (most rookies).
    gap = value_redraft_gap(candidate, HORIZON_FLOOR)
    if gap is not None:
        g = max(-1.0, min(1.0, gap / 100.0))
        sign = -1.0 if status == "contend" else 1.0
        fit.horizon_tilt = sign * weights["h"] * g

    # 3. standing: contenders fill genuine startable holes; rebuilders w_s = 0.
    st = standing_by_pos.get(candidate.position or "?")
    if st is not None and st.is_hole:
        hole = max(0.0, min(1.0, (st.median - st.mine) / st.median))
        fit.standing_tilt = weights["s"] * hole

    fit.fit_score = anchor * (1.0 + fit.upgrade_tilt + fit.horizon_tilt + fit.standing_tilt)
    fit.why = _why(fit, status)
    return fit


def rank_fits(candidates: List[Asset], my_val: RosterValuation,
              all_vals: List[RosterValuation], roster_positions: List[str],
              status: str, limit: int) -> Tuple[TeamContext, List[DraftFit]]:
    """Score the value-sorted `candidates` for this team and return the top
    `limit` by FitScore, plus the team context for the header. `market_rank` is
    captured from the incoming (value-sorted) order before re-sorting."""
    weights = WEIGHTS.get(status, WEIGHTS["balanced"])
    standings = positional_standing(my_val, all_vals, roster_positions)
    standing_by_pos = {s.position: s for s in standings}
    base, _ = startable_value(my_val.assets, roster_positions)
    fits = [
        score_candidate(c, base, my_val.assets, roster_positions,
                        standing_by_pos, weights, status, rank)
        for rank, c in enumerate(candidates, 1)
    ]
    fits.sort(key=lambda f: f.fit_score, reverse=True)
    ctx = TeamContext(status=status, power_rank=my_val.power_rank,
                      num_teams=len(all_vals), standings=standings)
    return ctx, fits[:limit]
