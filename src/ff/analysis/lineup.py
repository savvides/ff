"""Optimal weekly lineup from projected stats + the league's own scoring.

Two pure pieces:
  * project_points(): score a projected stat line with the league's
    scoring_settings. Position bonuses (TEP via `bonus_rec_te`, `bonus_rec_wr`,
    ...) arrive as their own stat keys, so scoring is fully data-driven.
  * optimal_lineup(): assign rostered players to starting slots to maximize
    projected points.

Why the greedy assignment is correct: the supported slots
(QB/RB/WR/TE/K/DEF/FLEX/SUPER_FLEX) form a laminar family - any two eligibility
sets are disjoint or nested - so filling the most restrictive slot first, each
taking the best eligible player left, is provably optimal (exchange argument).
Non-laminar overlapping flexes (WRRB_FLEX + REC_FLEX together) are deliberately
NOT supported, because greedy can be suboptimal for them; such slots are
reported in `Lineup.unsupported_slots` rather than silently mis-filled.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ff.contracts import Lineup, LineupSlot, Roster
from ff.contracts.models import WeeklyContext, WeeklyPlayer
from ff.sleeper import player_name

# Which positions may fill each starting slot. This set is intentionally laminar
# (every pair of eligibility sets is disjoint or nested) so the greedy assignment
# is optimal. Overlapping flexes like WRRB_FLEX {RB,WR} and REC_FLEX {WR,TE} are
# deliberately omitted: together they are non-laminar and greedy can be wrong, so
# they are surfaced as unsupported instead of silently mis-filled.
SLOT_ELIGIBILITY: Dict[str, set] = {
    "QB": {"QB"},
    "RB": {"RB"},
    "WR": {"WR"},
    "TE": {"TE"},
    "K": {"K"},
    "DEF": {"DEF"},
    "FLEX": {"RB", "WR", "TE"},
    "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
}

# Roster spots that are not starting slots at all.
BENCH_SLOTS = {"BN", "IR", "TAXI"}


def project_points(stats: Dict[str, Any], scoring: Dict[str, Any]) -> float:
    """Fantasy points for one projected stat line under the league's scoring.

    Purely data-driven: multiply every stat key the league scores by its weight.
    This already covers position bonuses, because Sleeper's projection exposes
    them as their own stat keys - `bonus_rec_te` (TE premium), `bonus_rec_wr`,
    `bonus_pass_yd_300`, etc. - each equal to the count it applies to. Do NOT add
    TEP separately: the projection's `bonus_rec_te` stat already carries it, so a
    manual bonus would double-count. Verified against Sleeper's own
    `pts_half_ppr` (WR/TE/K match to the cent).
    """
    pts = 0.0
    for key, value in stats.items():
        weight = scoring.get(key)
        if weight is not None and isinstance(value, (int, float)):
            pts += value * weight
    return round(pts, 2)


def projected_points(roster: Roster, projections: Dict[str, Dict[str, Any]],
                     scoring: Dict[str, Any],
                     players_meta: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """player_id -> {name, position, points} for everyone on the roster."""
    meta = players_meta or {}
    out: Dict[str, Dict[str, Any]] = {}
    for pid in roster.player_ids:
        m = meta.get(pid, {})
        name = player_name(pid, meta)
        pos = m.get("position")
        out[pid] = {
            "name": name,
            "position": pos,
            "points": project_points(projections.get(pid, {}), scoring),
        }
    return out


def starting_slots(roster_positions: List[str]) -> List[str]:
    """The ordered starting slots we optimize (duplicates kept, e.g. two 'RB').

    Bench tokens (BN/IR/TAXI) and unsupported overlapping flexes are dropped, so
    the result is exactly the laminar slots the greedy assignment is optimal for.
    """
    return [s for s in roster_positions if s in SLOT_ELIGIBILITY]



def _assign(positions: Dict[str, Optional[str]], scores: Dict[str, float],
            starting: List[str]) -> Dict[int, Optional[str]]:
    """Greedy laminar assignment: most-restrictive slot first, each taking the
    highest-scoring eligible player left. Returns {slot_index -> player_id|None}.

    Score-agnostic: `scores` may be projected points (lineup) or dynasty value
    (fit). Iterates `scores` in its own insertion order so the strict-`>`
    tie-break is stable - callers pass insertion-aligned `positions`/`scores`.
    """
    order = sorted(range(len(starting)), key=lambda i: len(SLOT_ELIGIBILITY[starting[i]]))
    chosen: Dict[int, Optional[str]] = {}
    used: set = set()
    for i in order:
        eligible = SLOT_ELIGIBILITY[starting[i]]
        best_pid, best_score = None, None
        for pid in scores:
            if pid in used or positions.get(pid) not in eligible:
                continue
            if best_score is None or scores[pid] > best_score:
                best_pid, best_score = pid, scores[pid]
        if best_pid is not None:
            used.add(best_pid)
        chosen[i] = best_pid
    return chosen


def optimal_lineup(roster: Roster, projections: Dict[str, Dict[str, Any]],
                   scoring: Dict[str, Any], roster_positions: List[str],
                   players_meta: Optional[Dict[str, Any]] = None,
                   season: str = "", week: int = 0,
                   weekly: Optional[WeeklyContext] = None,
                   required_start: Optional[str] = None,
                   exclude: Optional[set] = None,
                   contingencies: bool = True) -> Lineup:
    pid: Optional[str]
    info = projected_points(roster, projections, scoring, players_meta)
    starting = starting_slots(roster_positions)
    # Starting-slot-shaped tokens we don't optimize (e.g. WRRB_FLEX, IDP slots).
    unsupported = [s for s in roster_positions
                   if s not in SLOT_ELIGIBILITY and s not in BENCH_SLOTS]

    warnings = list(weekly.warnings) if weekly else []
    if weekly and (weekly.blocked_reason or unsupported):
        raise ValueError(weekly.blocked_reason or "Unsupported lineup slots: " + ", ".join(unsupported))
    inactive = set(roster.taxi) | set(roster.reserve) | (exclude or set())
    frozen: Dict[int, Optional[str]] = {}
    locked: set = set()
    if weekly:
        if weekly.as_of.tzinfo is None:
            raise ValueError("Weekly clock must include a timezone")
        for pid in info:
            fact = weekly.players.get(pid, WeeklyPlayer())
            timing_unknown = fact.game_status == "unknown" or (fact.game_status == "scheduled" and (fact.kickoff is None or fact.kickoff.tzinfo is None))
            is_locked = game_locked(fact, weekly)
            if is_locked:
                locked.add(pid)
            if is_locked or timing_unknown:
                inactive.add(pid)
                for i, current in enumerate(roster.starters):
                    if current == pid and i < len(starting):
                        if pid in (exclude or set()):
                            raise ValueError(f"{info[pid]['name']} is locked or timing is unverified")
                        frozen[i] = pid
                if timing_unknown:
                    warnings.append(f"{info[pid]['name']}: game timing unverified; existing assignment preserved.")
            if fact.game_status == "bye" or unavailable(fact):
                inactive.add(pid)
            if pid not in projections and not is_locked:
                inactive.add(pid)
                warnings.append(f"{info[pid]['name']}: no projection; not recommended for an open slot.")
            if is_locked:
                info[pid]["points"] = fact.actual if fact.actual is not None else 0.0
                if fact.actual is None:
                    warnings.append(f"{info[pid]['name']}: actual points unavailable; displayed as zero, total incomplete.")

    eligible = {pid: d for pid, d in info.items() if pid not in inactive}
    positions = {pid: d["position"] for pid, d in eligible.items()}
    scores = {pid: d["points"] for pid, d in eligible.items()}

    def assign(fixed: Dict[int, Optional[str]]) -> Dict[int, Optional[str]]:
        open_indices = [i for i in range(len(starting)) if i not in fixed]
        available_scores = {p: v for p, v in scores.items() if p not in fixed.values()}
        assignment = _assign(positions, available_scores, [starting[i] for i in open_indices])
        return {**fixed, **{open_indices[i]: p for i, p in assignment.items()}}

    if required_start and required_start not in frozen.values():
        if required_start not in eligible:
            raise ValueError("Requested player cannot start: unavailable, locked, or missing a projection")
        choices = [assign({**frozen, i: required_start}) for i, slot in enumerate(starting)
                   if i not in frozen and positions[required_start] in SLOT_ELIGIBILITY[slot]]
        if not choices:
            raise ValueError("Requested player has no legal starting slot")
        chosen = max(choices, key=lambda c: (sum(p is not None for p in c.values()),
                                             sum(info[p]["points"] for p in c.values() if p)))
    else:
        chosen = assign(frozen)

    # Reassign the same selected players to preserve later kickoff flexibility.
    # Swaps do not alter points or selected IDs and never move a frozen slot.
    if weekly:
        for i in sorted(chosen, key=lambda j: len(SLOT_ELIGIBILITY[starting[j]])):
            if i in frozen or not chosen[i]:
                continue
            for j in chosen:
                if j in frozen or not chosen[j] or i == j:
                    continue
                p, q = chosen[i], chosen[j]
                assert p is not None and q is not None
                fp, fq = weekly.players.get(p), weekly.players.get(q)
                if (SLOT_ELIGIBILITY[starting[i]] < SLOT_ELIGIBILITY[starting[j]]
                        and info[q]["position"] in SLOT_ELIGIBILITY[starting[i]]
                        and info[p]["position"] in SLOT_ELIGIBILITY[starting[j]]
                        and fp and fq and fp.kickoff and fq.kickoff and fp.kickoff > fq.kickoff):
                    chosen[i], chosen[j] = q, p
    used = {pid for pid in chosen.values() if pid is not None}

    slots: List[LineupSlot] = []
    for i, slot in enumerate(starting):
        pid = chosen.get(i)
        d = info.get(pid) if pid else None
        slots.append(LineupSlot(
            slot=slot,
            player_id=pid,
            name=d["name"] if d else "(empty)",
            position=d["position"] if d else None,
            points=d["points"] if d else 0.0,
            **_slot_facts(pid, weekly, locked),
        ))

    bench = [
        LineupSlot(slot="BN", player_id=pid, name=d["name"],
                   position=d["position"], points=d["points"],
                   **_slot_facts(pid, weekly, locked))
        for pid, d in sorted(info.items(), key=lambda kv: kv[1]["points"], reverse=True)
        if pid not in used
    ]
    if weekly and contingencies:
        for index, entry in enumerate(slots):
            if index in frozen or entry.locked or entry.availability.lower() not in {"questionable", "doubtful"}:
                continue
            alternative = optimal_lineup(roster, projections, scoring, roster_positions, players_meta,
                                         season, week, weekly=weekly, exclude=(exclude or set()) | {entry.player_id},
                                         contingencies=False)
            replacements = [s for s in alternative.slots if s.player_id and s.player_id not in used]
            names = ", ".join(s.name for s in replacements) or "no projected rostered replacement"
            deadlines = [s.kickoff for s in replacements + [entry] if s.kickoff]
            deadline = min(deadlines).isoformat() if deadlines else "unverified"
            warnings.append(f"Conditional: {entry.name} is {entry.availability}. If out: {names}; "
                            f"lineup {alternative.total:.2f}; decide before {deadline} (UTC). "
                            "Replacement availability must also be rechecked.")
    return Lineup(slots=slots, bench=bench, season=str(season), week=week,
                  unsupported_slots=unsupported, warnings=warnings,
                  as_of=weekly.as_of if weekly else None)


UNAVAILABLE = {"out", "ir", "injured reserve", "suspended", "sus", "pup", "physically unable to perform", "inactive"}


def unavailable(fact: WeeklyPlayer) -> bool:
    return (fact.injury_status or "").lower() in UNAVAILABLE


def game_locked(fact: WeeklyPlayer, weekly: WeeklyContext) -> bool:
    return fact.game_status in {"live", "final"} or (
        fact.game_status == "scheduled" and fact.kickoff is not None
        and fact.kickoff.tzinfo is not None and fact.kickoff <= weekly.as_of)


def _slot_facts(pid: Optional[str], weekly: Optional[WeeklyContext], locked: set) -> Dict[str, Any]:
    if not weekly or not pid:
        return {}
    fact = weekly.players.get(pid, WeeklyPlayer())
    kind = "projected"
    if pid in locked:
        kind = "actual" if fact.game_status == "final" else "actual so far"
        if fact.actual is None:
            kind = "actual unavailable"
    return {"locked": pid in locked, "availability": fact.injury_status or (
        "no injury designation" if fact.source or fact.game_status != "unknown" else "unverified"),
        "points_kind": kind, "kickoff": fact.kickoff}
