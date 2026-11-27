from datetime import datetime, timezone

from ff.contracts import FeedStatus, NewsFlag, NewsItem, NewsReview, PlayerNewsBrief
from ff.qa.validators import validate_news_review


def test_validate_news_review_checks_fields_flags_and_degradation():
    as_of = datetime(2026, 11, 24, tzinfo=timezone.utc)
    bad = NewsReview(
        decision="start",
        as_of=as_of,
        briefs=[
            PlayerNewsBrief(
                player_id="1",
                player_name="Player",
                items=[NewsItem(provider="", source="ESPN", title="Headline")],
                flags=[
                    NewsFlag(
                        code="INJURY",
                        severity="high",
                        label="Injury",
                        reason="Out",
                        headline="Missing headline",
                        published_date="2026-11-24",
                    )
                ],
                feeds=[FeedStatus(provider="rss", ok=False, error="timeout")],
                warnings=[],
            )
        ],
        degraded_feeds=[],
        warnings=[],
    )
    checks = validate_news_review(bad)
    failed = {c.name for c in checks if not c.passed}
    assert "News Items Integrity" in failed
    assert "News Flags Citations" in failed
    assert "News Degradation Consistency" in failed


def test_validate_news_review_rejects_headline_mention_as_degradation_warning():
    as_of = datetime(2026, 11, 24, tzinfo=timezone.utc)
    review = NewsReview(
        decision="start",
        as_of=as_of,
        briefs=[
            PlayerNewsBrief(
                player_id="1",
                player_name="Star WR",
                items=[NewsItem(provider="sleeper", source="RotoWire", title="ESPN reports Star WR practiced")],
                flags=[],
                feeds=[FeedStatus(provider="espn", ok=False, error="500")],
                warnings=[],
            )
        ],
        degraded_feeds=["espn"],
        warnings=["Start check — Star WR (BREAKING): ESPN reports Star WR practiced"],
    )
    failed = {c.name for c in validate_news_review(review) if not c.passed}
    assert "News Degradation Consistency" in failed


def test_validate_news_review_rejects_substring_provider_in_degradation_warning():
    as_of = datetime(2026, 11, 24, tzinfo=timezone.utc)
    review = NewsReview(
        decision="start",
        as_of=as_of,
        briefs=[
            PlayerNewsBrief(
                player_id="1",
                player_name="Star WR",
                items=[],
                flags=[],
                feeds=[FeedStatus(provider="espn", ok=False, error="500")],
                warnings=[],
            )
        ],
        degraded_feeds=["espn"],
        warnings=["News feed(s) degraded or unreachable: espn_rss. Showing available sources."],
    )
    failed = {c.name for c in validate_news_review(review) if not c.passed}
    assert "News Degradation Consistency" in failed


def test_validate_news_review_passes_for_valid_degraded_review():
    from ff.analysis.news import build_news_review, build_player_brief

    as_of = datetime(2026, 11, 24, tzinfo=timezone.utc)
    brief = build_player_brief(
        "1",
        {"full_name": "Star WR"},
        [],
        [
            FeedStatus(provider="sleeper", ok=True, item_count=0),
            FeedStatus(provider="espn", ok=False, error="500"),
            FeedStatus(provider="rss", ok=True, item_count=0),
        ],
        as_of,
    )
    review = build_news_review("start", [brief], as_of)
    assert all(c.passed for c in validate_news_review(review))
