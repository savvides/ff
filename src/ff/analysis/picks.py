"""Future-pick ownership: who holds which picks, and what they are worth.

All pure (no I/O). Sleeper has no per-team pick endpoint; ownership is derived:
every team owns its own pick for each (season, round) unless a `traded_picks`
row reassigns it. A pick traded twice keeps `roster_id` = the original team on
every row, so the last row per (season, round, roster_id) is the current owner.

Valuation is tier-aware: FantasyCalc prices near-season 1sts/2nds as Early/Mid/
Late, and which tier a pick lands in depends on how good the ORIGINAL team is
(a bad team's own 1st is an early one). We proxy that with the original team's
current power rank; rounds without tiered entries fall back to the flat round
value, and unpriced rounds (typically 4ths) are 0, never guessed.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ff.contracts import FuturePick, Roster, TeamPicks
from ff.values import ValueBook


def pick_tier(power_rank: Optional[int], num_teams: int) -> str:
    """Early/mid/late from the ORIGINAL team's power rank: better team, later
    pick. Thirds, like `detect_status`; unknown rank prices neutrally as mid."""
    if not power_rank or num_teams < 3:
        return "mid"
    third = num_teams // 3
    if power_rank <= third:
        return "late"
    if power_rank > num_teams - third:
        return "early"
    return "mid"


def price_pick(book: ValueBook, season: str, round_: int,
               tier: str) -> Tuple[int, Optional[str]]:
    """(value, tier_used) for a (season, round) pick. Tiered entry when
    FantasyCalc has one, else the flat round entry (tier_used=None), else 0."""
    tiered = book.picks.get(f"{season} {round_} {tier}")
    if tiered:
        return tiered.value, tier
    flat = book.picks.get(f"{season} {round_}")
    if flat:
        return flat.value, None
    return 0, None


def pick_ledger(rosters: List[Roster], traded_picks: List[Dict[str, Any]],
                book: ValueBook, power_ranks: Dict[int, Optional[int]], *,
                seasons: List[str], rounds: int) -> List[TeamPicks]:
    """Every team's future picks, reconciled and valued, best capital first.

    `rounds` is the caller's best guess at the rookie-draft round count; a traded
    pick in a deeper round proves the draft has at least that many, so the ledger
    extends itself rather than silently dropping owned capital."""
    season_set = set(seasons)
    rounds = max([rounds] + [t["round"] for t in traded_picks
                             if t["season"] in season_set])

    current: Dict[Tuple[str, int, int], int] = {}
    for t in traded_picks:  # later rows win: a re-traded pick's last row is current
        current[(t["season"], t["round"], t["roster_id"])] = t["owner_id"]

    names = {r.roster_id: r.team_name for r in rosters}
    owned: Dict[int, List[FuturePick]] = {r.roster_id: [] for r in rosters}
    for season in seasons:
        for rnd in range(1, rounds + 1):
            for r in rosters:
                owner = current.get((season, rnd, r.roster_id), r.roster_id)
                value, tier_used = price_pick(
                    book, season, rnd, pick_tier(power_ranks.get(r.roster_id), len(rosters)))
                owned.setdefault(owner, []).append(FuturePick(
                    season=season, round=rnd,
                    original_roster_id=r.roster_id,
                    original_team=names.get(r.roster_id, f"Team {r.roster_id}"),
                    acquired=owner != r.roster_id,
                    tier=tier_used, value=value,
                ))

    out = [TeamPicks(roster_id=rid, team_name=names.get(rid, f"Team {rid}"),
                     picks=sorted(ps, key=lambda p: (p.season, p.round, -p.value)))
           for rid, ps in owned.items()]
    out.sort(key=lambda t: t.total_value, reverse=True)
    return out
