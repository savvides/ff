"""Shared test fixtures. Gate tests are offline + deterministic: FF_HOME is
redirected to a tmp dir so nothing reads/writes the user's real config or cache.
"""

import json
from pathlib import Path

import pytest

from ff.values import ValueBook
from ff.values.client import _asset_from_entry

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
        m[entry["player_id"]] = entry["value"]
    return m


@pytest.fixture
def multi_market_book(fc_entries, ktc_map):
    return ValueBook([_asset_from_entry(e, ktc_map=ktc_map) for e in fc_entries])

