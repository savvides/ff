"""Tests for DynastyDealerClient: fetching, pick normalization, caching, and fallback handling."""

import json
from pathlib import Path
from unittest.mock import patch

import requests
import responses

from ff.contracts import Format
from ff.values.dealer import DEALER_VALUES_TTL, DEALER_VALUES_URL, DynastyDealerClient


@responses.activate
def test_dealer_client_fetch_values():
    fixture_path = Path(__file__).parent / "fixtures" / "dealer_values.json"
    data = json.loads(fixture_path.read_text())
    responses.add(responses.GET, DEALER_VALUES_URL, json=data, status=200)

    client = DynastyDealerClient()
    values = client.fetch_values(Format(superflex=True))

    assert values["9221"] == 8400
    assert values["9509"] == 9750
    assert values["8138"] == 8900
    assert values["7564"] == 9600
    assert values["2026 1 early"] == 6342
    assert values["2027 1 mid"] == 3300


def test_dealer_client_base_value_fallback():
    sample_data = {
        "players": [
            {
                "sleeper_id": "1234",
                "name": "Test Player",
                "position": "QB",
                "base_value": 5000,
                "current_value": None,
            },
            {
                "sleeper_id": "pick_2026_1_late",
                "name": "2026 Round 1 Late",
                "position": "PICK",
                "base_value": 4000,
            },
            {
                "sleeper_id": "pick_unparseable",
                "name": "Unknown Pick",
                "position": "PICK",
                "current_value": 2000,
            },
        ]
    }
    with patch("ff.values.dealer.get_json", return_value=sample_data):
        client = DynastyDealerClient()
        values = client.fetch_values()

        assert values["1234"] == 5000
        assert values["2026 1 late"] == 4000
        assert values["pick_unparseable"] == 2000


@responses.activate
def test_dealer_client_graceful_degradation_on_error():
    responses.add(responses.GET, DEALER_VALUES_URL, status=500)
    client = DynastyDealerClient()
    values = client.fetch_values()
    assert values == {}


def test_dealer_client_exception_fallback():
    with patch("ff.values.dealer.get_json", side_effect=requests.RequestException("Connection error")):
        client = DynastyDealerClient()
        values = client.fetch_values()
        assert values == {}


def test_dealer_client_malformed_payload():
    for malformed in [None, [], "invalid", {}, {"players": "not-a-list"}, {"players": [{"invalid": 1}]}]:
        with patch("ff.values.dealer.get_json", return_value=malformed):
            client = DynastyDealerClient()
            values = client.fetch_values()
            assert isinstance(values, dict)


def test_dealer_client_custom_config():
    custom_url = "https://custom.dynastydealer.com/api/player-values"
    custom_ttl = 1800
    sample_data = {
        "players": [
            {"sleeper_id": "1", "name": "Player 1", "current_value": 100}
        ]
    }
    with patch("ff.values.dealer.get_json", return_value=sample_data) as mock_get:
        client = DynastyDealerClient(url=custom_url, ttl=custom_ttl)
        values = client.fetch_values()
        mock_get.assert_called_once_with(custom_url, ttl=custom_ttl)
        assert values["1"] == 100


def test_dealer_export_in_values_package():
    from ff.values import DynastyDealerClient as ExportedClient, KtcClient as ExportedKtcClient
    assert ExportedClient is DynastyDealerClient
    assert ExportedKtcClient is DynastyDealerClient

