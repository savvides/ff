"""Pure news merging, deduplication, deterministic flagging, and decision warnings."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional, Sequence, Set, Tuple
from urllib.parse import urlsplit

from ff.contracts import FeedStatus, NewsFlag, NewsItem, NewsReview, PlayerNewsBrief

DecisionType = Literal["start", "trade", "drop", "waiver", "lookup"]

_STOPWORDS: Set[str] = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "was",
    "were",
    "with",
}

_MAX_ITEMS_PER_PLAYER = 5
_LOOKBACK_DAYS = 14
_DEDUPE_WINDOW_MS = 24 * 3600 * 1000

_SIGNAL_RULES: Tuple[
    Tuple[
        Literal["INJURY", "DISCIPLINE", "TRANSACTION", "ROLE_CHANGE"],
        Literal["high", "medium"],
        str,
        Tuple[str, ...],
    ],
    ...,
] = (
    (
        "INJURY",
        "high",
        "Injury (High)",
        (
            "ruled out",
            "doubtful",
            "dnp",
            "did not practice",
            "ir",
            "injured reserve",
            "surgery",
            "torn",
            "concussion",
            "season-ending",
        ),
    ),
    (
        "INJURY",
        "medium",
        "Injury (Monitor)",
        ("questionable", "limited", "day-to-day", "injury"),
    ),
    (
        "DISCIPLINE",
        "high",
        "Discipline",
        ("suspended", "suspension", "exempt list", "arrested"),
    ),
    (
        "TRANSACTION",
        "high",
        "Transaction",
        (
            "traded",
            "released",
            "waived",
            "cut",
            "signed",
            "claimed",
            "activated",
            "designated to return",
        ),
    ),
    (
        "ROLE_CHANGE",
        "high",
        "Role Change",
        ("benched", "demoted", "healthy scratch", "inactive", "named starter", "promoted"),
    ),
    (
        "ROLE_CHANGE",
        "medium",
        "Role Watch",
        ("elevated", "lead back", "workhorse", "snap share", "depth chart"),
    ),
)

_COMPILED_RULES = [
    (
        code,
        severity,
        label,
        [(kw, re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE)) for kw in keywords],
    )
    for code, severity, label, keywords in _SIGNAL_RULES
]

_NEGATIVE_ROLE_KWS = {"benched", "demoted", "healthy scratch", "inactive"}
_POSITIVE_ROLE_KWS = {"named starter", "promoted", "elevated", "lead back"}
_POSITIVE_TX_KWS = {"signed", "traded", "activated", "designated to return"}


def canonical_url(url: Optional[str]) -> Optional[str]:
    """Normalize a URL by stripping scheme, www., query params, and trailing slash."""
    if not url:
        return None
    raw = url.strip()
    if not raw:
        return None
    parts = urlsplit(raw)
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/")
    if not host and not path:
        return None
    return f"{host}{path}"


def _norm_tokens(title: str) -> Tuple[str, Set[str]]:
    cleaned = re.sub(r"[^a-z0-9\s]", " ", title.lower())
    tokens = [tok for tok in cleaned.split() if tok and tok not in _STOPWORDS]
    return " ".join(tokens), set(tokens)


def _richness(item: NewsItem) -> Tuple[int, int, int]:
    return (
        1 if item.published else 0,
        1 if item.url else 0,
        len(item.description or "") + len(item.analysis or ""),
    )


def _titles_similar(a: NewsItem, b: NewsItem) -> bool:
    if a.published and b.published and abs(a.published - b.published) > _DEDUPE_WINDOW_MS:
        return False
    norm_a, set_a = _norm_tokens(a.title)
    norm_b, set_b = _norm_tokens(b.title)
    if not norm_a or not norm_b:
        return False
    if norm_a in norm_b or norm_b in norm_a:
        return True
    union = set_a | set_b
    if not union:
        return False
    return (len(set_a & set_b) / len(union)) >= 0.65


def _pick_richer(existing: NewsItem, candidate: NewsItem) -> NewsItem:
    return candidate if _richness(candidate) > _richness(existing) else existing


def dedupe_news(items: Sequence[NewsItem]) -> List[NewsItem]:
    """Collapse duplicate headlines across sources and sort newest-first (undated last)."""
    by_url: Dict[str, NewsItem] = {}
    no_url_items: List[NewsItem] = []

    for item in items:
        c_url = canonical_url(item.url)
        if c_url:
            if c_url in by_url:
                by_url[c_url] = _pick_richer(by_url[c_url], item)
            else:
                by_url[c_url] = item
        else:
            no_url_items.append(item)

    merged: List[NewsItem] = []
    for item in list(by_url.values()) + no_url_items:
        matched_idx: Optional[int] = None
        for idx, existing in enumerate(merged):
            if _titles_similar(existing, item):
                matched_idx = idx
                break
        if matched_idx is not None:
            merged[matched_idx] = _pick_richer(merged[matched_idx], item)
        else:
            merged.append(item)

    return sorted(merged, key=lambda n: (n.published is not None, n.published or 0), reverse=True)


def _published_dt(item: NewsItem) -> Optional[datetime]:
    if not item.published:
        return None
    return datetime.fromtimestamp(item.published / 1000, tz=timezone.utc)


def extract_flags(items: Sequence[NewsItem], as_of: datetime) -> List[NewsFlag]:
    """Derive deterministic recency and content signal flags within the 14-day window."""
    as_of_utc = as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
    cutoff = as_of_utc - timedelta(days=_LOOKBACK_DAYS)
    recent_items: List[Tuple[NewsItem, datetime]] = []
    for item in items:
        dt = _published_dt(item)
        if dt is not None and cutoff <= dt <= as_of_utc + timedelta(hours=1):
            recent_items.append((item, dt))

    recent_items.sort(key=lambda pair: pair[1], reverse=True)
    flags: List[NewsFlag] = []

    if recent_items:
        newest, newest_dt = recent_items[0]
        age = as_of_utc - newest_dt
        if age < timedelta(hours=24):
            flags.append(
                NewsFlag(
                    code="BREAKING",
                    severity="high",
                    label="Breaking (<24h)",
                    reason="Published within 24 hours",
                    headline=newest.title,
                    published_date=newest.published_date,
                )
            )
        elif age < timedelta(hours=72):
            flags.append(
                NewsFlag(
                    code="RECENT",
                    severity="info",
                    label="Recent (<72h)",
                    reason="Published within 72 hours",
                    headline=newest.title,
                    published_date=newest.published_date,
                )
            )

    seen_codes: Set[str] = set()
    for code, severity, label, patterns in _COMPILED_RULES:
        if code in seen_codes:
            continue
        for item, _ in recent_items:
            text = f"{item.title} {item.description}".strip()
            matched = [kw for kw, rx in patterns if rx.search(text)]
            if matched:
                seen_codes.add(code)
                flags.append(
                    NewsFlag(
                        code=code,
                        severity=severity,
                        label=label,
                        reason=f"Matched keyword(s): {', '.join(matched)}",
                        headline=item.title,
                        published_date=item.published_date,
                    )
                )
                break

    return flags


def build_player_brief(
    player_id: str,
    player_meta: Dict[str, Any],
    items: Sequence[NewsItem],
    feeds: Sequence[FeedStatus],
    as_of: datetime,
) -> PlayerNewsBrief:
    """Build a deduplicated, flagged PlayerNewsBrief for one player."""
    first = player_meta.get("first_name") or ""
    last = player_meta.get("last_name") or ""
    name = (
        player_meta.get("full_name")
        or " ".join(part for part in (first, last) if part)
        or player_id
    )
    deduped = dedupe_news(items)[:_MAX_ITEMS_PER_PLAYER]
    flags = extract_flags(deduped, as_of)
    warnings: List[str] = []
    if feeds and all(not f.ok for f in feeds):
        warnings.append(f"{name}: news could not be verified (all feeds failed)")

    return PlayerNewsBrief(
        player_id=player_id,
        player_name=name,
        position=player_meta.get("position"),
        team=player_meta.get("team"),
        injury_status=player_meta.get("injury_status"),
        items=deduped,
        flags=flags,
        feeds=list(feeds),
        warnings=warnings,
    )


def _flag_keywords(flag: NewsFlag) -> Set[str]:
    prefix = "Matched keyword(s): "
    if flag.reason.startswith(prefix):
        return {part.strip().lower() for part in flag.reason[len(prefix) :].split(",")}
    return set()


def _decision_warnings_for_brief(decision: DecisionType, brief: PlayerNewsBrief) -> List[str]:
    out: List[str] = list(brief.warnings)
    codes = {f.code: f for f in brief.flags}

    if decision == "start":
        role = codes.get("ROLE_CHANGE")
        neg_role = role is not None and bool(_flag_keywords(role) & _NEGATIVE_ROLE_KWS)
        if any(c in codes for c in ("BREAKING", "INJURY", "DISCIPLINE")) or neg_role:
            reasons = [f.code for f in brief.flags if f.code in {"BREAKING", "INJURY", "DISCIPLINE"} or (f.code == "ROLE_CHANGE" and neg_role)]
            headline = brief.flags[0].headline if brief.flags else ""
            out.append(f"Start check — {brief.player_name} ({', '.join(reasons)}): {headline}")

    elif decision == "trade":
        active = [f.code for f in brief.flags if f.code in {"BREAKING", "INJURY", "DISCIPLINE", "TRANSACTION", "ROLE_CHANGE"}]
        if active:
            headline = next((f.headline for f in brief.flags if f.code in active), "")
            out.append(
                f"Trade check — {brief.player_name} ({', '.join(active)}): market values may lag breaking news — {headline}"
            )

    elif decision == "drop":
        role = codes.get("ROLE_CHANGE")
        tx = codes.get("TRANSACTION")
        pos_role = role is not None and bool(_flag_keywords(role) & _POSITIVE_ROLE_KWS)
        pos_tx = tx is not None and bool(_flag_keywords(tx) & _POSITIVE_TX_KWS)
        if "BREAKING" in codes or pos_role or pos_tx:
            reasons = [c for c in ("BREAKING", "ROLE_CHANGE", "TRANSACTION") if (c == "BREAKING" and c in codes) or (c == "ROLE_CHANGE" and pos_role) or (c == "TRANSACTION" and pos_tx)]
            headline = brief.flags[0].headline if brief.flags else ""
            out.append(
                f"Drop check — {brief.player_name} ({', '.join(reasons)}): review before dropping — {headline}"
            )

    elif decision == "waiver":
        opp = [f.code for f in brief.flags if f.code in {"ROLE_CHANGE", "TRANSACTION"}]
        caution = [f.code for f in brief.flags if f.code in {"INJURY", "DISCIPLINE"}]
        if opp:
            headline = next((f.headline for f in brief.flags if f.code in opp), "")
            out.append(f"Waiver opportunity — {brief.player_name} ({', '.join(opp)}): {headline}")
        if caution:
            headline = next((f.headline for f in brief.flags if f.code in caution), "")
            out.append(
                f"Waiver caution — {brief.player_name} ({', '.join(caution)}): verify before spending FAAB — {headline}"
            )

    return out


def build_news_review(
    decision: DecisionType,
    briefs: Sequence[PlayerNewsBrief],
    as_of: datetime,
) -> NewsReview:
    """Aggregate player briefs, degraded feeds, and decision-contextual warnings."""
    degraded: List[str] = []
    seen_degraded: Set[str] = set()
    for brief in briefs:
        for feed in brief.feeds:
            if not feed.ok and feed.provider not in seen_degraded:
                seen_degraded.add(feed.provider)
                degraded.append(feed.provider)

    warnings: List[str] = []
    if degraded:
        warnings.append(
            f"News feed(s) degraded or unreachable: {', '.join(degraded)}. Showing available sources."
        )

    for brief in briefs:
        for w in _decision_warnings_for_brief(decision, brief):
            if w not in warnings:
                warnings.append(w)

    return NewsReview(
        decision=decision,
        as_of=as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc),
        briefs=list(briefs),
        degraded_feeds=degraded,
        warnings=warnings,
    )
