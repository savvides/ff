"""Tests for KtcClient: fetching, pick normalization, caching, and fallback handling."""

import json
from pathlib import Path
from unittest.mock import patch

import requests

from ff.contracts import Format
from ff.values.ktc import KTC_VALUES_TTL, KTC_VALUES_URL, KtcClient


def test_ktc_fetch_and_normalize():
    sample_data = [
        {"player_id": "4034", "name": "Christian McCaffrey", "value": 6500},
        {"player_id": "2027 1.01", "name": "2027 Early 1st", "value": 4500},
    ]
    with patch("ff.values.ktc.get_json", return_value=sample_data) as mock_get:
        client = KtcClient()
        values = client.fetch_values(Format(superflex=True))
        mock_get.assert_called_once_with(KTC_VALUES_URL, ttl=KTC_VALUES_TTL)
        assert values["4034"] == 6500
        assert "2027 1 early" in values or "2027 1" in values
        assert values["2027 1 early"] == 4500


def test_ktc_fetch_fixture():
    fixture_path = Path(__file__).parent / "fixtures" / "ktc_values.json"
    data = json.loads(fixture_path.read_text())
    with patch("ff.values.ktc.get_json", return_value=data):
        client = KtcClient()
        values = client.fetch_values()
        # Verify players
        assert values["7564"] == 9600  # Ja'Marr Chase
        assert values["9221"] == 8400  # Jahmyr Gibbs
        assert values["4984"] == 7200  # Josh Allen
        assert values["8138"] == 8900  # Bijan Robinson
        assert values["4034"] == 6500  # Christian McCaffrey
        # Verify picks
        assert values["2026 pick 1.05"] == 3600
        assert values["2026 1"] == 4100
        assert values["2027 1"] == 3200
        assert values["2026 2"] == 1600
        assert values["2027 1 early"] == 4500
        assert values["2027 1 mid"] == 3300
        assert values["2027 1 late"] == 2500
        assert values["2027 2"] == 1450
        assert values["2028 1"] == 2300


def test_ktc_client_graceful_error_fallback():
    with patch("ff.values.ktc.get_json", side_effect=requests.RequestException("API offline")):
        client = KtcClient()
        values = client.fetch_values()
        assert values == {}


def test_ktc_client_malformed_payload():
    with patch("ff.values.ktc.get_json", return_value={"error": "rate limit"}):
        client = KtcClient()
        values = client.fetch_values()
        assert values == {}


def test_ktc_client_custom_config():
    custom_url = "https://custom.api/v1/values"
    custom_ttl = 3600
    with patch("ff.values.ktc.get_json", return_value=[{"player_id": "1", "name": "Player 1", "value": 100}]) as mock_get:
        client = KtcClient(url=custom_url, ttl=custom_ttl)
        values = client.fetch_values()
        mock_get.assert_called_once_with(custom_url, ttl=custom_ttl)
        assert values["1"] == 100


def test_ktc_export_in_values_package():
    from ff.values import KtcClient as ExportedKtcClient
    assert ExportedKtcClient is KtcClient
