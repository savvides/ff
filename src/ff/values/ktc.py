"""Secondary market dynasty values from KeepTradeCut (KTC) via Dynasty Daddy API.

Fetches crowdsourced/secondary market valuations for players and draft picks.
Values are normalized to Sleeper player IDs and canonical draft-pick labels,
with automatic disk caching and graceful degradation if the endpoint is offline.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

from ff.contracts import Format
from ff.core.http import get_json
from ff.values.normalize import normalize_pick

logger = logging.getLogger(__name__)

KTC_VALUES_URL = "https://api.dynastydaddy.com/v1/values"
KTC_VALUES_TTL = 6 * 3600  # 6 hours


class KtcClient:
    """Client for fetching secondary market dynasty values from KeepTradeCut."""

    def __init__(self, url: str = KTC_VALUES_URL, ttl: float = KTC_VALUES_TTL) -> None:
        self.url = url
        self.ttl = ttl

    def fetch_values(self, fmt: Optional[Format] = None) -> Dict[str, int]:
        """Fetch and return KTC values mapped by sleeper_id or canonical pick label."""
        try:
            data = get_json(self.url, ttl=self.ttl)
        except Exception as err:
            logger.warning("Failed to fetch KTC values from %s: %s", self.url, err)
            return {}

        if not isinstance(data, list):
            if isinstance(data, dict):
                data = data.get("values") or data.get("players") or data.get("data") or []
            else:
                return {}

        values: Dict[str, int] = {}
        for entry in data:
            if not isinstance(entry, dict):
                continue
            raw_id = (
                entry.get("player_id")
                or entry.get("sleeper_id")
                or entry.get("id")
                or entry.get("sleeperId")
            )
            name = entry.get("name") or entry.get("player_name") or ""
            raw_val = entry.get("value")
            if raw_val is None:
                raw_val = entry.get("ktc_value", 0)
            try:
                val = int(raw_val or 0)
            except (ValueError, TypeError):
                continue

            pick_from_name = normalize_pick(str(name)) if name else None
            pick_from_id = normalize_pick(str(raw_id)) if raw_id is not None else None

            if pick_from_name or pick_from_id:
                if pick_from_name:
                    values[pick_from_name] = val
                if pick_from_id:
                    values[pick_from_id] = val
            elif raw_id is not None:
                values[str(raw_id)] = val

        return values
