"""Secondary market dynasty values from Dynasty Dealer API.

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

DEALER_VALUES_URL = "https://www.dynastydealer.com/api/player-values"
DEALER_VALUES_TTL = 6 * 3600  # 6 hours


class DynastyDealerClient:
    """Client for fetching secondary market dynasty values from Dynasty Dealer."""

    def __init__(self, url: str = DEALER_VALUES_URL, ttl: float = DEALER_VALUES_TTL) -> None:
        self.url = url
        self.ttl = ttl

    def fetch_values(self, fmt: Optional[Format] = None) -> Dict[str, int]:
        """Fetch and return Dynasty Dealer values mapped by sleeper_id or canonical pick label."""
        try:
            data = get_json(self.url, ttl=self.ttl)
        except Exception as err:
            logger.warning("Failed to fetch Dynasty Dealer values from %s: %s", self.url, err)
            return {}

        if not isinstance(data, dict):
            return {}

        raw_players = data.get("players")
        if not isinstance(raw_players, list):
            return {}

        values: Dict[str, int] = {}
        for entry in raw_players:
            if not isinstance(entry, dict):
                continue
            sleeper_id = entry.get("sleeper_id")
            name = entry.get("name") or ""
            is_pick = entry.get("position") == "PICK" or str(sleeper_id or "").startswith("pick_")
            raw_val = entry.get("current_value")
            if raw_val is None:
                raw_val = entry.get("base_value", 0)
            try:
                val = int(round(float(raw_val))) if raw_val is not None else 0
            except (ValueError, TypeError):
                continue

            if is_pick:
                pick_from_name = normalize_pick(str(name)) if name else None
                if pick_from_name:
                    values[pick_from_name] = val
                if sleeper_id:
                    values[str(sleeper_id)] = val
            elif sleeper_id is not None:
                values[str(sleeper_id)] = val

        return values
