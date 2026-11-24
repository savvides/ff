"""Orchestration helper combining multi-source fetch with pure news analysis."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Sequence

from ff.analysis.news import DecisionType, build_news_review, build_player_brief
from ff.contracts import NewsReview, PlayerNewsBrief
from ff.news.client import NewsClient


def review_players(
    player_ids: Sequence[str],
    players_meta: Dict[str, Any],
    decision: Literal["start", "trade", "drop", "waiver", "lookup"],
    *,
    news_client: Optional[NewsClient] = None,
    as_of: Optional[datetime] = None,
) -> NewsReview:
    """Fetch multi-source news for unique player IDs and build a flagged NewsReview."""
    now = as_of or datetime.now(timezone.utc)
    seen: set[str] = set()
    clean_ids: List[str] = []
    for raw_id in player_ids:
        pid = str(raw_id)
        if not pid or pid == "0" or pid.startswith("pick_") or pid in seen:
            continue
        if pid not in players_meta:
            continue
        seen.add(pid)
        clean_ids.append(pid)

    client = news_client or NewsClient()
    fetched = client.fetch_for_players(clean_ids, players_meta)

    briefs: List[PlayerNewsBrief] = []
    for pid in clean_ids:
        items, feeds = fetched.get(pid, ([], []))
        meta = players_meta.get(pid) or {}
        briefs.append(build_player_brief(pid, meta, items, feeds, now))

    typed_decision: DecisionType = decision
    return build_news_review(typed_decision, briefs, now)
