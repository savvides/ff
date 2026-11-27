"""FantasyCalc values + the resolvers that turn user input into priced Assets.

The hard part is not the HTTP call (one GET) - it is matching:
  * a Sleeper roster's player_ids -> values  (exact, via sleeperId)
  * a human-typed "Jahmyr Gibbs"  -> a value (fuzzy, via normalized name)
  * a human-typed "2027 1st"      -> a pick value (canonicalized pick label)
"""

from __future__ import annotations

import difflib
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from ff.contracts import Asset, Format
from ff.core.http import _cache_file, get_json
from ff.values.dp import DynastyProcessClient
from ff.values.ktc import KtcClient
from ff.values.normalize import normalize_name, normalize_pick
from ff.values.snapshot import SecondarySnapshot


VALUES_URL = "https://api.fantasycalc.com/values/current"
VALUES_TTL = 6 * 3600  # values drift slowly; refresh a few times a day


def _asset_from_entry(
    entry: dict,
    secondary_map: Optional[Dict[str, int]] = None,
    dealer_map: Optional[Dict[str, int]] = None,
    ktc_map: Optional[Dict[str, int]] = None,
    approx_keys: Optional[Set[str]] = None,
) -> Asset:
    p = entry.get("player", {})
    position = p.get("position")
    is_pick = position == "PICK"
    name = p.get("name", "?")
    if is_pick:
        ident = normalize_pick(name) or normalize_name(name)
    else:
        ident = str(p.get("sleeperId") or p.get("id"))

    sec_map = secondary_map if secondary_map is not None else (dealer_map if dealer_map is not None else ktc_map)
    sec_val: Optional[int] = None
    sec_key: Optional[str] = None
    if sec_map:
        if is_pick:
            norm_pk = normalize_pick(name)
            for key in (norm_pk, ident):
                if key and key in sec_map:
                    sec_key = key
                    break
        else:
            sleeper_id = p.get("sleeperId")
            for key in (str(sleeper_id) if sleeper_id is not None else None,
                        normalize_name(name), ident):
                if key and key in sec_map:
                    sec_key = key
                    break
        if sec_key is not None:
            sec_val = sec_map[sec_key]

    return Asset(
        id=ident,
        name=name,
        kind="pick" if is_pick else "player",
        position=position,
        team=p.get("maybeTeam"),
        age=p.get("maybeAge"),
        value=int(entry.get("value", 0) or 0),
        secondary_value=sec_val,
        secondary_approx=sec_key in (approx_keys or set()),
        overall_rank=entry.get("overallRank"),
        position_rank=entry.get("positionRank"),
        trend_30day=entry.get("trend30Day"),
        redraft_value=int(entry.get("redraftValue", 0) or 0) or None,
    )



class ValueBook:
    """An indexed snapshot of FantasyCalc values for one league format.

    `secondary_top` is KTC's most valuable asset in the same format/TEP (an input to
    KTC's trade adjustment); it defaults to the largest secondary value in the book
    for KTC/legacy books and remains `None` for DynastyProcess. The fetch metadata
    (`format`, `fetched_at`, `secondary_fetched_at`, `secondary_html`,
    `secondary_source`, `secondary_label`, `secondary_notes`) lets `ff trade` say
    where its numbers came from and check the KTC calculator code for drift."""

    def __init__(
        self,
        assets: List[Asset],
        *,
        secondary_top: Optional[int] = None,
        fmt: Optional[Format] = None,
        fetched_at: Optional[float] = None,
        secondary_fetched_at: Optional[float] = None,
        secondary_html: str = "",
        secondary_map: Optional[Dict[str, int]] = None,
        secondary_source: Optional[str] = None,
        secondary_label: str = "KTC",
        secondary_notes: Optional[List[str]] = None,
    ) -> None:
        self.assets = assets
        # Secondary market's own values by key, so a pick can be priced at the tier
        # a trade names (or fall back to the flat round for markets like DP).
        self.secondary_map: Dict[str, int] = dict(secondary_map or {})
        self.secondary_source = secondary_source
        self.secondary_label = secondary_label
        self.secondary_notes: List[str] = list(secondary_notes or [])
        if secondary_top is None and secondary_source in (None, "ktc"):
            priced = [a.secondary_value for a in assets if a.secondary_value is not None]
            secondary_top = max(priced) if priced else None
        self.secondary_top = secondary_top
        self.format = fmt
        self.fetched_at = fetched_at
        self.secondary_fetched_at = secondary_fetched_at
        self.secondary_html = secondary_html
        self.by_sleeper_id: Dict[str, Asset] = {}
        self.by_name: Dict[str, Asset] = {}
        self.by_surname: Dict[str, List[Asset]] = {}
        self.picks: Dict[str, Asset] = {}
        for a in assets:
            if a.is_pick:
                self.picks[a.id] = a
                continue
            self.by_sleeper_id[a.id] = a
            key = normalize_name(a.name)
            # On a normalized-name collision (e.g. "Michael Carter" vs
            # "Michael Carter II" both strip to "michael carter"), keep the more
            # valuable asset rather than letting list order decide silently.
            cur = self.by_name.get(key)
            if cur is None or a.value > cur.value:
                self.by_name[key] = a
            surname = key.split()[-1] if key else ""
            if surname:
                self.by_surname.setdefault(surname, []).append(a)
        self._name_keys = list(self.by_name.keys())

    # --- lookups ---------------------------------------------------------
    def _flat_pick_fallback(self, pick: Asset, season: str, round_: str) -> Optional[Asset]:
        """Fall back to a flat round key for non-KTC markets when a tiered pick is unpriced."""
        if pick.secondary_value is not None or self.secondary_source in (None, "ktc"):
            return None
        flat = self.secondary_map.get(f"{season} {round_}")
        if flat is None:
            return None
        return pick.model_copy(update={"secondary_value": flat, "secondary_approx": False})

    def pick_at_tier(self, season: str, round_: int, tier: str) -> Optional[Asset]:
        """The pick "<season> <round> <tier>" priced as each site prices it: the
        FantasyCalc tiered entry when it has one (else its flat round value), and
        the secondary market's value for that tier (falling back to the flat round
        when the active secondary market is not KTC). None if FantasyCalc has no
        such round."""
        fc = self.picks.get(f"{season} {round_} {tier}") or self.picks.get(f"{season} {round_}")
        if fc is None:
            return None
        ordinal = {1: "1st", 2: "2nd", 3: "3rd"}.get(round_, f"{round_}th")
        out = fc.model_copy()
        out.name = f"{season} {ordinal} ({tier.capitalize()})"
        tiered = self.secondary_map.get(f"{season} {round_} {tier}")
        if tiered is None and self.secondary_source not in (None, "ktc"):
            tiered = self.secondary_map.get(f"{season} {round_}")
        out.secondary_value = tiered
        out.secondary_approx = False
        return out

    def value_for_sleeper_id(self, sleeper_id: str) -> Optional[Asset]:
        return self.by_sleeper_id.get(str(sleeper_id))

    def resolve(self, token: str) -> Optional[Asset]:
        """Turn a free-text trade token into an Asset (player or pick)."""
        token = token.strip()
        if not token:
            return None

        # a draft pick?
        pk = normalize_pick(token)
        if pk:
            if pk in self.picks:
                pick = self.picks[pk]
                m = re.match(r"(20\d{2}) ([1-9]) (early|mid|late)$", pk)
                if m:
                    return self._flat_pick_fallback(pick, m.group(1), m.group(2)) or pick
                return pick
            # round-level fallback for a slot pick we don't have ("2026 pick 1.05"
            # -> "2026 1") so traded future picks still get a value.
            m = re.match(r"(20\d{2}) pick (\d+)\.\d+", pk)
            if m and f"{m.group(1)} {m.group(2)}" in self.picks:
                return self.picks[f"{m.group(1)} {m.group(2)}"]
            # tier fallback both ways: a tiered ask without a tiered entry drops
            # to the flat round value on FantasyCalc and is that exact tier on KTC;
            # a flat ask with only tiered entries takes mid, the neutral assumption
            # when the slot is unknown. That Mid is a guess, so its KTC price is
            # flagged as a stand-in, never an exact match.
            m = re.match(r"(20\d{2}) ([1-9]) (early|mid|late)$", pk)
            if m:
                return self.pick_at_tier(m.group(1), int(m.group(2)), m.group(3))
            if f"{pk} mid" in self.picks:
                mid = self.picks[f"{pk} mid"]
                if (
                    self.secondary_source not in (None, "ktc")
                    and re.match(r"(20\d{2}) ([1-9])$", pk)
                    and pk in self.secondary_map
                ):
                    return mid.model_copy(
                        update={"secondary_value": self.secondary_map[pk], "secondary_approx": False}
                    )
                mid_copy = mid.model_copy()
                mid_copy.secondary_approx = mid_copy.secondary_value is not None
                return mid_copy
            return None

        # a player, by exact normalized name then fuzzy
        norm = normalize_name(token)
        if norm in self.by_name:
            return self.by_name[norm]
        if norm.isdigit() and norm in self.by_sleeper_id:
            return self.by_sleeper_id[norm]
        # Fuzzy, but tight: 0.85 silently swaps distinct players (Brian Robinson
        # -> Bijan Robinson scores 0.93). 0.93 still passes real typos
        # ("Bijan Robison" = 0.96) while refusing to guess between two real names.
        close = difflib.get_close_matches(norm, self._name_keys, n=1, cutoff=0.93)
        if close:
            return self.by_name[close[0]]
        # Surname-only shorthand ("Gibbs"), but only when it is unambiguous.
        if " " not in norm:
            matches = self.by_surname.get(norm)
            if matches and len({m.id for m in matches}) == 1:
                return matches[0]
        return None

    def suggest(self, token: str, n: int = 3) -> List[Asset]:
        """Best-guess candidates for an unresolved token, for a 'did you mean'
        hint. Surname matches for a single word (the common ambiguous case),
        else loose fuzzy matches. Never used to auto-resolve - display only."""
        norm = normalize_name(token)
        if not norm:
            return []
        if " " not in norm and norm in self.by_surname:
            return self.by_surname[norm][:n]
        close = difflib.get_close_matches(norm, self._name_keys, n=n, cutoff=0.6)
        return [self.by_name[c] for c in close]

    def top(self, position: Optional[str] = None, limit: Optional[int] = 50,
            exclude: Optional[set] = None) -> List[Asset]:
        """Players ranked by dynasty value. `exclude` drops ids already taken
        (rostered/drafted); `limit=None` returns the whole ranked pool."""
        pool = [a for a in self.assets if not a.is_pick]
        if exclude:
            pool = [a for a in pool if a.id not in exclude]
        if position:
            pool = [a for a in pool if a.position == position.upper()]
        return sorted(pool, key=lambda a: a.value, reverse=True)[:limit]


def _normalize_mode(mode: str) -> str:
    """Normalize secondary market selection to 'dp', 'ktc', or 'none'."""
    norm = mode.strip().lower()
    if norm == "dealer":
        return "ktc"
    if norm not in ("dp", "ktc", "none"):
        raise ValueError(f"Unsupported secondary market: {mode!r} (expected 'dp', 'ktc', or 'none')")
    return norm


class ValuesClient:
    """Fetches FantasyCalc dynasty values merged with a pluggable secondary market."""

    def __init__(
        self,
        url: str = VALUES_URL,
        secondary: str = "dp",
        dp_client: Optional[DynastyProcessClient] = None,
        ktc_client: Optional[KtcClient] = None,
        dealer_client: Optional[KtcClient] = None,
        ktc_file: Optional[Path] = None,
    ) -> None:
        self.url = url
        self.dp_client = dp_client or DynastyProcessClient()
        self.ktc_file = ktc_file
        self.ktc_client = ktc_client or dealer_client or KtcClient(file_path=ktc_file)
        norm_sec = _normalize_mode(secondary)
        if norm_sec == "dp" and (
            ktc_file is not None
            or (dp_client is None and (ktc_client is not None or dealer_client is not None))
        ):
            self.secondary = "ktc"
        else:
            self.secondary = norm_sec

    @property
    def dealer_client(self) -> KtcClient:
        return self.ktc_client

    @dealer_client.setter
    def dealer_client(self, client: KtcClient) -> None:
        self.ktc_client = client

    @staticmethod
    def _fetch_ktc_snapshot(client: Any, fmt: Format, fresh: bool) -> SecondarySnapshot:
        """Fetch a SecondarySnapshot from KtcClient or a legacy fetch_values()-only mock."""
        if hasattr(client, "fetch_snapshot"):
            snap = client.fetch_snapshot(fmt, fresh=fresh)
            if isinstance(snap, SecondarySnapshot):
                return snap
        raw_vals = client.fetch_values(fmt, fresh=fresh) or {}
        values = raw_vals if isinstance(raw_vals, dict) else {}
        top_v = getattr(client, "last_top", None)
        fetched_v = getattr(client, "last_fetched_at", None)
        approx_v = getattr(client, "last_approx_keys", None)
        html_v = getattr(client, "last_html", None)
        return SecondarySnapshot(
            source="ktc",
            label="KTC",
            values=values,
            top=top_v if isinstance(top_v, int) and not isinstance(top_v, bool) else None,
            fetched_at=(
                float(fetched_v)
                if isinstance(fetched_v, (int, float)) and not isinstance(fetched_v, bool)
                else None
            ),
            approx_keys=approx_v if isinstance(approx_v, set) else set(),
            html=html_v if isinstance(html_v, str) else "",
        )

    def _fetch_secondary(
        self,
        mode: str,
        fmt: Format,
        fresh: bool,
        ktc_file: Optional[Path],
    ) -> SecondarySnapshot:
        """Fetch the active secondary market snapshot, degrading on network errors."""
        if mode == "none":
            return SecondarySnapshot(source="none", label="None", values={})
        if mode == "dp":
            try:
                snap = self.dp_client.fetch_snapshot(fmt, fresh=fresh)
                if isinstance(snap, SecondarySnapshot):
                    return snap
            except Exception:
                pass
            return SecondarySnapshot(source="dp", label="DynastyProcess", values={})
        ktc = KtcClient(file_path=ktc_file) if ktc_file is not None else self.ktc_client
        try:
            return self._fetch_ktc_snapshot(ktc, fmt, fresh)
        except ValueError:
            raise
        except Exception:
            return SecondarySnapshot(source="ktc", label="KTC", values={})

    def fetch(
        self,
        fmt: Format,
        include_secondary: bool = True,
        include_ktc: bool = True,
        fresh: bool = False,
        secondary: Optional[str] = None,
        ktc_file: Optional[Path] = None,
    ) -> ValueBook:
        """`fresh` fetches both markets live (and refreshes the cache) instead of
        using a copy up to VALUES_TTL old; `ff trade` uses it so its numbers match
        what the sites show right now."""
        params = fmt.fantasycalc_params()
        data = get_json(self.url, params=params, ttl=0 if fresh else VALUES_TTL)
        try:
            fetched_at: Optional[float] = _cache_file(self.url, params).stat().st_mtime
        except OSError:
            fetched_at = time.time()

        if not (include_secondary and include_ktc):
            mode = "none"
        elif ktc_file is not None:
            mode = "ktc"
        else:
            mode = _normalize_mode(secondary or self.secondary)

        snap = self._fetch_secondary(mode, fmt, fresh, ktc_file)
        assets = [
            _asset_from_entry(e, secondary_map=snap.values, approx_keys=snap.approx_keys)
            for e in (data if isinstance(data, list) else [])
        ]
        return ValueBook(
            assets,
            secondary_top=snap.top if snap.values else None,
            fmt=fmt,
            fetched_at=fetched_at,
            secondary_fetched_at=snap.fetched_at,
            secondary_html=snap.html if snap.values else "",
            secondary_map=snap.values,
            secondary_source=snap.source,
            secondary_label=snap.label,
            secondary_notes=snap.notes,
        )

