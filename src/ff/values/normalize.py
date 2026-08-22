"""Canonical player-name and draft-pick keys.

Kept in its own module so `values.client` and `values.ktc` can share the
helpers without a circular import.
"""

from __future__ import annotations

import re
from typing import Optional

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
_ORDINALS = {
    "1": "1", "1st": "1", "first": "1",
    "2": "2", "2nd": "2", "second": "2",
    "3": "3", "3rd": "3", "third": "3",
    "4": "4", "4th": "4", "fourth": "4",
}


def normalize_name(name: str) -> str:
    """Lowercase, strip punctuation + generational suffixes, collapse spaces."""
    s = name.lower()
    s = re.sub(r"[.'`]", "", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    parts = [p for p in s.split() if p not in _SUFFIXES]
    return " ".join(parts).strip()


def normalize_pick(label: str) -> Optional[str]:
    """Canonicalize a draft-pick label to a stable key.

    Slot picks   -> "<year> pick R.SS"        (e.g. "2026 pick 1.05")
    Round picks  -> "<year> <round>"           (e.g. "2027 1")
    Tiered picks -> "<year> <round> <tier>"    (e.g. "2027 1 early")
    Returns None if `label` is not pick-shaped.

    The tier suffix is what keeps FantasyCalc's "2027 1st (Early)/(Mid)/(Late)"
    entries distinct: without it all three collapse onto "2027 1" and whichever
    loads last silently overwrites the others in `ValueBook.picks`.
    """
    s = label.lower().strip()
    year = re.search(r"\b(20\d{2})\b", s)
    if not year:
        return None
    yr = year.group(1)

    slot = re.search(r"\b([1-9])\.(\d{1,2})\b", s)  # 1.05, 2.11
    if slot:
        return f"{yr} pick {int(slot.group(1))}.{int(slot.group(2)):02d}"

    tier_m = re.search(r"\b(early|mid|late)\b", s)
    tier = f" {tier_m.group(1)}" if tier_m else ""

    # round-level: an ordinal word/number, or "round N" / "rN"
    rnd = re.search(r"\bround\s*([1-9])\b", s) or re.search(r"\br([1-9])\b", s)
    if rnd:
        return f"{yr} {rnd.group(1)}{tier}"
    for tok in s.split():
        if tok in _ORDINALS:
            return f"{yr} {_ORDINALS[tok]}{tier}"
    return None
