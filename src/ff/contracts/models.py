"""Shared data models - the contract between modules.

Kept deliberately small. `Asset` is the unit of value: it covers both rostered
players and draft picks, because in dynasty a trade is a basket of both.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class Format(BaseModel):
    """A league's scoring/roster format - everything needed to ask FantasyCalc
    for the *right* values. Derived from Sleeper's own league settings so it is
    always correct for the user's league (never guessed)."""

    is_dynasty: bool = True
    superflex: bool = False
    num_qbs: int = 1
    num_teams: int = 12
    ppr: float = 1.0
    # Tight-end premium, detected from the league for reference only. FantasyCalc's
    # public /values/current does NOT expose a TEP param (verified: passing one is a
    # no-op), so values are not TEP-adjusted; TE values run slightly conservative in
    # TEP leagues. Surfaced in the format label so the gap is visible, never hidden.
    tep: float = 0.0

    def fantasycalc_params(self) -> Dict[str, str]:
        """Map to FantasyCalc's /values/current query params. (TEP is omitted
        because FantasyCalc does not support it; see the `tep` field note.)"""
        return {
            "isDynasty": "true" if self.is_dynasty else "false",
            "numQbs": str(self.num_qbs),
            "numTeams": str(self.num_teams),
            "ppr": str(self.ppr),
        }

    def label(self) -> str:
        kind = "Dynasty" if self.is_dynasty else "Redraft"
        qb = "Superflex" if self.superflex else "1QB"
        scoring = {1.0: "PPR", 0.5: "Half-PPR", 0.0: "Standard"}.get(self.ppr, f"{self.ppr}PPR")
        tep = f" +{self.tep:g}TEP" if self.tep else ""
        return f"{self.num_teams}-team {kind} {qb} {scoring}{tep}"


# Availability fields only Sleeper's players file supplies; FantasyCalc has none
# of them, so `Asset.fill_from_meta` only ever fills blanks.
_META_FIELDS = ("injury_status", "injury_body_part", "depth_chart_order", "status")


class Asset(BaseModel):
    """A tradeable thing: a player or a draft pick, with its dynasty value."""

    id: str  # sleeper_id for players, a normalized label for picks ("2027 1st")
    name: str
    kind: str = "player"  # "player" | "pick"
    position: Optional[str] = None  # QB/RB/WR/TE for players, "PICK" for picks
    team: Optional[str] = None
    age: Optional[float] = None
    value: int = 0  # FantasyCalc dynasty value (0 if unvalued)
    ktc_value: Optional[int] = None  # KeepTradeCut dynasty value
    overall_rank: Optional[int] = None
    position_rank: Optional[int] = None
    trend_30day: Optional[int] = None  # 30-day value change (+/-)
    redraft_value: Optional[int] = None  # win-now value, for buy-low/sell-high
    injury_status: Optional[str] = None  # Questionable, Out, IR, Doubtful, Sus
    injury_body_part: Optional[str] = None  # Foot, Knee, Hamstring, etc.
    depth_chart_order: Optional[int] = None  # 1, 2, 3...
    status: Optional[str] = None  # Active, Injured Reserve, etc.

    @property
    def is_pick(self) -> bool:
        return self.kind == "pick"

    def fill_from_meta(self, meta: Optional[Dict[str, Any]]) -> None:
        """Fill blank availability fields from a Sleeper players-file entry.

        The book prices players; only Sleeper knows whether they can play. Both
        `value_roster` and the trade resolver need that join, so it lives here -
        `contracts` is the one module they may both import from.
        """
        if not isinstance(meta, dict):
            return
        for field in _META_FIELDS:
            if getattr(self, field) is None:
                setattr(self, field, meta.get(field))
        if not self.team and meta.get("team"):
            self.team = meta.get("team")
        if self.age is None and meta.get("age"):
            self.age = meta.get("age")

    @property
    def injury_tag(self) -> str:
        """Short injury label: '[Q]', '[Q - Foot]', '[IR]', '[O]', '[D]'. Empty if healthy."""
        if self.is_pick:
            return ""
        if self.status == "Injured Reserve" or self.injury_status == "IR":
            return "[IR]"
        if not self.injury_status or self.injury_status.lower() in ("active", "healthy", "none"):
            return ""
        code = {
            "Questionable": "Q",
            "Doubtful": "D",
            "Out": "O",
            "Suspended": "SUS",
        }.get(self.injury_status, self.injury_status[:1].upper())
        if self.injury_body_part:
            return f"[{code} - {self.injury_body_part}]"
        return f"[{code}]"

    @property
    def depth_tag(self) -> str:
        """Depth chart role: 'RB1', 'WR2', 'QB1', etc."""
        if self.is_pick or not self.position or self.depth_chart_order is None:
            return ""
        return f"{self.position}{self.depth_chart_order}"

    @property
    def status_label(self) -> str:
        """Combined depth & injury status string: 'RB3 [Q - Foot]' or 'WR1' or '[IR]'."""
        parts = []
        if self.depth_tag:
            parts.append(self.depth_tag)
        if self.injury_tag:
            parts.append(self.injury_tag)
        return " ".join(parts)


class DraftPickInfo(BaseModel):
    """One draft pick a roster owns - upcoming, or already used on a player."""

    pick_no: int  # overall pick number (1-indexed)
    round: int
    slot: int  # draft slot (1..teams) the pick belongs to
    used: bool = False
    player_id: Optional[str] = None  # set once used
    player_name: Optional[str] = None
    position: Optional[str] = None


class FuturePick(BaseModel):
    """One future rookie-draft pick a roster currently owns.

    Sleeper has no per-team pick endpoint: ownership is the default endowment
    (every team owns its own pick per season/round) reconciled with the league's
    `traded_picks`. `tier` records which FantasyCalc tier priced it (early/mid/
    late, from the original team's power rank), None when only the flat round
    value existed."""

    season: str
    round: int
    original_roster_id: int
    original_team: str = ""
    acquired: bool = False  # came from another team via trade
    tier: Optional[str] = None  # "early" | "mid" | "late" | None (flat round value)
    value: int = 0

    @property
    def label(self) -> str:
        n = self.round
        if 10 <= n % 100 <= 20:  # 11th-13th, not 11st/12nd/13rd
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{self.season} {n}{suffix}"


class TeamPicks(BaseModel):
    """Every future pick one roster owns, valued - a team's draft capital."""

    roster_id: int
    team_name: str = ""
    picks: List[FuturePick] = Field(default_factory=list)

    @property
    def total_value(self) -> int:
        return sum(p.value for p in self.picks)


class Roster(BaseModel):
    """A team in the league, as Sleeper reports it (before valuation)."""

    roster_id: int
    owner_id: Optional[str] = None
    team_name: str = "Unknown"
    player_ids: List[str] = Field(default_factory=list)
    starters: List[str] = Field(default_factory=list)
    # Taxi (practice squad) and reserve (IR) are subsets of player_ids that do
    # NOT occupy an active roster slot. Empty for leagues without those pools.
    taxi: List[str] = Field(default_factory=list)
    reserve: List[str] = Field(default_factory=list)
    wins: int = 0
    losses: int = 0
    ties: int = 0
    points_for: float = 0.0


class RosterValuation(BaseModel):
    """A team's roster priced out with dynasty values."""

    roster_id: int
    team_name: str
    total_value: int = 0
    starters_value: int = 0
    by_position: Dict[str, int] = Field(default_factory=dict)
    assets: List[Asset] = Field(default_factory=list)  # sorted desc by value
    unvalued: List[str] = Field(default_factory=list)  # player_ids with no value
    power_rank: Optional[int] = None  # 1 = most valuable roster in the league


class RosterSlot(BaseModel):
    """One rostered player, categorized by where they sit, with the signals a
    roster-cleanup decision needs: value, age/experience, and taxi eligibility."""

    player_id: str
    name: str
    position: Optional[str] = None
    age: Optional[float] = None
    years_exp: Optional[int] = None
    value: int = 0
    trend_30day: Optional[int] = None
    slot: str = "BENCH"  # START | BENCH | TAXI | IR
    taxi_eligible: bool = False

    @property
    def is_active(self) -> bool:
        """Occupies a starter/bench slot (so dropping it frees active room).
        Taxi and IR players do not, which is why cutting them adds no waiver room."""
        return self.slot in ("START", "BENCH")


class RosterAudit(BaseModel):
    """A roster's capacity vs its fill, plus ranked drop and taxi-move
    suggestions - the input to a cleanup decision. Pure, deterministic."""

    team_name: str
    starter_cap: int = 0
    bench_cap: int = 0
    taxi_cap: int = 0
    ir_cap: int = 0
    slots: List[RosterSlot] = Field(default_factory=list)  # every owned player
    # Non-starters ranked worst-first (lowest value); dropping one frees an active
    # slot only if it is_active (bench), not if it is on taxi/IR.
    drop_candidates: List[RosterSlot] = Field(default_factory=list)
    # Taxi-eligible bench players (best first) that could be stashed to free an
    # active slot WITHOUT dropping anyone; capped at the open taxi slots.
    taxi_candidates: List[RosterSlot] = Field(default_factory=list)

    def _in(self, slot: str) -> List[RosterSlot]:
        return [s for s in self.slots if s.slot == slot]

    @property
    def starters(self) -> List[RosterSlot]:
        return self._in("START")

    @property
    def bench(self) -> List[RosterSlot]:
        return self._in("BENCH")

    @property
    def taxi(self) -> List[RosterSlot]:
        return self._in("TAXI")

    @property
    def ir(self) -> List[RosterSlot]:
        return self._in("IR")

    @property
    def active_count(self) -> int:
        return len(self.starters) + len(self.bench)

    @property
    def active_cap(self) -> int:
        return self.starter_cap + self.bench_cap

    @property
    def active_open(self) -> int:
        """Open active slots; negative means the roster is over the cap."""
        return self.active_cap - self.active_count

    @property
    def taxi_open(self) -> int:
        return self.taxi_cap - len(self.taxi)

    @property
    def ir_open(self) -> int:
        return self.ir_cap - len(self.ir)


class TradeSide(BaseModel):
    assets: List[Asset] = Field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(a.value for a in self.assets)

    @property
    def ktc_total(self) -> Optional[int]:
        if not any(a.ktc_value is not None for a in self.assets):
            return None
        return sum(a.ktc_value or 0 for a in self.assets)


class TradeEvaluation(BaseModel):
    """Result of analyzing a proposed trade between two sides."""

    side_a: TradeSide
    side_b: TradeSide
    label_a: str = "Side A"
    label_b: str = "Side B"

    @property
    def value_a(self) -> int:
        return self.side_a.total

    @property
    def value_b(self) -> int:
        return self.side_b.total

    @property
    def delta(self) -> int:
        """Positive => side A receives more value."""
        return self.value_a - self.value_b

    @property
    def pct_diff(self) -> float:
        """Gap as a % of the larger side (0 = even, 100 = total blowout)."""
        larger = max(self.value_a, self.value_b)
        return 0.0 if larger == 0 else abs(self.delta) / larger * 100.0

    @property
    def ktc_value_a(self) -> Optional[int]:
        return self.side_a.ktc_total

    @property
    def ktc_value_b(self) -> Optional[int]:
        return self.side_b.ktc_total

    @property
    def ktc_delta(self) -> Optional[int]:
        if self.ktc_value_a is None or self.ktc_value_b is None:
            return None
        return self.ktc_value_a - self.ktc_value_b

    @property
    def ktc_pct_diff(self) -> Optional[float]:
        if self.ktc_value_a is None or self.ktc_value_b is None:
            return None
        larger = max(self.ktc_value_a, self.ktc_value_b)
        return 0.0 if larger == 0 else abs(self.ktc_delta) / larger * 100.0

    def winner(self) -> str:
        if self.delta == 0:
            return "even"
        return self.label_a if self.delta > 0 else self.label_b

    def is_fair(self, threshold_pct: float = 5.0) -> bool:
        return self.pct_diff <= threshold_pct

    def arbitrage_label(self, threshold_pct: float = 5.0) -> Optional[str]:
        if self.ktc_delta is None or self.ktc_pct_diff is None:
            return None
        fc_fair = self.is_fair(threshold_pct)
        ktc_fair = self.ktc_pct_diff <= threshold_pct

        if fc_fair and ktc_fair:
            return "Fair"

        fc_win = self.delta > 0 and not fc_fair
        fc_loss = self.delta < 0 and not fc_fair
        ktc_win = self.ktc_delta > 0 and not ktc_fair
        ktc_loss = self.ktc_delta < 0 and not ktc_fair

        if fc_win and ktc_win:
            return "Consensus Win"
        if fc_loss and ktc_loss:
            return "Consensus Loss"
        if fc_win and (ktc_loss or ktc_fair):
            return "Value Arbitrage"
        if (fc_loss or fc_fair) and ktc_win:
            return "Hype Arbitrage"
        if fc_loss or ktc_loss:
            return "Consensus Loss"
        return "Fair"


class ArbitrageMover(BaseModel):
    """An asset with valuation discrepancies across FantasyCalc and KeepTradeCut."""

    asset: Asset
    fc_value: int = 0
    ktc_value: int = 0
    diff: int = 0  # ktc_value - fc_value
    pct_diff: float = 0.0  # abs(diff) / max(fc, ktc) * 100.0
    diff_pct: float = 0.0
    roster_id: Optional[int] = None
    team_name: Optional[str] = None
    market_bias: str = ""  # "KTC" | "FC" | "EVEN"

    def model_post_init(self, __context: Any) -> None:
        if self.fc_value == 0 and self.asset.value:
            self.fc_value = self.asset.value
        if self.ktc_value == 0 and self.asset.ktc_value:
            self.ktc_value = self.asset.ktc_value
        if self.diff == 0 and (self.ktc_value or self.fc_value):
            self.diff = self.ktc_value - self.fc_value
        if self.pct_diff == 0.0 and (self.ktc_value or self.fc_value):
            larger = max(self.fc_value, self.ktc_value)
            self.pct_diff = (abs(self.diff) / larger * 100.0) if larger > 0 else 0.0
        if self.diff_pct == 0.0 and self.pct_diff != 0.0:
            self.diff_pct = self.pct_diff
        if not self.market_bias:
            if self.diff > 0:
                self.market_bias = "KTC"
            elif self.diff < 0:
                self.market_bias = "FC"
            else:
                self.market_bias = "EVEN"


class WaiverTarget(BaseModel):
    """A trending add joined to its dynasty value and roster availability."""

    asset: Asset
    add_count: int = 0  # how many Sleeper users added in the trending window
    is_rostered: bool = False  # taken somewhere in *this* league?


class LineupSlot(BaseModel):
    """One starting slot (or a bench entry) with its projected player."""

    slot: str  # QB / RB / WR / TE / FLEX / SUPER_FLEX / BN ...
    player_id: Optional[str] = None
    name: str = "(empty)"
    position: Optional[str] = None
    points: float = 0.0


class Lineup(BaseModel):
    """An optimal starting lineup for one week plus the leftover bench."""

    slots: List[LineupSlot] = Field(default_factory=list)
    bench: List[LineupSlot] = Field(default_factory=list)
    season: str = ""
    week: int = 0
    # Starting slots the optimizer does not support (non-laminar flexes, IDP, ...).
    # Surfaced so the lineup is never silently wrong for those leagues.
    unsupported_slots: List[str] = Field(default_factory=list)

    @property
    def total(self) -> float:
        return round(sum(s.points for s in self.slots), 2)


class PositionStanding(BaseModel):
    """Where one roster stands at a position vs the league, by startable value."""

    position: str
    mine: int = 0  # this team's startable value at the position
    median: int = 0  # league median startable value at the position

    @property
    def gap(self) -> int:
        """Positive => stronger than the median team at this position."""
        return self.mine - self.median

    @property
    def is_hole(self) -> bool:
        return self.median > 0 and self.mine < self.median


class TeamContext(BaseModel):
    """A team's competitive status and positional standing - the lens a draft
    recommendation is made through."""

    status: str = "balanced"  # "contend" | "rebuild" | "balanced"
    power_rank: Optional[int] = None  # 1 = most valuable roster in the league
    num_teams: int = 12
    standings: List[PositionStanding] = Field(default_factory=list)


class DraftFit(BaseModel):
    """One available player scored for *this* team: market value (the anchor)
    adjusted by roster-fit and win-now/rebuild horizon."""

    asset: Asset
    fit_score: float = 0.0
    market_rank: int = 0  # 1-based rank by raw dynasty value among available
    marginal_starter: int = 0  # value this player adds to the starting lineup
    upgrade_tilt: float = 0.0
    horizon_tilt: float = 0.0
    standing_tilt: float = 0.0
    why: str = ""


class NewsItem(BaseModel):
    """One headline from Sleeper's per-player news feed.

    The feed is undocumented and its `metadata` block varies by source (a real
    10-item sample carried `url` on 6 and `analysis` on 7), so every field but
    the title/description pair is optional and parsing never raises.
    """

    published: Optional[int] = None  # epoch MILLISECONDS, as Sleeper sends it
    source: str = "?"
    title: str = "(untitled)"
    description: str = ""
    analysis: Optional[str] = None
    url: Optional[str] = None

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "NewsItem":
        meta = payload.get("metadata") or {}
        return cls(
            published=payload.get("published"),
            source=payload.get("source") or "?",
            title=(meta.get("title") or "").strip() or "(untitled)",
            description=(meta.get("description") or "").strip(),
            analysis=(meta.get("analysis") or "").strip() or None,
            url=(meta.get("url") or "").strip() or None,
        )

    @property
    def published_date(self) -> str:
        """YYYY-MM-DD, or '-' when the feed omitted a timestamp."""
        if not self.published:
            return "-"
        return datetime.fromtimestamp(self.published / 1000).strftime("%Y-%m-%d")
