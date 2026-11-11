"""Rest-of-season simulation: expected wins, playoff odds, projected draft slot.

Pure and seeded (same input -> same output). Each team's weekly score is drawn
from a normal around its points-per-game, shrunk toward the league mean so a
few hot weeks do not look like a true talent level. Standings sort by wins,
then points for (Sleeper's default tiebreak).

Draft slot follows the common dynasty rule: non-playoff teams pick in reverse
order of standings, playoff teams after them. Playoff results are not simulated,
so playoff teams are ordered by reverse seed.
shortcut: leagues that set draft order by max PF or lottery differ, add a setting if one is needed.
"""

from __future__ import annotations

import random
import statistics
from typing import Dict, List, Sequence, Tuple

from ff.contracts import Roster, StandingProjection

_SHRINK_GAMES = 3.0  # prior weight: a team's PPG counts fully only after many games
_DEFAULT_SD = 25.0  # typical weekly team-score spread when the sample is too small


def scoring_model(scores: Dict[int, List[float]]) -> Tuple[Dict[int, float], float]:
    """({roster_id: expected weekly score}, weekly sd) from scores to date."""
    played = [x for xs in scores.values() for x in xs]
    if not played:
        return {}, _DEFAULT_SD
    league = statistics.fmean(played)
    means: Dict[int, float] = {}
    resid: List[float] = []
    for rid, xs in scores.items():
        if not xs:
            means[rid] = league
            continue
        m = statistics.fmean(xs)
        means[rid] = league + (m - league) * len(xs) / (len(xs) + _SHRINK_GAMES)
        resid += [x - m for x in xs]
    dof = len(resid) - sum(1 for xs in scores.values() if xs)
    sd = (sum(r * r for r in resid) / dof) ** 0.5 if dof > 0 else _DEFAULT_SD
    return means, sd or _DEFAULT_SD


def _seed_order(rosters: Sequence[Roster], key: Dict[int, Tuple[float, float]],
                playoff_teams: int) -> List[int]:
    """Roster ids best-first; division winners take the top seeds."""
    order = sorted((r.roster_id for r in rosters), key=lambda rid: key[rid], reverse=True)
    division = {r.roster_id: r.division for r in rosters}
    winners: List[int] = []
    seen = set()
    for rid in order:
        d = division[rid]
        if d is not None and d not in seen:
            seen.add(d)
            winners.append(rid)
    winners = winners[:playoff_teams]
    return winners + [rid for rid in order if rid not in winners]


def simulate_season(rosters: Sequence[Roster], scores: Dict[int, List[float]],
                    remaining: Sequence[Sequence[Tuple[int, int]]], *, playoff_teams: int,
                    median_game: bool = False, sims: int = 4000,
                    seed: int = 0) -> List[StandingProjection]:
    """Project the regular season. `scores` are each team's weekly totals so
    far, `remaining` the unplayed weeks as (roster_id, roster_id) pairings.
    `median_game` adds Sleeper's extra weekly game against the league median.
    Returns best expected finish first; empty when no game has been played."""
    means, sd = scoring_model(scores)
    if not means:
        return []
    rng = random.Random(seed)
    n = len(rosters)
    base_w = {r.roster_id: r.wins + r.ties / 2.0 for r in rosters}
    base_pf = {r.roster_id: r.points_for for r in rosters}
    tot_w = dict.fromkeys(base_w, 0.0)
    tot_slot = dict.fromkeys(base_w, 0.0)
    made = dict.fromkeys(base_w, 0)
    for _ in range(sims):
        w = dict(base_w)
        pf = dict(base_pf)
        for week in remaining:
            pts = {rid: rng.gauss(means[rid], sd) for pair in week for rid in pair}
            for a, b in week:
                if pts[a] != pts[b]:
                    w[a if pts[a] > pts[b] else b] += 1
            if median_game and pts:
                cut = statistics.median(pts.values())
                for rid, x in pts.items():
                    w[rid] += x > cut
            for rid, x in pts.items():
                pf[rid] += x
        order = _seed_order(rosters, {rid: (w[rid], pf[rid]) for rid in w}, playoff_teams)
        in_playoffs = order[:playoff_teams]
        for rid in in_playoffs:
            made[rid] += 1
        # Slot 1 goes to the worst non-playoff team; playoff teams pick last.
        for slot, rid in enumerate(reversed(order[playoff_teams:]), 1):
            tot_slot[rid] += slot
        for i, rid in enumerate(reversed(in_playoffs)):
            tot_slot[rid] += n - playoff_teams + 1 + i
        for rid in w:
            tot_w[rid] += w[rid]
    names = {r.roster_id: r.team_name for r in rosters}
    out = [StandingProjection(roster_id=rid, team_name=names[rid],
                              exp_wins=round(tot_w[rid] / sims, 2),
                              playoff_odds=made[rid] / sims,
                              draft_slot=round(tot_slot[rid] / sims, 2))
           for rid in base_w]
    out.sort(key=lambda p: (p.playoff_odds, p.exp_wins), reverse=True)
    return out
