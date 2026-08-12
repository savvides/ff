"""Roster-cleanup audit: capacity vs fill, plus drop and taxi-move suggestions.

Pure and deterministic (same input -> same output), so it is gate-tested, not
evaluated. The one judgment this encodes is the distinction that actually matters
when you need waiver room: only starter/bench players occupy an *active* slot, so
dropping a taxi/IR player frees a taxi/IR slot but adds NO room for a waiver add.
The two levers are therefore surfaced separately:
  * drop candidates  - non-starters ranked worst-first (each flagged whether the
                       drop frees an active slot)
  * taxi candidates  - taxi-eligible bench players that could be stashed to free
                       an active slot without dropping anyone
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ff.contracts import Roster, RosterAudit, RosterSlot
from ff.sleeper import player_name
from ff.values import ValueBook

# Slots in roster_positions that are not active starting slots.
_NON_STARTER = {"BN", "TAXI", "IR"}


def taxi_eligible(
    years_exp: Optional[int],
    *,
    allow_vets: bool,
    taxi_years: Optional[int],
) -> bool:
    """Whether a player may be stashed on the taxi squad.

    Sleeper's taxi rules: if the league allows veterans (`taxi_allow_vets`), any
    player qualifies. Otherwise a player qualifies only inside the rookie window,
    i.e. experience <= `taxi_years` (and `taxi_years` unset means rookies only).
    Unknown experience is treated as ineligible (conservative: never suggest a
    move the league might reject).
    """
    if allow_vets:
        return True
    if years_exp is None:
        return False
    if taxi_years is not None:
        return years_exp <= taxi_years
    return years_exp == 0



def audit_roster(
    roster: Roster,
    book: ValueBook,
    players_meta: Optional[Dict[str, Any]] = None,
    *,
    roster_positions: Optional[List[str]] = None,
    taxi_slots: int = 0,
    reserve_slots: int = 0,
    taxi_allow_vets: bool = False,
    taxi_years: Optional[int] = None,
    drop_limit: int = 8,
) -> RosterAudit:
    """Categorize every player, compute capacity, and rank drop / taxi moves."""
    roster_positions = roster_positions or []
    starter_cap = sum(1 for p in roster_positions if p not in _NON_STARTER)
    bench_cap = roster_positions.count("BN")

    starter_set = set(roster.starters)
    taxi_set = set(roster.taxi)
    reserve_set = set(roster.reserve)

    slots: List[RosterSlot] = []
    for pid in roster.player_ids:
        m = (players_meta or {}).get(pid, {})
        valued = book.value_for_sleeper_id(pid)
        # Category precedence: a player can appear in both `starters` and `taxi`
        # only through bad data; taxi/IR win because they define slot occupancy.
        if pid in taxi_set:
            cat = "TAXI"
        elif pid in reserve_set:
            cat = "IR"
        elif pid in starter_set:
            cat = "START"
        else:
            cat = "BENCH"
        years_exp = m.get("years_exp")
        slots.append(RosterSlot(
            player_id=pid,
            name=valued.name if valued else player_name(pid, players_meta),
            position=(valued.position if valued else m.get("position")),
            age=(valued.age if valued and valued.age is not None else m.get("age")),
            years_exp=years_exp,
            value=valued.value if valued else 0,
            trend_30day=valued.trend_30day if valued else None,
            slot=cat,
            taxi_eligible=taxi_eligible(
                years_exp, allow_vets=taxi_allow_vets, taxi_years=taxi_years),
        ))

    audit = RosterAudit(
        team_name=roster.team_name,
        starter_cap=starter_cap,
        bench_cap=bench_cap,
        taxi_cap=taxi_slots,
        ir_cap=reserve_slots,
        slots=slots,
    )

    # Drop candidates: never a current starter (you do not cut a starter to add a
    # free agent). Worst-first = lowest value, then oldest, then most experienced
    # (least rebuild upside). Tie-break by name keeps the order stable.
    non_starters = [s for s in slots if s.slot != "START"]
    non_starters.sort(key=lambda s: (
        s.value,
        -(s.age or 0),
        -(s.years_exp if s.years_exp is not None else -1),
        s.name,
    ))
    audit.drop_candidates = non_starters[:drop_limit]

    # Taxi candidates: eligible bench players, best-first, capped at open taxi
    # slots. Stashing them frees an active slot while keeping the player.
    taxi_open = max(0, taxi_slots - len(audit.taxi))
    eligible_bench = [s for s in slots if s.slot == "BENCH" and s.taxi_eligible]
    eligible_bench.sort(key=lambda s: (-s.value, s.name))
    audit.taxi_candidates = eligible_bench[:taxi_open]

    return audit
