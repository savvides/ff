"""Shared data models - the contract between modules.

Kept deliberately small. `Asset` is the unit of value: it covers both rostered
players and draft picks, because in dynasty a trade is a basket of both.
"""

from __future__ import annotations

from typing import Dict, List, Optional

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


class Asset(BaseModel):
    """A tradeable thing: a player or a draft pick, with its dynasty value."""

    id: str  # sleeper_id for players, a normalized label for picks ("2027 1st")
    name: str
    kind: str = "player"  # "player" | "pick"
    position: Optional[str] = None  # QB/RB/WR/TE for players, "PICK" for picks
    team: Optional[str] = None
    age: Optional[float] = None
    value: int = 0  # FantasyCalc dynasty value (0 if unvalued)
    overall_rank: Optional[int] = None
    position_rank: Optional[int] = None
    trend_30day: Optional[int] = None  # 30-day value change (+/-)
    redraft_value: Optional[int] = None  # win-now value, for buy-low/sell-high

    @property
    def is_pick(self) -> bool:
        return self.kind == "pick"


class Roster(BaseModel):
    """A team in the league, as Sleeper reports it (before valuation)."""

    roster_id: int
    owner_id: Optional[str] = None
    team_name: str = "Unknown"
    player_ids: List[str] = Field(default_factory=list)
    starters: List[str] = Field(default_factory=list)
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


class TradeSide(BaseModel):
    assets: List[Asset] = Field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(a.value for a in self.assets)


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

    def winner(self) -> str:
        if self.delta == 0:
            return "even"
        return self.label_a if self.delta > 0 else self.label_b

    def is_fair(self, threshold_pct: float = 5.0) -> bool:
        return self.pct_diff <= threshold_pct


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
