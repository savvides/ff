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


def test_render_news_review_escapes_brackets_and_strips_raw_markup_tags():
    review = NewsReview(
        decision="start",
        as_of=datetime(2026, 11, 24, tzinfo=timezone.utc),
        briefs=[
            PlayerNewsBrief(
                player_id="1",
                player_name="Bracket Player",
                items=[
                    NewsItem(
                        provider="espn",
                        source="ESPN [NFL]",
                        title="Player update [/video] today",
                        description="Details [red]here[/red]",
                        published=int(datetime(2026, 11, 24, 6, 0, tzinfo=timezone.utc).timestamp() * 1000),
                    )
                ],
                flags=[],
                feeds=[FeedStatus(provider="espn", ok=True, item_count=1)],
                warnings=[],
            )
        ],
        degraded_feeds=[],
        warnings=["Start check — Bracket Player (BREAKING): Player update [/video] today"],
    )
    c = Console(record=True, width=120)
    render_news_review(review, c, show_details=True)
    out = c.export_text()
    assert "[/video]" in out
    assert "[yellow]" not in out
    assert "[dim]" not in out


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
        def league(self, lid, **kwargs):
            return league

        def rosters(self, lid, **kwargs):
            return rosters_raw

        def users(self, lid, **kwargs):
            return users_raw

        def user(self, uid, **kwargs):
            return {"username": uid}

        def league_users(self, lid, **kwargs):
            return users_raw

        def players(self, fresh=False):
            return players_meta

        def state(self, **kwargs):
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

    from rich.console import Console

    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setattr("ff.cli.console", Console(width=200))
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


@responses.activate
def test_all_remaining_decision_tools_and_picks_only_trade_run_news_review(
    monkeypatch, book, league, players_meta
):
    import ff.news
    from ff.contracts import Format, Roster
    from ff.contracts.models import WeeklyContext, WeeklyPlayer
    from ff.core.config import Config
    from ff.services.llm.dispatcher import dispatch_tool

    monkeypatch.setattr("ff.services.llm.dispatcher.review_players", ff.news.review_players)
    for pid in ("4984", "7564", "9221", "9999"):
        responses.add(responses.GET, f"https://api.sleeper.com/players/nfl/{pid}/news", json=[])
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
    r1 = Roster(roster_id=1, owner_id="userA", team_name="Dynasty Warriors", player_ids=["7564", "9221"])
    r2 = Roster(roster_id=2, owner_id="userB", team_name="Gridiron Kings", player_ids=["9999"])
    weekly = WeeklyContext(
        as_of=datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc),
        players={
            pid: WeeklyPlayer(game_status="scheduled", kickoff=datetime(2026, 11, 29, 18, 0, tzinfo=timezone.utc))
            for pid in ("4984", "7564", "9221", "9999")
        },
    )
    projections = {
        pid: {"pts_ppr": 15.0, "rec": 5.0, "rec_yd": 60.0, "pass_yd": 250.0}
        for pid in ("4984", "7564", "9221", "9999")
    }
    ctx = {
        "config": cfg,
        "rosters": [r1, r2],
        "value_book": book,
        "players_meta": players_meta,
        "roster_positions": league["roster_positions"],
        "scoring": league["scoring_settings"],
        "projections": projections,
        "weekly": weekly,
        "season": "2026",
        "week": 12,
        "trending": [{"player_id": "4984", "count": 25}],
    }

    picks_trade = dispatch_tool("evaluate_trade", {"give": ["2027 1st"], "get": ["2027 2nd"]}, ctx)
    assert picks_trade["news_review"]["briefs"] == []

    player_trade = dispatch_tool("evaluate_trade", {"give": ["Josh Allen"], "get": ["Ja'Marr Chase"]}, ctx)
    assert {b["player_id"] for b in player_trade["news_review"]["briefs"]} == {"4984", "7564"}

    lu_res = dispatch_tool("get_lineup", {"team": "Dynasty Warriors"}, ctx)
    assert lu_res["news_review"]["decision"] == "start"

    cmp_res = dispatch_tool("get_player_comparison", {"team": "Dynasty Warriors", "player_ids": ["7564", "9221"]}, ctx)
    assert cmp_res["news_review"]["decision"] == "start"

    plan_res = dispatch_tool("get_trade_plan", {"team": "Dynasty Warriors"}, ctx)
    assert plan_res["news_review"]["decision"] == "trade"

    ww_res = dispatch_tool("get_weekly_waivers", {"team": "Dynasty Warriors", "limit": 5}, ctx)
    assert ww_res["news_review"]["decision"] == "waiver"


def test_all_remaining_cli_decision_commands_invoke_news_review(
    monkeypatch, book, league, rosters_raw, users_raw, players_meta
):
    from ff.contracts.models import WeeklyContext, WeeklyPlayer
    from ff.news import review_players as real_review_players

    calls = []

    def _spy_review(player_ids, meta, decision, **kwargs):
        calls.append((decision, list(player_ids)))
        return NewsReview(
            decision=decision,
            as_of=datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc),
            briefs=[],
            degraded_feeds=[],
            warnings=[],
        )

    assert real_review_players is not None
    monkeypatch.setattr("ff.cli.review_players", _spy_review)
    monkeypatch.setattr("ff.offers.review_players", _spy_review)

    cfg = Config(
        league_id=league["league_id"],
        user_id="userA",
        user_name="alice",
        season="2026",
        format=Format(superflex=True, ppr=1.0, teams=12, is_dynasty=True),
    )
    save_config(cfg)

    class _StubSleeper:
        def league(self, lid, **kwargs):
            return league

        def rosters(self, lid, **kwargs):
            return rosters_raw

        def users(self, lid, **kwargs):
            return users_raw

        def user(self, uid, **kwargs):
            return {"username": uid}

        def league_users(self, lid, **kwargs):
            return users_raw

        def players(self, fresh=False):
            return players_meta

        def state(self, **kwargs):
            return {"season": "2026", "week": 12, "season_type": "regular"}

        def drafts(self, lid):
            return []

        def traded_picks(self, lid):
            return []

        def trending(self, kind="add", lookback_hours=24, limit=50):
            return [{"player_id": "4984", "count": 50}]

        def matchups(self, lid, week, **kwargs):
            return [{"roster_id": 1, "starters": ["7564", "9221"], "players_points": {}}]

    weekly = WeeklyContext(
        as_of=datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc),
        players={
            pid: WeeklyPlayer(game_status="scheduled", kickoff=datetime(2026, 11, 29, 18, 0, tzinfo=timezone.utc))
            for pid in ("4984", "5555", "7564", "9221", "9999")
        },
    )
    projections = {
        pid: {"pts_ppr": 15.0, "rec": 5.0, "rec_yd": 60.0, "pass_yd": 250.0}
        for pid in ("4984", "5555", "7564", "9221", "9999")
    }

    monkeypatch.setattr("ff.cli._load", lambda: (cfg, _StubSleeper()))
    monkeypatch.setattr("ff.cli._book", lambda *a, **k: book)
    monkeypatch.setattr(
        "ff.cli.load_weekly",
        lambda *a, **k: (weekly, players_meta),
    )
    monkeypatch.setattr(
        "ff.cli.ProjectionsClient.week",
        lambda *a, **k: projections,
    )
    monkeypatch.setattr(
        "ff.cli.ProjectionsClient.snapshot",
        lambda *a, **k: (projections, {pid: players_meta[pid] for pid in ("5555",)}),
    )
    monkeypatch.setattr(
        "ff.cli.sell_candidates",
        lambda assets, stance: [(assets[0], "test sell")] if assets else [],
    )

    runner = CliRunner()
    for args, expected_decision in (
        (["compare", "7564", "9221"], "start"),
        (["lineup"], "start"),
        (["plan"], "trade"),
        (["cleanup"], "drop"),
        (["waivers"], "waiver"),
        (["waivers", "--weekly"], "waiver"),
    ):
        calls.clear()
        res = runner.invoke(app, args)
        assert res.exit_code == 0, f"{args}: {res.stdout}"
        assert calls, f"no calls for {args}: {res.output}"
        assert calls[-1][0] == expected_decision
        assert len(calls[-1][1]) >= 1

    # Also verify ff.offers.main invokes review_players("trade", ...)
    import ff.offers as offers_mod
    from ff.values import ValueBook

    ktc_book = ValueBook(
        [a.model_copy(update={"secondary_value": a.value}) for a in book.assets],
        secondary_top=10000,
    )
    monkeypatch.setattr(offers_mod, "load_config", lambda: cfg)
    monkeypatch.setattr(offers_mod, "SleeperClient", lambda: _StubSleeper())
    monkeypatch.setattr(offers_mod, "ValuesClient", lambda: type("_VC", (), {"fetch": lambda self, *a, **k: ktc_book})())
    monkeypatch.setattr(offers_mod, "check_calculators", lambda *a, **k: [])
    calls.clear()
    rc = offers_mod.main(["--sell", "Ja'Marr Chase"])
    assert rc == 0
    assert calls and calls[-1][0] == "trade"
    assert "7564" in calls[-1][1]
