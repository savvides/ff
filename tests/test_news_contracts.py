from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from ff.contracts import FeedStatus, NewsFlag, NewsItem, NewsReview, PlayerNewsBrief
from ff.core.http import _atomic_write


def test_news_item_provider_default_and_from_payload():
    item = NewsItem.from_payload(
        {"source": "RotoWire", "published": 1700000000000, "metadata": {"title": "Healthy"}}
    )
    assert item.provider == "sleeper"
    assert item.title == "Healthy"


def test_news_review_contract_shapes():
    flag = NewsFlag(
        code="INJURY",
        severity="high",
        label="Injury",
        reason="Ruled out",
        headline="Player ruled out for Sunday",
        published_date="2026-11-23",
    )
    feed = FeedStatus(provider="espn", ok=True, item_count=1)
    brief = PlayerNewsBrief(
        player_id="1234",
        player_name="Test Player",
        position="WR",
        team="KC",
        injury_status="Out",
        items=[
            NewsItem(
                provider="espn",
                source="ESPN",
                title="Player ruled out for Sunday",
                published=1700000000000,
            )
        ],
        flags=[flag],
        feeds=[feed],
        warnings=["Test warning"],
    )
    review = NewsReview(
        decision="start",
        as_of=datetime(2026, 11, 24, tzinfo=timezone.utc),
        briefs=[brief],
        degraded_feeds=[],
        warnings=["Test warning"],
    )
    assert review.briefs[0].flags[0].code == "INJURY"


def test_atomic_write_concurrent_threads(tmp_path):
    target = tmp_path / "shared.json"
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_atomic_write, target, f'{{"n": {i}}}') for i in range(40)]
        for fut in futures:
            fut.result()
    assert target.exists()
