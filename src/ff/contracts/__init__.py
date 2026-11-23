"""The shared contract: the only types that cross module boundaries.

Every module (`sleeper`, `values`, `analysis`, `cli`) imports these and nothing
from each other's internals. Change a model here and you have made a contract
change - update both sides.
"""

from __future__ import annotations

from ff.contracts.models import (
    ArbitrageMover,
    Asset,
    AssetDurationFlag,
    DecisionFilter,
    DraftFit,
    DraftPickInfo,
    Format,
    FuturePick,
    Lineup,
    LineupSlot,
    NewsItem,
    OfferVerdict,
    PositionStanding,
    Roster,
    RosterAudit,
    RosterSlot,
    RosterValuation,
    SeasonPhase,
    TeamContext,
    TeamPicks,
    TeamWindow,
    TradeEvaluation,
    TradeSide,
    WaiverTarget,
)

__all__ = [
    "ArbitrageMover",
    "Asset",
    "AssetDurationFlag",
    "DecisionFilter",
    "Format",
    "NewsItem",
    "OfferVerdict",
    "Roster",
    "RosterSlot",
    "RosterAudit",
    "RosterValuation",
    "SeasonPhase",
    "TradeSide",
    "TradeEvaluation",
    "WaiverTarget",
    "LineupSlot",
    "Lineup",
    "DraftPickInfo",
    "FuturePick",
    "TeamPicks",
    "TeamWindow",
    "PositionStanding",
    "TeamContext",
    "DraftFit",
]

