"""Secondary market dynasty values from KeepTradeCut (KTC).

Fetches crowdsourced dynasty valuations from keeptradecut.com/trade-calculator (the
page whose calculator ff reproduces). Extracts player and draft pick valuations from
the embedded rankings dataset, picking the same field the page itself uses for the
league's format and TE-premium tier, with disk caching and graceful degradation if
the endpoint is offline. The last fetch's top value, time and page are kept on the
client for the calculator port and the drift check.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from ff.contracts import Format
from ff.core.config import home
from ff.core.http import _cache_file, get_text
from ff.values.normalize import normalize_name, normalize_pick
from ff.values.snapshot import SecondarySnapshot

logger = logging.getLogger(__name__)

KTC_VALUES_URL = "https://keeptradecut.com/trade-calculator"
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

    # Current page (seen 2026-09-29): the rankings ship as JSON inside
    # <script type="application/json" id="ktc-players">, and the page's own JS
    # reads them with `playersArray = JSON.parse(...)`.
    m = re.search(r"<script[^>]*\bid=[\"']ktc-players[\"'][^>]*>(.*?)</script>", text, re.DOTALL)
    if m:
        try:
            parsed = json.loads(m.group(1))
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass

    # Older page: an inline `var playersArray = [...]` literal.
    m = re.search(r"var\s+playersArray\s*=\s*(\[.*?\])\s*;", text, re.DOTALL)
    if not m:
        return []
    try:
        parsed = json.loads(m.group(1))
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, ValueError):
        return []


def _parse_raw_players(
    raw_players: List[Dict[str, Any]], fmt: Optional[Format] = None
) -> Tuple[Dict[str, int], Optional[int], Set[str]]:
    """Parse raw KTC player/pick entries into (values, top, approx_keys)."""
    is_sf = True if fmt is None or fmt.superflex else False
    # The page's updateSingleDynastyAsset: TE+ / TE++ read the nested tep/tepp
    # values (only TEs differ); tier 0 reads the base value.
    tier_key = {1: "tep", 2: "tepp"}.get(fmt.ktc_tep_tier() if fmt is not None else 0)
    values: Dict[str, int] = {}
    approx_keys: Set[str] = set()
    top = 0

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
            tiered = val_data.get(tier_key) if tier_key else None
            raw_val = tiered.get("value") if isinstance(tiered, dict) else None
            if raw_val is None:
                raw_val = val_data.get("value")
        if raw_val is None:
            raw_val = entry.get("current_value")
        if raw_val is None:
            raw_val = entry.get("value")
        if raw_val is None:
            raw_val = entry.get("base_value", 0)

        try:
            val = max(0, int(round(float(raw_val)))) if raw_val is not None else 0
        except (ValueError, TypeError):
            continue
        top = max(top, val)

        if is_pick:
            norm_pk = normalize_pick(name) if name else None
            if norm_pk:
                values[norm_pk] = val
                if norm_pk.endswith(" mid"):
                    base_pk = norm_pk[:-4].strip()
                    if base_pk not in values:
                        values[base_pk] = val
                        approx_keys.add(base_pk)
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

    return values, (top or None), approx_keys


class KtcClient:
    """Client for fetching secondary market dynasty values from KeepTradeCut."""

    def __init__(
        self,
        url: str = KTC_VALUES_URL,
        ttl: float = KTC_VALUES_TTL,
        file_path: Optional[Path] = None,
    ) -> None:
        self.url = url
        self.ttl = ttl
        self.file_path = file_path
        # Set by fetch_snapshot/fetch_values: the most valuable asset in the chosen format/TEP
        # (the page's playersArray[0].value, an input to KTC's adjustment), when the page
        # was fetched, and which keys are
        # approximations (KTC prices only Early/Mid/Late picks, so a generic
        # "2028 1st" key holds the Mid value as a stand-in).
        self.last_top: Optional[int] = None
        self.last_fetched_at: Optional[float] = None
        self.last_approx_keys: Set[str] = set()
        self.last_html: str = ""

    def _fetch_text(self, use_cache: bool = True, fresh: bool = False) -> str:
        """Page HTML ("" when unreachable). `fresh` or `use_cache=False` skips a
        cached copy; the cache is refreshed either way."""
        try:
            html = get_text(self.url, ttl=self.ttl if use_cache and not fresh else 0)
            self.last_fetched_at = _cache_file(self.url, None).stat().st_mtime
        except Exception as err:
            logger.warning("Failed to fetch KTC values from %s: %s", self.url, err)
            return ""
        return html

    def _load_local_pool(self, path: Path) -> List[Dict[str, Any]]:
        """Read and validate a KTC pool JSON file as a list of entries."""
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError) as err:
            raise ValueError(f"Invalid or missing KTC pool file: {path}") from err
        if not isinstance(parsed, list):
            raise ValueError(f"Invalid or missing KTC pool file: {path}")
        return parsed

    def fetch_snapshot(
        self,
        fmt: Optional[Format] = None,
        use_cache: bool = True,
        fresh: bool = False,
    ) -> SecondarySnapshot:
        """Fetch and return a SecondarySnapshot of KTC values."""
        self.last_top, self.last_approx_keys = None, set()
        raw_players: List[Dict[str, Any]] = []

        if self.file_path is not None:
            self.last_html = ""
            raw_players = self._load_local_pool(self.file_path)
            self.last_fetched_at = self.file_path.stat().st_mtime
        else:
            text = self._fetch_text(use_cache=use_cache, fresh=fresh)
            self.last_html = text
            raw_players = _extract_players(text) if text else []
            if not raw_players:
                pool_path = home() / "ktc_pool.json"
                if pool_path.is_file():
                    try:
                        raw_players = self._load_local_pool(pool_path)
                        self.last_fetched_at = pool_path.stat().st_mtime
                    except ValueError:
                        raw_players = []

        if not raw_players:
            return SecondarySnapshot(
                source="ktc",
                label="KTC",
                values={},
                top=None,
                fetched_at=self.last_fetched_at,
                approx_keys=set(),
                html=self.last_html,
            )

        values, top, approx_keys = _parse_raw_players(raw_players, fmt)
        self.last_top = top
        self.last_approx_keys = approx_keys
        return SecondarySnapshot(
            source="ktc",
            label="KTC",
            values=values,
            top=top,
            fetched_at=self.last_fetched_at,
            approx_keys=set(approx_keys),
            html=self.last_html,
        )

    def fetch_values(
        self,
        fmt: Optional[Format] = None,
        use_cache: bool = True,
        fresh: bool = False,
    ) -> Dict[str, int]:
        """Fetch and return KTC values mapped by sleeper_id, normalized name, or pick label."""
        return self.fetch_snapshot(fmt, use_cache=use_cache, fresh=fresh).values
