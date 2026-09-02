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
def dealer_entries():
    return load("dealer_values")


@pytest.fixture
def dealer_map(dealer_entries):
    m = {}
    raw_players = dealer_entries.get("players", []) if isinstance(dealer_entries, dict) else dealer_entries
    for entry in raw_players:
        if not isinstance(entry, dict):
            continue
        sleeper_id = entry.get("sleeper_id")
        name = entry.get("name") or ""
        is_pick = entry.get("position") == "PICK" or str(sleeper_id or "").startswith("pick_")
        raw_val = entry.get("current_value")
        if raw_val is None:
            raw_val = entry.get("base_value", 0)
        try:
            val = int(round(float(raw_val))) if raw_val is not None else 0
        except (ValueError, TypeError):
            continue

        if is_pick:
            norm_pk = normalize_pick(str(name)) if name else None
            if norm_pk:
                m[norm_pk] = val
            if sleeper_id:
                m[str(sleeper_id)] = val
        elif sleeper_id is not None:
            m[str(sleeper_id)] = val
    return m


@pytest.fixture
def ktc_entries():
    return load("ktc_values")


@pytest.fixture
def ktc_map(dealer_map):
    return dealer_map


@pytest.fixture
def multi_market_book(fc_entries, dealer_map):
    return ValueBook([_asset_from_entry(e, secondary_map=dealer_map) for e in fc_entries])


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
        def fetch(self, fmt, include_secondary=True, include_ktc=True):
            return multi_market_book if (include_secondary and include_ktc) else book

    class FakeProjections:
        def week(self, season, week, positions=None):
            return {"7564": {"rec": 8, "rec_yd": 100, "rec_td": 1},
                    "9221": {"rush_yd": 90, "rush_td": 1}}

    monkeypatch.setattr("ff.cli.SleeperClient", lambda *a, **k: FakeSleeper())
    monkeypatch.setattr("ff.cli.ValuesClient", lambda *a, **k: FakeValues())
    monkeypatch.setattr("ff.cli.ProjectionsClient", lambda *a, **k: FakeProjections())
    monkeypatch.setenv("COLUMNS", "200")  # keep rich from wrapping cells

