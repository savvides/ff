"""Tests for ValuesClient: multi-market ingestion and merging into ValueBook."""

from unittest.mock import patch
import requests

from ff.contracts import Format
from ff.values.client import ValuesClient


def test_values_client_merges_secondary_values():
    fc_entry = [{"player": {"sleeperId": "123", "name": "Test Player", "position": "WR"}, "value": 1500}]
    dealer_map = {"123": 1800}

    with patch("ff.values.client.get_json", return_value=fc_entry), \
         patch("ff.values.dealer.DynastyDealerClient.fetch_values", return_value=dealer_map):
        client = ValuesClient()
        book = client.fetch(Format(), include_secondary=True)
        asset = book.resolve("Test Player")
        assert asset is not None
        assert asset.value == 1500
        assert asset.secondary_value == 1800
        assert asset.dealer_value == 1800
        assert asset.ktc_value == 1800


def test_values_client_merges_secondary_picks():
    fc_entries = [
        {"player": {"id": 101, "name": "2027 1st (Early)", "position": "PICK"}, "value": 4200},
        {"player": {"id": 102, "name": "2026 Pick 1.05", "position": "PICK"}, "value": 3500},
        {"player": {"id": 103, "name": "2026 1st", "position": "PICK"}, "value": 4000},
    ]
    dealer_map = {
        "2027 1 early": 4500,
        "2026 pick 1.05": 3600,
        "2026 1": 4100,
    }

    with patch("ff.values.client.get_json", return_value=fc_entries), \
         patch("ff.values.dealer.DynastyDealerClient.fetch_values", return_value=dealer_map):
        client = ValuesClient()
        book = client.fetch(Format(), include_secondary=True)

        pick_early = book.resolve("2027 1st (Early)")
        assert pick_early is not None
        assert pick_early.value == 4200
        assert pick_early.secondary_value == 4500
        assert pick_early.dealer_value == 4500
        assert pick_early.ktc_value == 4500

        pick_slot = book.resolve("2026 Pick 1.05")
        assert pick_slot is not None
        assert pick_slot.value == 3500
        assert pick_slot.secondary_value == 3600
        assert pick_slot.dealer_value == 3600
        assert pick_slot.ktc_value == 3600

        pick_flat = book.resolve("2026 1st")
        assert pick_flat is not None
        assert pick_flat.value == 4000
        assert pick_flat.secondary_value == 4100
        assert pick_flat.dealer_value == 4100
        assert pick_flat.ktc_value == 4100


def test_values_client_include_secondary_false():
    fc_entry = [{"player": {"sleeperId": "123", "name": "Test Player", "position": "WR"}, "value": 1500}]
    dealer_map = {"123": 1800}

    with patch("ff.values.client.get_json", return_value=fc_entry), \
         patch("ff.values.dealer.DynastyDealerClient.fetch_values", return_value=dealer_map) as mock_dealer:
        client = ValuesClient()
        book = client.fetch(Format(), include_secondary=False)
        mock_dealer.assert_not_called()
        asset = book.resolve("Test Player")
        assert asset is not None
        assert asset.value == 1500
        assert asset.secondary_value is None


def test_values_client_dealer_offline_fallback():
    fc_entry = [{"player": {"sleeperId": "123", "name": "Test Player", "position": "WR"}, "value": 1500}]

    with patch("ff.values.client.get_json", return_value=fc_entry), \
         patch("ff.values.dealer.DynastyDealerClient.fetch_values", side_effect=requests.RequestException("Dealer offline")):
        client = ValuesClient()
        book = client.fetch(Format(), include_secondary=True)
        asset = book.resolve("Test Player")
        assert asset is not None
        assert asset.value == 1500
        assert asset.secondary_value is None


def test_values_client_unmapped_dealer_asset():
    fc_entry = [{"player": {"sleeperId": "9999", "name": "Deep Stash", "position": "WR"}, "value": 50}]
    dealer_map = {"123": 1800}

    with patch("ff.values.client.get_json", return_value=fc_entry), \
         patch("ff.values.dealer.DynastyDealerClient.fetch_values", return_value=dealer_map):
        client = ValuesClient()
        book = client.fetch(Format(), include_secondary=True)
        asset = book.resolve("Deep Stash")
        assert asset is not None
        assert asset.value == 50
        assert asset.secondary_value is None

