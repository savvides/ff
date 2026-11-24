from datetime import datetime, timezone
from rich.console import Console
from typer.testing import CliRunner
import responses

from ff.cli import app, render_news_review
from ff.contracts import FeedStatus, NewsFlag, NewsItem, NewsReview, PlayerNewsBrief
from ff.core.config import Config, Format, save_config


def test_render_news_review_shows_banner_warnings_and_quiet_fallback():
    review = NewsReview(
        decision="trade",
        as_of=datetime(2026, 11, 24, tzinfo=timezone.utc),
        briefs=[
            PlayerNewsBrief(
                player_id="1",
                player_name="Quiet Player",
                items=[],
                flags=[],
                feeds=[FeedStatus(provider="sleeper", ok=False, error="500")],
                warnings=[],
            ),
            PlayerNewsBrief(
                player_id="2",
                player_name="Active Player",
                items=[
                    NewsItem(
                        provider="espn",
                        source="ESPN",
                        title="Active Player named starter",
                        published=int(datetime(2026, 11, 24, 6, 0, tzinfo=timezone.utc).timestamp() * 1000),
                    )
                ],
                flags=[
                    NewsFlag(
                        code="BREAKING",
                        severity="high",
                        label="Breaking (<24h)",
                        reason="Published within 24 hours",
                        headline="Active Player named starter",
                        published_date="2026-11-24",
                    )
                ],
                feeds=[FeedStatus(provider="espn", ok=True, item_count=1)],
                warnings=[],
            ),
        ],
        degraded_feeds=["sleeper"],
        warnings=["News feed(s) degraded or unreachable: sleeper. Showing available sources."],
    )
    c = Console(record=True, width=120)
    render_news_review(review, c)
    out = c.export_text()
    assert "sleeper" in out.lower()
    assert "No recent news (14d)" in out
    assert "Active Player named starter" in out


@responses.activate
def test_cli_trade_and_news_player_run_mandatory_news_review(
    monkeypatch, book, league, rosters_raw, users_raw, players_meta
):
    import ff.news

    monkeypatch.setattr("ff.cli.review_players", ff.news.review_players)
    save_config(
        Config(
            league_id=league["league_id"],
            user_id="u1",
            user_name="owner1",
            season="2026",
            format=Format(superflex=True, ppr=1.0, teams=12, is_dynasty=True),
        )
    )

    class _StubSleeper:
        def league(self, lid):
            return league

        def rosters(self, lid):
            return rosters_raw

        def users(self, lid):
            return users_raw

        def league_users(self, lid):
            return users_raw

        def players(self, fresh=False):
            return players_meta

        def state(self):
            return {"season": "2026", "week": 12, "season_type": "regular"}

        def drafts(self, lid):
            return []

        def traded_picks(self, lid):
            return []

        def trending(self, kind="add", lookback_hours=24, limit=50):
            return []

        def matchups(self, lid, week, **kwargs):
            return []

    monkeypatch.setattr("ff.cli._load", lambda: (Config(
        league_id=league["league_id"],
        user_id="u1",
        user_name="owner1",
        season="2026",
        format=Format(superflex=True, ppr=1.0, teams=12, is_dynasty=True),
    ), _StubSleeper()))
    monkeypatch.setattr("ff.cli._book", lambda *a, **k: book)

    # Mock all 3 news providers
    responses.add(
        responses.GET,
        responses.matchers.url_matcher if False else "https://api.sleeper.com/players/nfl/4984/news",
        json=[{"source": "RotoWire", "published": 1795400000000, "metadata": {"title": "Josh Allen practicing in full"}}],
    )
    responses.add(
        responses.GET,
        "https://api.sleeper.com/players/nfl/7564/news",
        status=500,
    )
    responses.add(
        responses.GET,
        "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news",
        json={"articles": []},
    )
    responses.add(
        responses.GET,
        "https://www.espn.com/espn/rss/nfl/news",
        body="<rss><channel></channel></rss>",
    )
    responses.add(
        responses.GET,
        "https://www.nbcsports.com/nfl/profootballtalk.rss",
        body="<rss><channel></channel></rss>",
    )

    runner = CliRunner()
    res_news = runner.invoke(app, ["news", "--player", "Josh Allen"])
    assert res_news.exit_code == 0, res_news.stdout
    assert "Josh Allen" in res_news.stdout
    assert "practicing in full" in res_news.stdout

    res_trade = runner.invoke(
        app,
        ["trade", "--give", "Josh Allen", "--get", "Ja'Marr Chase", "--get", "2027 1st"],
    )
    assert res_trade.exit_code == 0, res_trade.stdout
    assert "Latest News Review" in res_trade.stdout
    assert "sleeper" in res_trade.stdout.lower()  # degraded warning for 6794 500


@responses.activate
def test_dispatcher_attaches_news_review_and_supports_get_player_news(
    monkeypatch, book, league, rosters_raw, players_meta
):
    import ff.news
    from ff.contracts import Format, Roster
    from ff.core.config import Config
    from ff.services.llm.dispatcher import dispatch_tool
    from ff.services.llm.tools import ALLOWED_TOOLS

    assert "get_player_news" in ALLOWED_TOOLS
    monkeypatch.setattr("ff.services.llm.dispatcher.review_players", ff.news.review_players)

    responses.add(
        responses.GET,
        "https://api.sleeper.com/players/nfl/4984/news",
        json=[{"source": "RotoWire", "published": 1795400000000, "metadata": {"title": "Josh Allen healthy"}}],
    )
    responses.add(
        responses.GET,
        "https://api.sleeper.com/players/nfl/7564/news",
        json=[],
    )
    responses.add(
        responses.GET,
        "https://api.sleeper.com/players/nfl/9221/news",
        json=[],
    )
    responses.add(
        responses.GET,
        "https://api.sleeper.com/players/nfl/9999/news",
        json=[],
    )
    responses.add(
        responses.GET,
        "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news",
        json={"articles": []},
    )
    responses.add(
        responses.GET,
        "https://www.espn.com/espn/rss/nfl/news",
        body="<rss><channel></channel></rss>",
    )
    responses.add(
        responses.GET,
        "https://www.nbcsports.com/nfl/profootballtalk.rss",
        body="<rss><channel></channel></rss>",
    )

    cfg = Config(
        league_id=league["league_id"],
        user_id="userA",
        user_name="alice",
        season="2026",
        format=Format(superflex=True, ppr=1.0, teams=12, is_dynasty=True),
    )
    rosters = [
        Roster(roster_id=1, owner_id="userA", team_name="Dynasty Warriors", player_ids=["7564", "9221", "9999"]),
    ]
    ctx = {
        "config": cfg,
        "rosters": rosters,
        "value_book": book,
        "players_meta": players_meta,
        "roster_positions": league["roster_positions"],
        "trending": [{"player_id": "4984", "count": 50}],
    }

    news_res = dispatch_tool("get_player_news", {"player": "Josh Allen"}, ctx)
    assert news_res["decision"] == "lookup"
    assert news_res["briefs"][0]["player_name"] == "Josh Allen"

    cleanup_res = dispatch_tool("get_roster_cleanup", {"team": "Dynasty Warriors"}, ctx)
    assert "news_review" in cleanup_res

    waivers_res = dispatch_tool("get_waivers", {"limit": 5}, ctx)
    assert "news_review" in waivers_res
    assert "targets" in waivers_res
