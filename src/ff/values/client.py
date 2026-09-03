"""FantasyCalc values + the resolvers that turn user input into priced Assets.

The hard part is not the HTTP call (one GET) - it is matching:
  * a Sleeper roster's player_ids -> values  (exact, via sleeperId)
  * a human-typed "Jahmyr Gibbs"  -> a value (fuzzy, via normalized name)
  * a human-typed "2027 1st"      -> a pick value (canonicalized pick label)
"""

from __future__ import annotations

import difflib
import re
from typing import Any, Dict, List, Optional

from ff.contracts import Asset, Format
from ff.core.http import get_json
from ff.values.ktc import KtcClient
from ff.values.normalize import normalize_name, normalize_pick


VALUES_URL = "https://api.fantasycalc.com/values/current"
VALUES_TTL = 6 * 3600  # values drift slowly; refresh a few times a day


def _asset_from_entry(
    entry: dict,
    secondary_map: Optional[Dict[str, int]] = None,
    dealer_map: Optional[Dict[str, int]] = None,
    ktc_map: Optional[Dict[str, int]] = None,
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
    if sec_map:
        if is_pick:
            norm_pk = normalize_pick(name)
            if norm_pk and norm_pk in sec_map:
                sec_val = sec_map[norm_pk]
            elif ident in sec_map:
                sec_val = sec_map[ident]
        else:
            sleeper_id = p.get("sleeperId")
            norm_name = normalize_name(name)
            if sleeper_id is not None and str(sleeper_id) in sec_map:
                sec_val = sec_map[str(sleeper_id)]
            elif norm_name in sec_map:
                sec_val = sec_map[norm_name]
            elif ident in sec_map:
                sec_val = sec_map[ident]

    return Asset(
        id=ident,
        name=name,
        kind="pick" if is_pick else "player",
        position=position,
        team=p.get("maybeTeam"),
        age=p.get("maybeAge"),
        value=int(entry.get("value", 0) or 0),
        secondary_value=sec_val,
        overall_rank=entry.get("overallRank"),
        position_rank=entry.get("positionRank"),
        trend_30day=entry.get("trend30Day"),
        redraft_value=int(entry.get("redraftValue", 0) or 0) or None,
    )



class ValueBook:
    """An indexed snapshot of FantasyCalc values for one league format."""

    def __init__(self, assets: List[Asset]) -> None:
        self.assets = assets
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
            # mid, the neutral assumption when the slot is unknown.
            m = re.match(r"(20\d{2} [1-9]) (?:early|mid|late)$", pk)
            if m and m.group(1) in self.picks:
                return self.picks[m.group(1)]
            if f"{pk} mid" in self.picks:
                return self.picks[f"{pk} mid"]
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
    ) -> ValueBook:
        data = get_json(self.url, params=fmt.fantasycalc_params(), ttl=VALUES_TTL)
        secondary_map: Dict[str, int] = {}
        should_include = include_secondary and include_ktc
        if should_include:
            try:
                secondary_map = self.ktc_client.fetch_values(fmt) or {}
            except Exception:
                secondary_map = {}
        return ValueBook([_asset_from_entry(e, secondary_map=secondary_map) for e in (data if isinstance(data, list) else [])])

