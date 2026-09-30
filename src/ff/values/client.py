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
from typing import Dict, List, Optional, Set

from ff.contracts import Asset, Format
from ff.core.http import _cache_file, get_json
from ff.values.ktc import KtcClient
from ff.values.normalize import normalize_name, normalize_pick


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
    sec_source = None if sec_key is None else ("approx" if sec_key in (approx_keys or set()) else "exact")

    return Asset(
        id=ident,
        name=name,
        kind="pick" if is_pick else "player",
        position=position,
        team=p.get("maybeTeam"),
        age=p.get("maybeAge"),
        value=int(entry.get("value", 0) or 0),
        secondary_value=sec_val,
        secondary_source=sec_source,
        overall_rank=entry.get("overallRank"),
        position_rank=entry.get("positionRank"),
        trend_30day=entry.get("trend30Day"),
        redraft_value=int(entry.get("redraftValue", 0) or 0) or None,
    )



class ValueBook:
    """An indexed snapshot of FantasyCalc values for one league format.

    `secondary_top` is KTC's most valuable asset in the same format/TEP (an input to
    KTC's trade adjustment); it defaults to the largest KTC value in the book. The
    fetch metadata (`format`, `fetched_at`, `secondary_fetched_at`,
    `secondary_version`, `secondary_html`) lets `ff trade` say where its numbers
    came from and check the KTC calculator code for drift."""

    def __init__(self, assets: List[Asset], *, secondary_top: Optional[int] = None,
                 fmt: Optional[Format] = None, fetched_at: Optional[float] = None,
                 secondary_fetched_at: Optional[float] = None,
                 secondary_version: Optional[str] = None, secondary_html: str = "",
                 secondary_map: Optional[Dict[str, int]] = None) -> None:
        self.assets = assets
        # KTC's own values by key, so a pick can be priced at the tier a trade names
        # (KTC has Early/Mid/Late for every year; FantasyCalc only near-season).
        self.secondary_map: Dict[str, int] = dict(secondary_map or {})
        if secondary_top is None:
            priced = [a.secondary_value for a in assets if a.secondary_value is not None]
            secondary_top = max(priced) if priced else None
        self.secondary_top = secondary_top
        self.format = fmt
        self.fetched_at = fetched_at
        self.secondary_fetched_at = secondary_fetched_at
        self.secondary_version = secondary_version
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
    def pick_at_tier(self, season: str, round_: int, tier: str) -> Optional[Asset]:
        """The pick "<season> <round> <tier>" priced as each site prices it: the
        FantasyCalc tiered entry when it has one (else its flat round value), and
        KTC's value for that exact tier. None if FantasyCalc has no such round."""
        fc = self.picks.get(f"{season} {round_} {tier}") or self.picks.get(f"{season} {round_}")
        if fc is None:
            return None
        ordinal = {1: "1st", 2: "2nd", 3: "3rd"}.get(round_, f"{round_}th")
        out = fc.model_copy()
        out.name = f"{season} {ordinal} ({tier.capitalize()})"
        ktc = self.secondary_map.get(f"{season} {round_} {tier}")
        out.secondary_value = ktc
        out.secondary_source = "exact" if ktc is not None else None
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
                return self.picks[pk]
            # round-level fallback for a slot pick we don't have ("2026 pick 1.05"
            # -> "2026 1") so traded future picks still get a value.
            m = re.match(r"(20\d{2}) pick (\d+)\.\d+", pk)
            if m and f"{m.group(1)} {m.group(2)}" in self.picks:
                return self.picks[f"{m.group(1)} {m.group(2)}"]
            # tier fallback both ways: a tiered ask without a tiered entry drops
            # to the flat round value; a flat ask with only tiered entries takes
            # mid, the neutral assumption when the slot is unknown. That Mid is a
            # guess, so its KTC price is flagged as a stand-in, never an exact match.
            m = re.match(r"(20\d{2} [1-9]) (?:early|mid|late)$", pk)
            if m and m.group(1) in self.picks:
                return self.picks[m.group(1)]
            if f"{pk} mid" in self.picks:
                mid = self.picks[f"{pk} mid"].model_copy()
                if mid.secondary_value is not None:
                    mid.secondary_source = "approx"
                return mid
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


class ValuesClient:
    def __init__(
        self,
        url: str = VALUES_URL,
        ktc_client: Optional[KtcClient] = None,
        dealer_client: Optional[KtcClient] = None,
    ) -> None:
        self.url = url
        self.ktc_client = ktc_client or dealer_client or KtcClient()

    @property
    def dealer_client(self) -> KtcClient:
        return self.ktc_client

    @dealer_client.setter
    def dealer_client(self, client: KtcClient) -> None:
        self.ktc_client = client

    def fetch(
        self,
        fmt: Format,
        include_secondary: bool = True,
        include_ktc: bool = True,
        fresh: bool = False,
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
        secondary_map: Dict[str, int] = {}
        should_include = include_secondary and include_ktc
        if should_include:
            try:
                secondary_map = self.ktc_client.fetch_values(fmt, fresh=fresh) or {}
            except Exception:
                secondary_map = {}

        def meta(attr: str, kind: type) -> object:
            v = getattr(self.ktc_client, attr, None) if should_include else None
            return v if isinstance(v, kind) else None

        approx = meta("last_approx_keys", set) or set()
        assets = [_asset_from_entry(e, secondary_map=secondary_map, approx_keys=approx)  # type: ignore[arg-type]
                  for e in (data if isinstance(data, list) else [])]
        return ValueBook(
            assets,
            secondary_top=meta("last_top", int) if secondary_map else None,  # type: ignore[arg-type]
            fmt=fmt,
            fetched_at=fetched_at,
            secondary_fetched_at=meta("last_fetched_at", float),  # type: ignore[arg-type]
            secondary_version=meta("last_version", str),  # type: ignore[arg-type]
            secondary_html=(meta("last_html", str) or "") if secondary_map else "",  # type: ignore[arg-type]
            secondary_map=secondary_map,
        )

