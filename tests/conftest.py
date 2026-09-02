"""Shared test fixtures. Gate tests are offline + deterministic: FF_HOME is
redirected to a tmp dir so nothing reads/writes the user's real config or cache.
"""

import json
from pathlib import Path

import pytest

from ff.values import ValueBook
from ff.values.client import _asset_from_entry, normalize_pick

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str):
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture(autouse=True)
def ff_home(tmp_path, monkeypatch):
    monkeypatch.setenv("FF_HOME", str(tmp_path / ".ff"))
    return tmp_path


@pytest.fixture
def fc_entries():
    return load("fantasycalc_sf")


@pytest.fixture
def book(fc_entries):
    return ValueBook([_asset_from_entry(e) for e in fc_entries])


@pytest.fixture
def league():
    return load("league")


@pytest.fixture
def rosters_raw():
    return load("rosters")


@pytest.fixture
def users_raw():
    return load("users")


@pytest.fixture
def players_meta():
    return load("players_meta")


@pytest.fixture
def trending():
    return load("trending")


@pytest.fixture
def traded_picks():
    return load("traded_picks")


@pytest.fixture
def ktc_entries():
    return load("ktc_values")


@pytest.fixture
def ktc_map(ktc_entries):
    m = {}
    for entry in ktc_entries:
        raw_id = entry.get("player_id")
        name = entry.get("name")
        val = entry.get("value")
        norm_name = normalize_pick(name) if name else None
        norm_id = normalize_pick(raw_id) if raw_id else None
        if norm_name or norm_id:
            if norm_name:
                m[norm_name] = val
            if norm_id:
                m[norm_id] = val
        elif raw_id is not None:
            m[str(raw_id)] = val
    return m


@pytest.fixture
def multi_market_book(fc_entries, ktc_map):
    return ValueBook([_asset_from_entry(e, ktc_map=ktc_map) for e in fc_entries])


@pytest.fixture
def fake_clients(monkeypatch, book, multi_market_book, league, rosters_raw, users_raw, players_meta,
                 trending, traded_picks):
    class FakeSleeper:
        def state(self, sport="nfl"):
            return {"season": "2026", "previous_season": "2025"}

        def user(self, u):
            return {"user_id": "userA", "username": u}

        def user_leagues(self, uid, season, sport="nfl"):
            return [league]

        def league(self, lid):
            return league

        def rosters(self, lid):
            return rosters_raw

        def league_users(self, lid):
            return users_raw

        def players(self, sport="nfl"):
            return players_meta

        def trending(self, sport="nfl", kind="add", lookback_hours=24, limit=25):
            return trending

        def traded_picks(self, lid):
            return traded_picks

        def player_news(self, pid):
            return [{
                "published": 1724800000000,
                "source": "RotoWire",
                "metadata": {
                    "title": "Practicing in full",
                    "description": "Participated in all drills.",
                    "analysis": "Expected to start Sunday.",
                    "url": "https://rotowire.com/example",
                }
            }]

        def drafts(self, lid):
            return [{"draft_id": "DR1", "status": "drafting", "type": "linear",
                     "season": "2026", "settings": {"teams": 3, "rounds": 2}}]

        def draft(self, did):
            return {"draft_id": "DR1", "status": "drafting", "type": "linear",
                     "settings": {"teams": 3, "rounds": 2, "reversal_round": 0},
                     "slot_to_roster_id": {"1": 1, "2": 2, "3": 3}}

        def draft_picks(self, did):
            return [{"pick_no": 1, "round": 1, "draft_slot": 1, "roster_id": 1,
                     "player_id": "7564",
                     "metadata": {"first_name": "Ja'Marr", "last_name": "Chase",
                                  "position": "WR"}}]

        def draft_traded_picks(self, did):
            return []

    class FakeValues:
        def fetch(self, fmt, include_ktc=True):
            return multi_market_book if include_ktc else book

    class FakeProjections:
        def week(self, season, week, positions=None):
            return {"7564": {"rec": 8, "rec_yd": 100, "rec_td": 1},
                    "9221": {"rush_yd": 90, "rush_td": 1}}

    monkeypatch.setattr("ff.cli.SleeperClient", lambda *a, **k: FakeSleeper())
    monkeypatch.setattr("ff.cli.ValuesClient", lambda *a, **k: FakeValues())
    monkeypatch.setattr("ff.cli.ProjectionsClient", lambda *a, **k: FakeProjections())
    monkeypatch.setenv("COLUMNS", "200")  # keep rich from wrapping cells

