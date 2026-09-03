"""Backward-compatibility module for DynastyDealerClient redirecting to KtcClient."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import requests

from ff.contracts import Format
from ff.core.http import get_json
from ff.values.ktc import (
    KTC_VALUES_TTL as DEALER_VALUES_TTL,
    KTC_VALUES_URL as DEALER_VALUES_URL,
    KtcClient,
)
from ff.values.normalize import normalize_name, normalize_pick

logger = logging.getLogger(__name__)


class DynastyDealerClient(KtcClient):
    """Backward-compatible DynastyDealerClient delegating to KtcClient."""

    def __init__(self, url: str = DEALER_VALUES_URL, ttl: float = DEALER_VALUES_TTL) -> None:
        super().__init__(url=url, ttl=ttl)

    def fetch_values(self, fmt: Optional[Format] = None, use_cache: bool = True) -> Dict[str, int]:
        """Fetch values, supporting get_json mocking for backward compatibility."""
        try:
            data = get_json(self.url, ttl=self.ttl)
        except Exception as err:
            logger.warning("Failed to fetch secondary values from %s: %s", self.url, err)
            return {}

        if not data:
            return {}

        if isinstance(data, (dict, list)):
            return self._parse_from_data(data, fmt=fmt)

        return super().fetch_values(fmt=fmt, use_cache=use_cache)

    def _parse_from_data(self, data: Any, fmt: Optional[Format] = None) -> Dict[str, int]:
        if isinstance(data, dict):
            raw_players = data.get("players") or data.get("values") or []
        elif isinstance(data, list):
            raw_players = data
        else:
            return {}

        if not isinstance(raw_players, list):
            return {}

        is_sf = True if fmt is None or fmt.superflex else False
        values: Dict[str, int] = {}
        for entry in raw_players:
            if not isinstance(entry, dict):
                continue
            sleeper_id = entry.get("sleeper_id") or entry.get("sleeperId")
            name = entry.get("playerName") or entry.get("name") or ""
            is_pick = entry.get("position") in ("PICK", "RDP") or str(sleeper_id or "").startswith("pick_")

            val_data = entry.get("superflexValues") if is_sf else entry.get("oneQBValues")
            raw_val = None
            if isinstance(val_data, dict):
                raw_val = val_data.get("value")
            if raw_val is None:
                raw_val = entry.get("current_value")
            if raw_val is None:
                raw_val = entry.get("value")
            if raw_val is None:
                raw_val = entry.get("base_value", 0)

            try:
                val = int(round(float(raw_val))) if raw_val is not None else 0
            except (ValueError, TypeError):
                continue

            if is_pick:
                norm_pk = normalize_pick(str(name)) if name else None
                if norm_pk:
                    values[norm_pk] = val
                    if norm_pk.endswith(" mid"):
                        base_pk = norm_pk[:-4].strip()
                        values.setdefault(base_pk, val)
                if sleeper_id:
                    values[str(sleeper_id)] = val
            else:
                norm = normalize_name(str(name)) if name else None
                if norm:
                    values[norm] = val
                if sleeper_id is not None:
                    values[str(sleeper_id)] = val

        return values


__all__ = ["DynastyDealerClient", "DEALER_VALUES_URL", "DEALER_VALUES_TTL"]
