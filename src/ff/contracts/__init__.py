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
    FabClaim,
    FeedStatus,
    Format,
    FuturePick,
    Lineup,
    LineupSlot,
    NewsFlag,
    NewsItem,
    NewsReview,
    OfferVerdict,
    PlayerNewsBrief,
    PositionStanding,
    Roster,
    RosterAudit,
    RosterSlot,
    RosterValuation,
    SeasonPhase,
    StandingProjection,
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
    "FeedStatus",
    "Format",
    "NewsFlag",
    "NewsItem",
    "NewsReview",
    "OfferVerdict",
    "PlayerNewsBrief",
    "Roster",
    "RosterSlot",
    "RosterAudit",
    "RosterValuation",
    "SeasonPhase",
    "StandingProjection",
    "TradeSide",
    "TradeEvaluation",
    "WaiverTarget",
    "LineupSlot",
    "Lineup",
    "DraftPickInfo",
    "FabClaim",
    "FuturePick",
    "TeamPicks",
    "TeamWindow",
    "PositionStanding",
    "TeamContext",
    "DraftFit",
]

