"""Secondary market dynasty values from DynastyProcess.

Fetches open-source dynasty player and draft-pick values plus the DynastyProcess
ID crosswalk CSV, joins FantasyPros IDs to Sleeper IDs, and returns a normalized
`SecondarySnapshot`.
"""

from __future__ import annotations

import csv
import io
import logging
from typing import Dict, List, Optional

from ff.contracts import Format
from ff.core.http import _cache_file, get_text
from ff.values.normalize import normalize_name, normalize_pick
from ff.values.snapshot import SecondarySnapshot

logger = logging.getLogger(__name__)

DP_VALUES_URL = "https://raw.githubusercontent.com/dynastyprocess/data/master/files/values.csv"
DP_PLAYERIDS_URL = "https://raw.githubusercontent.com/dynastyprocess/data/master/files/db_playerids.csv"
DP_VALUES_TTL = 6 * 3600
DP_IDS_TTL = 24 * 3600


def _empty_snapshot() -> SecondarySnapshot:
    return SecondarySnapshot(source="dp", label="DynastyProcess", values={})


def _parse_id_map(ids_csv: str) -> Dict[str, str]:
    """Map non-empty `fantasypros_id` -> `sleeper_id` from db_playerids.csv."""
    mapping: Dict[str, str] = {}
    for row in csv.DictReader(io.StringIO(ids_csv)):
        fp_id = (row.get("fantasypros_id") or "").strip()
        sleeper_id = (row.get("sleeper_id") or "").strip()
        if fp_id and sleeper_id:
            mapping[fp_id] = sleeper_id
    return mapping


class DynastyProcessClient:
    """Client for fetching secondary market dynasty values from DynastyProcess."""

    def __init__(
        self,
        values_url: str = DP_VALUES_URL,
        ids_url: str = DP_PLAYERIDS_URL,
        ttl: float = DP_VALUES_TTL,
        ids_ttl: float = DP_IDS_TTL,
    ) -> None:
        self.values_url = values_url
        self.ids_url = ids_url
        self.ttl = ttl
        self.ids_ttl = ids_ttl

    def fetch_snapshot(
        self,
        fmt: Optional[Format] = None,
        use_cache: bool = True,
        fresh: bool = False,
    ) -> SecondarySnapshot:
        """Fetch and return normalized DynastyProcess values as a SecondarySnapshot."""
        values_ttl = self.ttl if use_cache and not fresh else 0
        ids_ttl = self.ids_ttl if use_cache and not fresh else 0

        try:
            values_text = get_text(self.values_url, ttl=values_ttl)
            fetched_at = _cache_file(self.values_url, None).stat().st_mtime
            ids_text = get_text(self.ids_url, ttl=ids_ttl)
            fp_to_sleeper = _parse_id_map(ids_text)
        except Exception as err:
            logger.warning("Failed to fetch DynastyProcess data: %s", err)
            return _empty_snapshot()

        if not values_text.strip():
            return _empty_snapshot()

        is_sf = True if fmt is None or fmt.superflex else False
        val_col = "value_2qb" if is_sf else "value_1qb"
        values: Dict[str, int] = {}

        try:
            for row in csv.DictReader(io.StringIO(values_text)):
                raw_val = (row.get(val_col) or "").strip()
                if not raw_val:
                    continue
                try:
                    val = max(0, int(round(float(raw_val))))
                except (ValueError, TypeError):
                    continue

                name = (row.get("player") or "").strip()
                pos = (row.get("pos") or "").strip().upper()
                if pos in ("PICK", "RDP"):
                    norm_pk = normalize_pick(name) if name else None
                    if norm_pk:
                        values[norm_pk] = val
                else:
                    norm = normalize_name(name) if name else None
                    if norm:
                        values[norm] = val
                    fp_id = (row.get("fp_id") or "").strip()
                    if fp_id and fp_id in fp_to_sleeper:
                        values[fp_to_sleeper[fp_id]] = val
        except Exception as err:
            logger.warning("Failed to parse DynastyProcess values CSV: %s", err)
            return _empty_snapshot()

        notes: List[str] = []
        if fmt is not None and fmt.tep > 0:
            notes.append("DynastyProcess values do not adjust for TE premium")

        return SecondarySnapshot(
            source="dp",
            label="DynastyProcess",
            values=values,
            top=None,
            fetched_at=fetched_at,
            notes=notes,
        )

    def fetch_values(
        self,
        fmt: Optional[Format] = None,
        use_cache: bool = True,
        fresh: bool = False,
    ) -> Dict[str, int]:
        """Fetch and return DynastyProcess values mapped by sleeper_id, name, or pick."""
        return self.fetch_snapshot(fmt=fmt, use_cache=use_cache, fresh=fresh).values
