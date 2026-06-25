"""Live-draft math: where you pick, what you still own, and who's left.

All pure (no I/O). The two hard parts are:
  * pick ordering, which differs by draft type (linear / snake / 3rd-round
    reversal), and
  * pick *ownership*, which `slot_to_roster_id` gives only as a starting point -
    traded picks reassign it, so a slot's pick may belong to a different roster.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from ff.contracts import Asset, DraftPickInfo
from ff.values import ValueBook


def pick_number(round_: int, slot: int, teams: int, *,
                snake: bool = False, reversal_round: int = 0) -> int:
    """Overall (1-indexed) pick number for a (round, slot).

    Linear: every round runs slot 1..teams, so slot S in round R is just
    (R-1)*teams + S. Snake: even rounds run in reverse. Third-round reversal
    (reversal_round=R, common in dynasty rookie drafts): the direction flips
    once more from round R on, so the team that drafted last in round R-1 also
    drafts first in round R.
    """
    forward = True
    if snake:
        forward = (round_ % 2 == 1)
        if reversal_round and round_ >= reversal_round:
            forward = not forward
    pos_in_round = slot if forward else (teams - slot + 1)
    return (round_ - 1) * teams + pos_in_round


def _owner(round_: int, slot: int, slot_to_roster: Dict[int, int],
           override: Dict[Tuple[int, int], int]) -> Optional[int]:
    """Current owner of a (round, slot)'s pick: the slot's roster unless a
    traded pick moved it."""
    orig = slot_to_roster.get(slot)
    if orig is None:
        return None
    return override.get((round_, orig), orig)


def my_picks(roster_id: int, slot_to_roster: Dict[int, int],
             traded_picks: List[Dict[str, Any]], picks_made: List[Dict[str, Any]],
             *, teams: int, rounds: int,
             snake: bool = False, reversal_round: int = 0) -> List[DraftPickInfo]:
    """Every pick `roster_id` currently owns - made and upcoming - by pick number.

    `used` is decided by count (a pick is used once `pick_no <= picks made`), so
    it stays correct no matter how the draft is ordered; the player who was taken
    is read from the matching `picks_made` row when present.
    """
    override = {(t["round"], t["roster_id"]): t["owner_id"] for t in traded_picks}
    by_no = {p["pick_no"]: p for p in picks_made}
    made_count = len(picks_made)

    out: List[DraftPickInfo] = []
    for rnd in range(1, rounds + 1):
        for slot in range(1, teams + 1):
            if _owner(rnd, slot, slot_to_roster, override) != roster_id:
                continue
            pn = pick_number(rnd, slot, teams, snake=snake, reversal_round=reversal_round)
            used = pn <= made_count
            made = by_no.get(pn)
            meta = (made or {}).get("metadata") or {}
            name = f"{meta.get('first_name', '')} {meta.get('last_name', '')}".strip()
            out.append(DraftPickInfo(
                pick_no=pn, round=rnd, slot=slot, used=used,
                player_id=(made or {}).get("player_id") if used else None,
                player_name=name or None if used else None,
                position=meta.get("position") if used else None,
            ))
    out.sort(key=lambda p: p.pick_no)
    return out


def available(book: ValueBook, taken_ids: Set[str], *,
              position: Optional[str] = None,
              limit: Optional[int] = None) -> List[Asset]:
    """ValueBook players not in `taken_ids`, ranked by dynasty value.

    `taken_ids` is the union of everyone already rostered league-wide and everyone
    drafted in this draft - so what's left is exactly what you can still pick. The
    ranking itself is `ValueBook.top`, so `values` and `draft` agree on order.
    """
    return book.top(position=position, limit=limit, exclude=taken_ids)
