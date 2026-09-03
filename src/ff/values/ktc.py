"""Secondary market dynasty values from KeepTradeCut (KTC).

Fetches crowdsourced dynasty valuations directly from keeptradecut.com/dynasty-rankings.
Extracts player and draft pick valuations from the embedded rankings dataset with
automatic disk caching and graceful degradation if the endpoint is offline.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from typing import Any, Dict, List, Optional

import requests

from ff.contracts import Format
from ff.core.http import _atomic_write, _cache_file, _fresh
from ff.values.normalize import normalize_name, normalize_pick

logger = logging.getLogger(__name__)

KTC_VALUES_URL = "https://keeptradecut.com/dynasty-rankings"
KTC_VALUES_TTL = 6 * 3600  # 6 hours

# Canonical aliases for common nickname differences between KTC and Sleeper/FantasyCalc
ALIASES: Dict[str, str] = {
    "kenneth gainwell": "kenny gainwell",
    "chigoziem okonkwo": "chig okonkwo",
    "matthew hibner": "matt hibner",
    "gabriel davis": "gabe davis",
    "bam knight": "zonovan knight",
}


def _extract_players(text: str) -> List[Dict[str, Any]]:
    """Extract player/pick entries from KTC HTML or raw JSON."""
    text_stripped = text.strip()
    if text_stripped.startswith("[") or text_stripped.startswith("{"):
        try:
            parsed = json.loads(text_stripped)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                return parsed.get("players") or parsed.get("values") or parsed.get("data") or []
        except (json.JSONDecodeError, ValueError):
            pass

    m = re.search(r"var\s+playersArray\s*=\s*(\[.*?\])\s*;", text, re.DOTALL)
    if not m:
        return []
    try:
        parsed = json.loads(m.group(1))
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, ValueError):
        return []


class KtcClient:
    """Client for fetching secondary market dynasty values from KeepTradeCut."""

    def __init__(self, url: str = KTC_VALUES_URL, ttl: float = KTC_VALUES_TTL) -> None:
        self.url = url
        self.ttl = ttl

    def _fetch_text(self, use_cache: bool = True) -> str:
        cache_path = _cache_file(self.url, None)
        if use_cache and _fresh(cache_path, self.ttl):
            try:
                return cache_path.read_text()
            except (ValueError, OSError):
                pass

        ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
        html = ""
        try:
            resp = requests.get(self.url, headers={"User-Agent": ua}, timeout=30)
            resp.raise_for_status()
            html = resp.text
        except requests.exceptions.SSLError:
            # Apple Command Line Tools Python on macOS is linked to LibreSSL 2.8.3,
            # which lacks TLS 1.3 support required by keeptradecut.com. Fall back to curl.
            try:
                res = subprocess.run(
                    ["curl", "-s", "--compressed", "-H", "User-Agent: " + ua, self.url],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=True,
                )
                html = res.stdout
            except Exception as err:
                logger.warning("Failed to fetch KTC values via curl from %s: %s", self.url, err)
                return ""
        except Exception as err:
            logger.warning("Failed to fetch KTC values from %s: %s", self.url, err)
            return ""

        if html and use_cache:
            _atomic_write(cache_path, html)
        return html

    def fetch_values(self, fmt: Optional[Format] = None, use_cache: bool = True) -> Dict[str, int]:
        """Fetch and return KTC values mapped by sleeper_id, normalized name, or pick label."""
        text = self._fetch_text(use_cache=use_cache)
        if not text:
            return {}

        raw_players = _extract_players(text)
        if not raw_players:
            return {}

        is_sf = True if fmt is None or fmt.superflex else False
        values: Dict[str, int] = {}

        for entry in raw_players:
            if not isinstance(entry, dict):
                continue

            name = entry.get("playerName") or entry.get("name") or ""
            pos = entry.get("position") or ""
            sleeper_id = entry.get("sleeper_id") or entry.get("sleeperId")
            is_pick = pos == "RDP" or pos == "PICK" or str(sleeper_id or "").startswith("pick_")

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
                norm_pk = normalize_pick(name) if name else None
                if norm_pk:
                    values[norm_pk] = val
                    if norm_pk.endswith(" mid"):
                        base_pk = norm_pk[:-4].strip()
                        if base_pk not in values:
                            values[base_pk] = val
                if sleeper_id:
                    values[str(sleeper_id)] = val
            else:
                norm = normalize_name(name) if name else None
                if norm:
                    values[norm] = val
                    if norm in ALIASES:
                        values[ALIASES[norm]] = val
                if sleeper_id is not None:
                    values[str(sleeper_id)] = val

        return values
