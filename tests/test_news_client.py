from datetime import datetime, timezone
import responses

from ff.news import NewsClient, review_players


@responses.activate
def test_news_client_merges_sleeper_espn_and_rss_and_disambiguates():
    players_meta = {
        "100": {
            "first_name": "A.J.",
            "last_name": "Brown",
            "full_name": "A.J. Brown",
            "position": "WR",
            "team": "PHI",
            "espn_id": "4047646",
        },
        "200": {
            "first_name": "Josh",
            "last_name": "Allen",
            "full_name": "Josh Allen",
            "position": "QB",
            "team": "BUF",
        },
        "201": {
            "first_name": "Josh",
            "last_name": "Allen",
            "full_name": "Josh Allen",
            "position": "DE",
            "team": "JAX",
        },
    }
    responses.add(
        responses.GET,
        "https://api.sleeper.com/players/nfl/100/news",
        json=[{"source": "RotoWire", "published": 1700000000000, "metadata": {"title": "A.J. Brown full participant"}}],
    )
    responses.add(
        responses.GET,
        "https://api.sleeper.com/players/nfl/200/news",
        json=[],
    )
    responses.add(
        responses.GET,
        "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news",
        json={
            "articles": [
                {
                    "headline": "A.J. Brown ready for Sunday",
                    "published": "2026-11-23T15:00:00Z",
                    "links": {"web": {"href": "https://espn.com/aj"}},
                }
            ]
        },
    )
    responses.add(
        responses.GET,
        "https://www.espn.com/espn/rss/nfl/news",
        body=(
            "<rss><channel>"
            "<item><title>Bills QB Josh Allen (BUF) practices in full</title>"
            "<pubDate>Mon, 23 Nov 2026 16:00:00 GMT</pubDate>"
            "<link>https://espn.com/ja</link></item>"
            "<item><title>AJ Brown shines in practice</title>"
            "<pubDate>Mon, 23 Nov 2026 17:00:00 GMT</pubDate></item>"
            "</channel></rss>"
        ),
    )
    responses.add(
        responses.GET,
        "https://www.nbcsports.com/nfl/profootballtalk.rss",
        body="<rss><channel></channel></rss>",
    )

    as_of = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
    review = review_players(
        ["100", "200", "pick_2027_1", "100"],
        players_meta,
        "trade",
        news_client=NewsClient(),
        as_of=as_of,
    )
    assert [b.player_id for b in review.briefs] == ["100", "200"]
    aj_providers = {i.provider for i in review.briefs[0].items}
    assert aj_providers == {"sleeper", "espn", "rss"}
    assert len(review.briefs[1].items) == 1  # matched BUF QB Josh Allen


@responses.activate
def test_news_client_degrades_loudly_on_xml_error_and_http_500():
    players_meta = {
        "100": {
            "first_name": "CeeDee",
            "last_name": "Lamb",
            "full_name": "CeeDee Lamb",
            "position": "WR",
            "team": "DAL",
        }
    }
    responses.add(responses.GET, "https://api.sleeper.com/players/nfl/100/news", status=500)
    responses.add(
        responses.GET,
        "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news",
        json={"articles": []},
    )
    responses.add(responses.GET, "https://www.espn.com/espn/rss/nfl/news", body="<not-valid-xml")
    responses.add(
        responses.GET,
        "https://www.nbcsports.com/nfl/profootballtalk.rss",
        body="<rss><channel></channel></rss>",
    )

    review = review_players(["100"], players_meta, "start", news_client=NewsClient())
    assert "sleeper" in review.degraded_feeds
    assert "rss" in review.degraded_feeds
    assert any("sleeper" in w.lower() for w in review.warnings)


@responses.activate
def test_news_client_handles_html_possessives_suffixes_saints_and_malformed_json():
    players_meta = {
        "100": {"full_name": "A.J. Brown", "position": "WR", "team": "PHI"},
        "200": {"full_name": "Marvin Harrison Jr.", "position": "WR", "team": "ARI"},
        "300": {"full_name": "Chris Olave", "position": "WR", "team": "NO"},
        "301": {"full_name": "Chris Olave", "position": "WR", "team": "DEN"},
    }
    # Sleeper returns non-dict metadata; ESPN returns a list instead of a dict for athlete
    responses.add(
        responses.GET,
        "https://api.sleeper.com/players/nfl/100/news",
        json=[{"source": "RotoWire", "published": 1700000000000, "metadata": "bad-shape"}],
    )
    responses.add(responses.GET, "https://api.sleeper.com/players/nfl/200/news", json=[])
    responses.add(responses.GET, "https://api.sleeper.com/players/nfl/300/news", json=[])
    # League-wide ESPN fallback matches A.J. Brown (missing espn_id) and Marvin Harrison Jr.
    responses.add(
        responses.GET,
        "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news",
        json={
            "articles": [
                {
                    "headline": "A.J. Brown's knee looks fine",
                    "description": "<p>WR/Marvin Harrison shines</p>",
                    "published": "2026-11-23T15:00:00Z",
                    "links": "bad-links",
                }
            ]
        },
    )
    responses.add(
        responses.GET,
        "https://www.espn.com/espn/rss/nfl/news",
        body=(
            "<rss><channel>"
            "<item><title>Chris Olave: no injury update today</title>"
            "<pubDate>Mon, 23 Nov 2026 16:00:00 GMT</pubDate></item>"
            "</channel></rss>"
        ),
    )
    responses.add(
        responses.GET,
        "https://www.nbcsports.com/nfl/profootballtalk.rss",
        body="<rss><channel></channel></rss>",
    )

    review = review_players(
        ["100", "200", "300"],
        players_meta,
        "trade",
        news_client=NewsClient(),
        as_of=datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc),
    )
    briefs = {b.player_id: b for b in review.briefs}
    assert any(i.provider == "espn" and "Brown" in i.title for i in briefs["100"].items)
    assert any(i.provider == "espn" and "Marvin Harrison" in i.description for i in briefs["200"].items)
    # "no injury update" lowercase "no" must NOT match Saints ("NO") ambiguous Chris Olave
    assert briefs["300"].items == []


@responses.activate
def test_news_client_degrades_on_espn_non_dict_json():
    players_meta = {"100": {"full_name": "CeeDee Lamb", "position": "WR", "team": "DAL", "espn_id": "4241389"}}
    responses.add(responses.GET, "https://api.sleeper.com/players/nfl/100/news", json=[])
    responses.add(responses.GET, "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news", json=["not-a-dict"])
    responses.add(responses.GET, "https://www.espn.com/espn/rss/nfl/news", body="<rss><channel></channel></rss>")
    responses.add(responses.GET, "https://www.nbcsports.com/nfl/profootballtalk.rss", body="<rss><channel></channel></rss>")

    review = review_players(["100"], players_meta, "start", news_client=NewsClient())
    assert "espn" in review.degraded_feeds
