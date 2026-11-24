"""Multi-source news I/O client (Sleeper, ESPN, and free NFL RSS feeds)."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests

from ff.contracts import FeedStatus, NewsItem
from ff.core.http import get_json, get_text

NEWS_TTL = 300.0
NEWS_TIMEOUT = 10
MAX_WORKERS = 6

SLEEPER_PLAYER_NEWS_URL = "https://api.sleeper.com/players/nfl/{pid}/news"
ESPN_NFL_NEWS_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news"
RSS_FEEDS: Tuple[Tuple[str, str], ...] = (
    ("espn_rss", "https://www.espn.com/espn/rss/nfl/news"),
    ("pft_rss", "https://www.nbcsports.com/nfl/profootballtalk.rss"),
)


def _norm_text(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\s]", "", value.lower())
    return " ".join(cleaned.split())


def _player_full_name(meta: Dict[str, Any], pid: str) -> str:
    first = meta.get("first_name") or ""
    last = meta.get("last_name") or ""
    return (
        meta.get("full_name")
        or " ".join(part for part in (first, last) if part)
        or pid
    )


def _parse_iso_ms(raw: Optional[str]) -> Optional[int]:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError):
        return None


def _parse_rfc822_ms(raw: Optional[str]) -> Optional[int]:
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw.strip())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError):
        return None


def _espn_article_to_item(article: Dict[str, Any]) -> NewsItem:
    links = article.get("links") or {}
    web = links.get("web") or {}
    url = (web.get("href") or article.get("link") or "").strip() or None
    title = (article.get("headline") or article.get("title") or "").strip() or "(untitled)"
    description = (article.get("description") or "").strip()
    published = _parse_iso_ms(article.get("published") or article.get("lastModified"))
    source = (article.get("byline") or "ESPN").strip() or "ESPN"
    return NewsItem(
        provider="espn",
        published=published,
        source=source,
        title=title,
        description=description,
        url=url,
    )


def _matches_player(
    text_norm: str,
    meta: Dict[str, Any],
    pid: str,
    ambiguous_names: set[str],
) -> bool:
    name_norm = _norm_text(_player_full_name(meta, pid))
    if not name_norm or len(name_norm) < 4:
        return False
    if not re.search(rf"\b{re.escape(name_norm)}\b", text_norm):
        return False
    if name_norm in ambiguous_names:
        team = (meta.get("team") or "").lower()
        pos = (meta.get("position") or "").lower()
        team_hit = bool(team and re.search(rf"\b{re.escape(team)}\b", text_norm))
        pos_hit = bool(pos and re.search(rf"\b{re.escape(pos)}\b", text_norm))
        return team_hit or pos_hit
    return True


def _ambiguous_name_set(players_meta: Dict[str, Any]) -> set[str]:
    counts: Dict[str, int] = {}
    for pid, meta in players_meta.items():
        if not isinstance(meta, dict):
            continue
        norm = _norm_text(_player_full_name(meta, str(pid)))
        if norm:
            counts[norm] = counts.get(norm, 0) + 1
    return {name for name, count in counts.items() if count > 1}


class NewsClient:
    """Fetches and normalizes player news from Sleeper, ESPN, and NFL RSS feeds."""

    def fetch_sleeper(self, pid: str) -> Tuple[List[NewsItem], FeedStatus]:
        url = SLEEPER_PLAYER_NEWS_URL.format(pid=pid)
        try:
            payload = get_json(url, ttl=NEWS_TTL, timeout=NEWS_TIMEOUT) or []
            if not isinstance(payload, list):
                raise ValueError("Unexpected Sleeper news payload shape")
            items = [
                NewsItem.from_payload({**row, "provider": "sleeper"})
                for row in payload
                if isinstance(row, dict)
            ]
            return items, FeedStatus(provider="sleeper", ok=True, item_count=len(items))
        except (requests.RequestException, ValueError, TypeError) as exc:
            return [], FeedStatus(provider="sleeper", ok=False, error=str(exc))

    def fetch_espn(
        self,
        pid: str,
        meta: Dict[str, Any],
        league_espn: Optional[Tuple[List[Dict[str, Any]], Optional[str]]] = None,
        ambiguous_names: Optional[set[str]] = None,
    ) -> Tuple[List[NewsItem], FeedStatus]:
        espn_id = meta.get("espn_id")
        if espn_id:
            try:
                data = get_json(
                    ESPN_NFL_NEWS_URL,
                    params={"athlete": str(espn_id), "limit": 10},
                    ttl=NEWS_TTL,
                    timeout=NEWS_TIMEOUT,
                )
                articles = (data or {}).get("articles") or []
                items = [_espn_article_to_item(a) for a in articles if isinstance(a, dict)]
                return items, FeedStatus(provider="espn", ok=True, item_count=len(items))
            except (requests.RequestException, ValueError, TypeError) as exc:
                return [], FeedStatus(provider="espn", ok=False, error=str(exc))

        if league_espn is None:
            articles, err = self._fetch_espn_league_feed()
        else:
            articles, err = league_espn
        if err is not None:
            return [], FeedStatus(provider="espn", ok=False, error=err)

        ambiguous = ambiguous_names or set()
        items: List[NewsItem] = []
        for article in articles:
            if not isinstance(article, dict):
                continue
            item = _espn_article_to_item(article)
            text_norm = _norm_text(f"{item.title} {item.description}")
            if _matches_player(text_norm, meta, pid, ambiguous):
                items.append(item)
        return items, FeedStatus(provider="espn", ok=True, item_count=len(items))

    def _fetch_espn_league_feed(self) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        try:
            data = get_json(
                ESPN_NFL_NEWS_URL,
                params={"limit": 50},
                ttl=NEWS_TTL,
                timeout=NEWS_TIMEOUT,
            )
            articles = (data or {}).get("articles") or []
            if not isinstance(articles, list):
                return [], "Unexpected ESPN news payload shape"
            return articles, None
        except (requests.RequestException, ValueError, TypeError) as exc:
            return [], str(exc)

    def fetch_rss(self) -> Tuple[List[Tuple[NewsItem, str]], FeedStatus]:
        """Fetch configured NFL RSS feeds and return (NewsItem, normalized_text) pairs."""
        parsed_items: List[Tuple[NewsItem, str]] = []
        errors: List[str] = []

        for source_name, url in RSS_FEEDS:
            try:
                body = get_text(url, ttl=NEWS_TTL, timeout=NEWS_TIMEOUT)
                root = ET.fromstring(body)
                label = "ESPN" if source_name == "espn_rss" else "ProFootballTalk"
                for elem in root.findall(".//item"):
                    title = (elem.findtext("title") or "").strip() or "(untitled)"
                    desc = (elem.findtext("description") or "").strip()
                    link = (elem.findtext("link") or "").strip() or None
                    pub_ms = _parse_rfc822_ms(elem.findtext("pubDate"))
                    item = NewsItem(
                        provider="rss",
                        published=pub_ms,
                        source=label,
                        title=title,
                        description=desc,
                        url=link,
                    )
                    parsed_items.append((item, _norm_text(f"{title} {desc}")))
            except (requests.RequestException, ET.ParseError, ValueError) as exc:
                errors.append(f"{source_name}: {exc}")

        if errors:
            return parsed_items, FeedStatus(
                provider="rss",
                ok=False,
                item_count=len(parsed_items),
                error="; ".join(errors),
            )
        return parsed_items, FeedStatus(provider="rss", ok=True, item_count=len(parsed_items))

    def fetch_for_players(
        self,
        player_ids: Sequence[str],
        players_meta: Dict[str, Any],
    ) -> Dict[str, Tuple[List[NewsItem], List[FeedStatus]]]:
        """Fetch Sleeper, ESPN, and RSS news for the given players with bounded concurrency."""
        if not player_ids:
            return {}

        ambiguous = _ambiguous_name_set(players_meta)
        rss_items, rss_status = self.fetch_rss()

        needs_league_espn = any(
            not (players_meta.get(pid) or {}).get("espn_id") for pid in player_ids
        )
        league_espn: Optional[Tuple[List[Dict[str, Any]], Optional[str]]] = (
            self._fetch_espn_league_feed() if needs_league_espn else None
        )

        def _fetch_one(pid: str) -> Tuple[str, List[NewsItem], List[FeedStatus]]:
            meta = players_meta.get(pid) or {}
            sleeper_items, sleeper_status = self.fetch_sleeper(pid)
            espn_items, espn_status = self.fetch_espn(
                pid, meta, league_espn=league_espn, ambiguous_names=ambiguous
            )
            matched_rss = [
                item
                for item, text_norm in rss_items
                if _matches_player(text_norm, meta, pid, ambiguous)
            ]
            player_rss_status = FeedStatus(
                provider="rss",
                ok=rss_status.ok,
                item_count=len(matched_rss),
                error=rss_status.error,
            )
            return (
                pid,
                sleeper_items + espn_items + matched_rss,
                [sleeper_status, espn_status, player_rss_status],
            )

        results: Dict[str, Tuple[List[NewsItem], List[FeedStatus]]] = {}
        workers = min(MAX_WORKERS, max(1, len(player_ids)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for pid, items, statuses in pool.map(_fetch_one, player_ids):
                results[pid] = (items, statuses)
        return results
