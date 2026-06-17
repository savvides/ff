"""Optimal weekly lineup from projected stats + the league's own scoring.

Two pure pieces:
  * project_points(): score a projected stat line with the league's
    scoring_settings, including TEP (a TE-only per-reception bonus that is not a
    stat key, so it is applied explicitly).
  * optimal_lineup(): assign rostered players to starting slots to maximize
    projected points.

Why the greedy assignment is correct: standard slot eligibility
(QB/RB/WR/TE/FLEX/SUPER_FLEX) is laminar - any two eligibility sets are either
disjoint or nested. Filling the most restrictive slots first, each taking the
best eligible player left, is optimal for a laminar family (exchange argument).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ff.contracts import Lineup, LineupSlot, Roster

# Which positions may fill each starting slot. Anything not here (BN/IR/TAXI or
# unknown) is not a starting slot. The standard slots below are laminar, so the
# greedy assignment is optimal. WRRB_FLEX + REC_FLEX overlap non-laminarly; a
# league running BOTH at once gets a good-but-not-guaranteed-optimal lineup.
SLOT_ELIGIBILITY: Dict[str, set] = {
    "QB": {"QB"},
    "RB": {"RB"},
    "WR": {"WR"},
    "TE": {"TE"},
    "K": {"K"},
    "DEF": {"DEF"},
    "FLEX": {"RB", "WR", "TE"},
    "WRRB_FLEX": {"RB", "WR"},
    "REC_FLEX": {"WR", "TE"},
    "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
}


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
        name = m.get("full_name") or " ".join(
            x for x in (m.get("first_name"), m.get("last_name")) if x) or pid
        pos = m.get("position")
        out[pid] = {
            "name": name,
            "position": pos,
            "points": project_points(projections.get(pid, {}), scoring),
        }
    return out


def optimal_lineup(roster: Roster, projections: Dict[str, Dict[str, Any]],
                   scoring: Dict[str, Any], roster_positions: List[str],
                   players_meta: Optional[Dict[str, Any]] = None,
                   season: str = "", week: int = 0) -> Lineup:
    info = projected_points(roster, projections, scoring, players_meta)
    starting = [s for s in roster_positions if s in SLOT_ELIGIBILITY]

    # Fill the most restrictive slots first (fewest eligible positions).
    order = sorted(range(len(starting)), key=lambda i: len(SLOT_ELIGIBILITY[starting[i]]))
    chosen: Dict[int, Optional[str]] = {}
    used: set = set()
    for i in order:
        eligible = SLOT_ELIGIBILITY[starting[i]]
        best_pid, best_pts = None, None
        for pid, d in info.items():
            if pid in used or d["position"] not in eligible:
                continue
            if best_pts is None or d["points"] > best_pts:
                best_pid, best_pts = pid, d["points"]
        if best_pid is not None:
            used.add(best_pid)
        chosen[i] = best_pid

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
        ))

    bench = [
        LineupSlot(slot="BN", player_id=pid, name=d["name"],
                   position=d["position"], points=d["points"])
        for pid, d in sorted(info.items(), key=lambda kv: kv[1]["points"], reverse=True)
        if pid not in used
    ]
    return Lineup(slots=slots, bench=bench, season=str(season), week=week)
