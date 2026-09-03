"""Tests for KtcClient: fetching HTML/JSON, pick normalization, aliases, caching, and fallback handling."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import subprocess

import requests
import responses

from ff.contracts import Format
from ff.values.ktc import KTC_VALUES_TTL, KTC_VALUES_URL, KtcClient


SAMPLE_HTML = """<!DOCTYPE html>
<html>
<head><title>Dynasty Rankings - KeepTradeCut</title></head>
<body>
<script>
var playersArray = [
    {
        "playerName": "Ja'Marr Chase",
        "position": "WR",
        "team": "CIN",
        "playerID": 1001,
        "sleeper_id": "7564",
        "superflexValues": {"value": 9600, "rank": 1},
        "oneQBValues": {"value": 9500, "rank": 1}
    },
    {
        "playerName": "Jahmyr Gibbs",
        "position": "RB",
        "team": "DET",
        "playerID": 1415,
        "sleeper_id": "9221",
        "superflexValues": {"value": 8400, "rank": 2},
        "oneQBValues": {"value": 8000, "rank": 2}
    },
    {
        "playerName": "Kenneth Gainwell",
        "position": "RB",
        "team": "TB",
        "playerID": 1416,
        "superflexValues": {"value": 3000, "rank": 100},
        "oneQBValues": {"value": 2800, "rank": 100}
    },
    {
        "playerName": "2026 Round 1 Early",
        "position": "RDP",
        "playerID": 2006,
        "superflexValues": {"value": 6342, "rank": 12},
        "oneQBValues": {"value": 6105, "rank": 12}
    },
    {
        "playerName": "2027 Round 1 Mid",
        "position": "RDP",
        "playerID": 2007,
        "superflexValues": {"value": 3300, "rank": 28},
        "oneQBValues": {"value": 3100, "rank": 28}
    }
];
var oneQBPlayers = [];
</script>
</body>
</html>"""


@responses.activate
def test_ktc_client_fetch_values_html_superflex():
    responses.add(responses.GET, KTC_VALUES_URL, body=SAMPLE_HTML, status=200)

    client = KtcClient()
    values = client.fetch_values(Format(superflex=True), use_cache=False)

    # Sleeper ID and normalized name lookups
    assert values["9221"] == 8400
    assert values["jahmyr gibbs"] == 8400
    assert values["7564"] == 9600
    assert values["jamarr chase"] == 9600

    # Pick normalization
    assert values["2026 1 early"] == 6342
    assert values["2027 1 mid"] == 3300

    # Nickname alias (Kenneth -> Kenny)
    assert values["kenneth gainwell"] == 3000
    assert values["kenny gainwell"] == 3000


@responses.activate
def test_ktc_client_fetch_values_html_one_qb():
    responses.add(responses.GET, KTC_VALUES_URL, body=SAMPLE_HTML, status=200)

    client = KtcClient()
    values = client.fetch_values(Format(superflex=False), use_cache=False)

    assert values["9221"] == 8000
    assert values["jahmyr gibbs"] == 8000
    assert values["7564"] == 9500
    assert values["2026 1 early"] == 6105


@responses.activate
def test_ktc_client_fetch_values_json_fixture():
    fixture_path = Path(__file__).parent / "fixtures" / "ktc_values.json"
    data = fixture_path.read_text()
    responses.add(responses.GET, KTC_VALUES_URL, body=data, status=200)

    client = KtcClient()
    values = client.fetch_values(Format(superflex=True), use_cache=False)

    assert values["9221"] == 8400
    assert values["7564"] == 9600
    assert values["2026 1 early"] == 6342
    assert values["2027 1 mid"] == 3300


@responses.activate
def test_ktc_client_graceful_degradation_on_error():
    responses.add(responses.GET, KTC_VALUES_URL, status=500)
    client = KtcClient()
    values = client.fetch_values(use_cache=False)
    assert values == {}


def test_ktc_client_ssl_error_fallback_to_curl():
    client = KtcClient()
    mock_run = MagicMock()
    mock_run.stdout = SAMPLE_HTML
    with patch("requests.get", side_effect=requests.exceptions.SSLError("TLS error")), \
         patch("subprocess.run", return_value=mock_run) as mock_subprocess:
        values = client.fetch_values(use_cache=False)
        assert mock_subprocess.called
        assert values["jahmyr gibbs"] == 8400


def test_ktc_client_exception_fallback():
    with patch("requests.get", side_effect=requests.RequestException("Connection error")):
        client = KtcClient()
        values = client.fetch_values(use_cache=False)
        assert values == {}


def test_ktc_client_malformed_payload():
    for malformed in ["<html>no players here</html>", "", "invalid json [", "var playersArray = not_json;"]:
        with patch.object(KtcClient, "_fetch_text", return_value=malformed):
            client = KtcClient()
            values = client.fetch_values(use_cache=False)
            assert isinstance(values, dict)
            assert values == {}


def test_ktc_client_custom_config():
    custom_url = "https://custom.keeptradecut.com/dynasty-rankings"
    custom_ttl = 1800
    client = KtcClient(url=custom_url, ttl=custom_ttl)
    assert client.url == custom_url
    assert client.ttl == custom_ttl


def test_ktc_export_in_values_package():
    from ff.values import KtcClient as ExportedKtcClient, DynastyDealerClient as ExportedDealerClient
    assert ExportedKtcClient is KtcClient
    assert ExportedDealerClient is KtcClient
