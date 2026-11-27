"""Snapshot model for secondary-market dynasty values."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


@dataclass
class SecondarySnapshot:
    """Normalized snapshot of secondary-market dynasty values."""

    source: str
    label: str
    values: Dict[str, int]
    top: Optional[int] = None
    fetched_at: Optional[float] = None
    approx_keys: Set[str] = field(default_factory=set)
    html: str = ""
    notes: List[str] = field(default_factory=list)
