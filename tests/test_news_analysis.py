from datetime import datetime, timedelta, timezone

from ff.analysis.news import (
    build_news_review,
    build_player_brief,
    canonical_url,
    dedupe_news,
    extract_flags,
)
from ff.contracts import FeedStatus, NewsItem


def _ts(as_of: datetime, hours_ago: float) -> int:
    return int((as_of - timedelta(hours=hours_ago)).timestamp() * 1000)


def test_canonical_url_strips_scheme_www_query_and_slash():
    assert canonical_url("https://www.espn.com/nfl/story?id=123/") == "espn.com/nfl/story"


def test_dedupe_news_collapses_url_and_title_similarity_keeps_richer_and_sorts():
    as_of = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
    items = [
        NewsItem(
            provider="rss",
            source="PFT",
            title="Justin Jefferson returns to practice Thursday",
            published=_ts(as_of, 6),
            url="https://www.nbcsports.com/story?utm=1",
        ),
        NewsItem(
            provider="sleeper",
            source="RotoWire",
            title="Justin Jefferson returns to practice Thursday",
            description="Full participant.",
            analysis="Start him.",
            published=_ts(as_of, 5),
            url="http://nbcsports.com/story/",
        ),
        NewsItem(
            provider="espn",
            source="ESPN",
            title="Justin Jefferson returns to practice",
            published=_ts(as_of, 8),
        ),
        NewsItem(provider="rss", source="PFT", title="Undated older note", published=None),
    ]
    deduped = dedupe_news(items)
    assert len(deduped) == 2
    assert deduped[0].provider == "sleeper"
    assert deduped[1].title == "Undated older note"


def test_extract_flags_window_recency_categories_and_word_boundaries():
    as_of = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
    items = [
        NewsItem(provider="espn", source="ESPN", title="Player ruled out with concussion", published=_ts(as_of, 4)),
        NewsItem(provider="sleeper", source="RotoWire", title="Suspended two games by NFL", published=_ts(as_of, 30)),
        NewsItem(provider="rss", source="PFT", title="Traded to Buffalo and named starter", published=_ts(as_of, 40)),
        NewsItem(provider="rss", source="PFT", title="Great cutback ability in any circumstance", published=_ts(as_of, 50)),
        NewsItem(provider="sleeper", source="RotoWire", title="Ruled out last month", published=_ts(as_of, 24 * 15)),
    ]
    flags = extract_flags(items, as_of)
    codes = {f.code for f in flags}
    assert {"BREAKING", "INJURY", "DISCIPLINE", "TRANSACTION", "ROLE_CHANGE"} == codes
    assert "RECENT" not in codes  # omitted when BREAKING is present

    # Word-boundary guard: "cutback" and "circumstance" must not trigger TRANSACTION or INJURY
    boundary_only = [
        NewsItem(
            provider="rss",
            source="PFT",
            title="Great cutback vision in any circumstance",
            published=_ts(as_of, 36),
        )
    ]
    b_flags = extract_flags(boundary_only, as_of)
    assert [f.code for f in b_flags] == ["RECENT"]


def test_build_news_review_contextual_warnings_and_loud_degradation():
    as_of = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
    brief_drop = build_player_brief(
        "p1",
        {"full_name": "Backup RB", "position": "RB", "team": "KC"},
        [NewsItem(provider="espn", source="ESPN", title="Named starter after injury", published=_ts(as_of, 3))],
        [
            FeedStatus(provider="sleeper", ok=True, item_count=0),
            FeedStatus(provider="espn", ok=True, item_count=1),
            FeedStatus(provider="rss", ok=False, error="timeout"),
        ],
        as_of,
    )
    brief_all_fail = build_player_brief(
        "p2",
        {"full_name": "Mystery WR", "position": "WR", "team": "NYJ"},
        [],
        [
            FeedStatus(provider="sleeper", ok=False, error="500"),
            FeedStatus(provider="espn", ok=False, error="500"),
            FeedStatus(provider="rss", ok=False, error="timeout"),
        ],
        as_of,
    )
    review = build_news_review("drop", [brief_drop, brief_all_fail], as_of)
    assert set(review.degraded_feeds) == {"sleeper", "espn", "rss"}
    assert any("review before dropping" in w.lower() for w in review.warnings)
    assert any("could not be verified" in w.lower() for w in review.warnings)


def test_start_and_drop_warnings_cite_triggering_headline_not_recent():
    as_of = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
    items = [
        NewsItem(provider="espn", source="ESPN", title="Benign media availability quote", published=_ts(as_of, 30)),
        NewsItem(provider="sleeper", source="RotoWire", title="Player ruled out with ankle injury", published=_ts(as_of, 48)),
    ]
    feeds = [FeedStatus(provider="espn", ok=True, item_count=2)]
    brief = build_player_brief("p1", {"full_name": "Star WR"}, items, feeds, as_of)
    assert brief.flags[0].code == "RECENT"
    assert brief.flags[1].code == "INJURY"

    start_rev = build_news_review("start", [brief], as_of)
    assert any("Player ruled out with ankle injury" in w for w in start_rev.warnings)
    assert not any("Benign media availability quote" in w for w in start_rev.warnings)

    drop_items = [
        NewsItem(provider="espn", source="ESPN", title="Benign media availability quote", published=_ts(as_of, 30)),
        NewsItem(provider="sleeper", source="RotoWire", title="Backup named starter for Week 12", published=_ts(as_of, 48)),
    ]
    drop_brief = build_player_brief("p2", {"full_name": "Backup RB"}, drop_items, feeds, as_of)
    drop_rev = build_news_review("drop", [drop_brief], as_of)
    assert any("Backup named starter for Week 12" in w for w in drop_rev.warnings)
    assert not any("Benign media availability quote" in w for w in drop_rev.warnings)


def test_dedupe_news_does_not_merge_prefix_substring_words():
    as_of = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
    items = [
        NewsItem(provider="espn", source="ESPN", title="Jefferson out", published=_ts(as_of, 4)),
        NewsItem(provider="rss", source="PFT", title="Jefferson outlook improves after bye", published=_ts(as_of, 6)),
    ]
    deduped = dedupe_news(items)
    assert len(deduped) == 2


def test_multi_keyword_flags_across_items_and_tiers_preserve_start_and_drop_warnings():
    as_of = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
    feeds = [FeedStatus(provider="sleeper", ok=True, item_count=2)]

    # Newer "named starter" must NOT hide older "benched" for start decision
    start_items = [
        NewsItem(provider="sleeper", source="RotoWire", title="Player named starter earlier", published=_ts(as_of, 30)),
        NewsItem(provider="sleeper", source="RotoWire", title="Player benched for disciplinary reasons", published=_ts(as_of, 50)),
    ]
    start_brief = build_player_brief("p1", {"full_name": "Split QB"}, start_items, feeds, as_of)
    start_rev = build_news_review("start", [start_brief], as_of)
    assert any("benched" in w.lower() for w in start_rev.warnings)

    # High-tier "benched" must NOT hide medium-tier "elevated" for drop decision
    drop_items = [
        NewsItem(provider="sleeper", source="RotoWire", title="Player benched in Week 11", published=_ts(as_of, 30)),
        NewsItem(provider="sleeper", source="RotoWire", title="Player elevated to active roster", published=_ts(as_of, 50)),
    ]
    drop_brief = build_player_brief("p2", {"full_name": "Stash WR"}, drop_items, feeds, as_of)
    drop_rev = build_news_review("drop", [drop_brief], as_of)
    assert any("elevated" in w.lower() for w in drop_rev.warnings)


def test_decision_warnings_surface_matched_keywords():
    as_of = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
    feeds = [FeedStatus(provider="sleeper", ok=True, item_count=1)]

    # Teammate-mention case: Bijan Robinson flagged because description mentions Brian Robinson's injury
    bijan_items = [
        NewsItem(
            provider="espn",
            source="ESPN",
            title="Bijan Robinson poised for heavy workload",
            description="Teammate Brian Robinson missed practice with a knee injury.",
            published=_ts(as_of, 40),
        )
    ]
    bijan_brief = build_player_brief("p1", {"full_name": "Bijan Robinson"}, bijan_items, feeds, as_of)
    for decision in ("trade", "start", "waiver"):
        rev = build_news_review(decision, [bijan_brief], as_of)
        assert any("(INJURY: injury)" in w for w in rev.warnings), f"{decision}: {rev.warnings}"

    # Multi-keyword flag
    multi_items = [
        NewsItem(
            provider="sleeper",
            source="RotoWire",
            title="Player ruled out with concussion",
            published=_ts(as_of, 4),
        )
    ]
    multi_brief = build_player_brief("p2", {"full_name": "Star WR"}, multi_items, feeds, as_of)
    multi_trade = build_news_review("trade", [multi_brief], as_of)
    assert any("(BREAKING, INJURY: ruled out/concussion)" in w for w in multi_trade.warnings)

    # Split role keywords for start vs drop
    split_items = [
        NewsItem(provider="sleeper", source="RotoWire", title="Player named starter earlier", published=_ts(as_of, 30)),
        NewsItem(provider="sleeper", source="RotoWire", title="Player benched for disciplinary reasons", published=_ts(as_of, 50)),
    ]
    split_brief = build_player_brief("p3", {"full_name": "Split QB"}, split_items, feeds, as_of)
    start_rev = build_news_review("start", [split_brief], as_of)
    assert any("(ROLE_CHANGE: benched)" in w for w in start_rev.warnings)
    assert not any("named starter" in w for w in start_rev.warnings)
    drop_rev = build_news_review("drop", [split_brief], as_of)
    assert any("(ROLE_CHANGE: named starter)" in w for w in drop_rev.warnings)
    assert not any("benched" in w for w in drop_rev.warnings)

    # Waiver opportunity keywords
    waiver_items = [
        NewsItem(
            provider="rss",
            source="PFT",
            title="Player signed and named starter",
            published=_ts(as_of, 40),
        )
    ]
    waiver_brief = build_player_brief("p4", {"full_name": "Waiver RB"}, waiver_items, feeds, as_of)
    waiver_rev = build_news_review("waiver", [waiver_brief], as_of)
    assert any("TRANSACTION: signed" in w and "ROLE_CHANGE: named starter" in w for w in waiver_rev.warnings)
