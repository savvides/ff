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
