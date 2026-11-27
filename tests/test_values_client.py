"""Tests for ValuesClient: multi-market ingestion and merging into ValueBook."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import requests
import responses

from ff.contracts import Asset, Format
from ff.values.client import VALUES_URL, ValueBook, ValuesClient
from ff.values.dp import DP_PLAYERIDS_URL, DP_VALUES_URL
from ff.values.snapshot import SecondarySnapshot


def test_values_client_merges_secondary_values():
    fc_entry = [{"player": {"sleeperId": "123", "name": "Test Player", "position": "WR"}, "value": 1500}]
    dealer_map = {"123": 1800}
    snap = SecondarySnapshot(source="ktc", label="KTC", values=dealer_map)

    with patch("ff.values.client.get_json", return_value=fc_entry), \
         patch("ff.values.ktc.KtcClient.fetch_snapshot", return_value=snap):
        client = ValuesClient(secondary="ktc")
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
    snap = SecondarySnapshot(source="ktc", label="KTC", values=dealer_map)

    with patch("ff.values.client.get_json", return_value=fc_entries), \
         patch("ff.values.ktc.KtcClient.fetch_snapshot", return_value=snap):
        client = ValuesClient(secondary="ktc")
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

    with patch("ff.values.client.get_json", return_value=fc_entry), \
         patch("ff.values.dp.DynastyProcessClient.fetch_snapshot") as mock_dp, \
         patch("ff.values.ktc.KtcClient.fetch_snapshot") as mock_ktc:
        client = ValuesClient()
        book = client.fetch(Format(), include_secondary=False)
        mock_dp.assert_not_called()
        mock_ktc.assert_not_called()
        asset = book.resolve("Test Player")
        assert asset is not None
        assert asset.value == 1500
        assert asset.secondary_value is None
        assert book.secondary_source == "none"
        assert book.secondary_label == "None"


def test_values_client_dealer_offline_fallback():
    fc_entry = [{"player": {"sleeperId": "123", "name": "Test Player", "position": "WR"}, "value": 1500}]

    with patch("ff.values.client.get_json", return_value=fc_entry), \
         patch("ff.values.ktc.KtcClient.fetch_snapshot", side_effect=requests.RequestException("Dealer offline")):
        client = ValuesClient(secondary="ktc")
        book = client.fetch(Format(), include_secondary=True)
        asset = book.resolve("Test Player")
        assert asset is not None
        assert asset.value == 1500
        assert asset.secondary_value is None


def test_values_client_unmapped_dealer_asset():
    fc_entry = [{"player": {"sleeperId": "9999", "name": "Deep Stash", "position": "WR"}, "value": 50}]
    dealer_map = {"123": 1800}
    snap = SecondarySnapshot(source="ktc", label="KTC", values=dealer_map)

    with patch("ff.values.client.get_json", return_value=fc_entry), \
         patch("ff.values.ktc.KtcClient.fetch_snapshot", return_value=snap):
        client = ValuesClient(secondary="ktc")
        book = client.fetch(Format(), include_secondary=True)
        asset = book.resolve("Deep Stash")
        assert asset is not None
        assert asset.value == 50
        assert asset.secondary_value is None


@responses.activate
def test_values_client_defaults_to_dynastyprocess():
    fc_entries = [
        {"player": {"sleeperId": "6819", "name": "Michael Pittman Jr.", "position": "WR"}, "value": 1158},
        {"player": {"id": 201, "name": "2028 1st", "position": "PICK"}, "value": 2362},
    ]
    dp_values_csv = (
        '"player","pos","team","age","draft_year","ecr_1qb","ecr_2qb","ecr_pos","value_1qb","value_2qb","scrape_date","fp_id"\n'
        '"Michael Pittman Jr.","WR","IND",29.2,2020,40.0,55.0,25.0,1441,461,"2026-11-27","19278"\n'
        '"2028 1st","PICK",,, ,55.0,45.0,,1700,1899,"2026-11-27",\n'
    )
    dp_ids_csv = (
        "mfl_id,fantasypros_id,sleeper_id,name\n"
        "15002,19278,6819,Michael Pittman\n"
    )
    responses.add(responses.GET, VALUES_URL, json=fc_entries, status=200)
    responses.add(responses.GET, DP_VALUES_URL, body=dp_values_csv, status=200)
    responses.add(responses.GET, DP_PLAYERIDS_URL, body=dp_ids_csv, status=200)

    book = ValuesClient().fetch(Format(superflex=True, tep=0.5), fresh=True)
    assert book.secondary_source == "dp"
    assert book.secondary_label == "DynastyProcess"
    assert book.secondary_top is None
    assert book.secondary_notes == ["DynastyProcess values do not adjust for TE premium"]
    pittman = book.resolve("6819")
    assert pittman is not None
    assert pittman.secondary_value == 461
    pick_28 = book.resolve("2028 1st")
    assert pick_28 is not None
    assert pick_28.secondary_value == 1899


def test_values_client_ktc_client_kwarg_keeps_ktc_backward_compat():
    fc_entry = [{"player": {"sleeperId": "123", "name": "Test Player", "position": "WR"}, "value": 1500}]
    mock_ktc = MagicMock()
    mock_ktc.fetch_snapshot.return_value = SecondarySnapshot(
        source="ktc", label="KTC", values={"123": 2100}, top=9500
    )

    with patch("ff.values.client.get_json", return_value=fc_entry):
        book = ValuesClient(ktc_client=mock_ktc).fetch(Format())
        assert book.secondary_source == "ktc"
        assert book.secondary_label == "KTC"
        assert book.secondary_top == 9500
        asset = book.resolve("123")
        assert asset is not None
        assert asset.secondary_value == 2100


def test_values_client_custom_mock_ktc_only_implementing_fetch_values():
    fc_entry = [{"player": {"sleeperId": "123", "name": "Test Player", "position": "WR"}, "value": 1500}]

    class LegacyKtcMock:
        last_top = 8888

        def fetch_values(self, fmt, fresh=False):
            return {"123": 1900}

    with patch("ff.values.client.get_json", return_value=fc_entry):
        book = ValuesClient(ktc_client=LegacyKtcMock()).fetch(Format())  # type: ignore[arg-type]
        assert book.secondary_source == "ktc"
        assert book.secondary_label == "KTC"
        assert book.secondary_top == 8888
        asset = book.resolve("123")
        assert asset is not None
        assert asset.secondary_value == 1900


def test_values_client_ktc_file_and_secondary_override(tmp_path):
    fc_entry = [{"player": {"sleeperId": "123", "name": "Test Player", "position": "WR"}, "value": 1500}]
    pool_file = tmp_path / "ktc_pool.json"
    pool_file.write_text(json.dumps([
        {"playerName": "Test Player", "position": "WR", "sleeper_id": "123",
         "superflexValues": {"value": 2400}, "oneQBValues": {"value": 2300}},
    ]), encoding="utf-8")

    with patch("ff.values.client.get_json", return_value=fc_entry):
        book_init = ValuesClient(ktc_file=pool_file).fetch(Format(superflex=True))
        assert book_init.secondary_source == "ktc"
        assert book_init.secondary_label == "KTC"
        assert book_init.secondary_top == 2400
        assert book_init.resolve("123").secondary_value == 2400

        book_fetch = ValuesClient().fetch(Format(superflex=True), ktc_file=pool_file)
        assert book_fetch.secondary_source == "ktc"
        assert book_fetch.resolve("123").secondary_value == 2400

        with pytest.raises(ValueError, match="KTC pool file"):
            ValuesClient().fetch(Format(superflex=True), ktc_file=tmp_path / "missing.json")


def test_values_client_fetch_secondary_override_and_invalid_market():
    fc_entry = [{"player": {"sleeperId": "123", "name": "Test Player", "position": "WR"}, "value": 1500}]
    mock_dp = MagicMock()
    mock_dp.fetch_snapshot.return_value = SecondarySnapshot(
        source="dp", label="DynastyProcess", values={"123": 900}
    )
    mock_ktc = MagicMock()
    mock_ktc.fetch_snapshot.return_value = SecondarySnapshot(
        source="ktc", label="KTC", values={"123": 2200}, top=9999
    )

    with patch("ff.values.client.get_json", return_value=fc_entry):
        client = ValuesClient(dp_client=mock_dp, ktc_client=mock_ktc)
        assert client.secondary == "dp"

        book_dp = client.fetch(Format())
        assert book_dp.secondary_source == "dp"
        assert book_dp.secondary_top is None
        assert book_dp.resolve("123").secondary_value == 900

        book_ktc = client.fetch(Format(), secondary="ktc")
        assert book_ktc.secondary_source == "ktc"
        assert book_ktc.secondary_top == 9999
        assert book_ktc.resolve("123").secondary_value == 2200

        book_none = client.fetch(Format(), secondary="none")
        assert book_none.secondary_source == "none"
        assert book_none.secondary_label == "None"
        assert book_none.resolve("123").secondary_value is None

        with pytest.raises(ValueError, match="Unsupported secondary market"):
            client.fetch(Format(), secondary="bogus")


def test_value_book_pick_at_tier_falls_back_to_flat_round_for_dp():
    flat_fc = Asset(id="2028 1", name="2028 1st", kind="pick", position="PICK", value=2362)
    dp_book = ValueBook(
        [flat_fc],
        secondary_map={"2028 1": 1899},
        secondary_source="dp",
        secondary_label="DynastyProcess",
    )
    p = dp_book.pick_at_tier("2028", 1, "early")
    assert p is not None
    assert p.name == "2028 1st (Early)"
    assert p.value == 2362
    assert p.secondary_value == 1899
    assert p.secondary_approx is False

    ktc_book = ValueBook(
        [flat_fc],
        secondary_map={"2028 1": 1899},
        secondary_source="ktc",
        secondary_label="KTC",
    )
    p_ktc = ktc_book.pick_at_tier("2028", 1, "early")
    assert p_ktc is not None
    assert p_ktc.secondary_value is None


def test_value_book_resolve_tiered_fc_picks_fall_back_to_flat_dp_round():
    early_fc = Asset(id="2028 1 early", name="2028 1st (Early)", kind="pick", position="PICK", value=2600)
    mid_fc = Asset(id="2028 1 mid", name="2028 1st (Mid)", kind="pick", position="PICK", value=2200)
    dp_book = ValueBook(
        [early_fc, mid_fc],
        secondary_map={"2028 1": 1899},
        secondary_source="dp",
        secondary_label="DynastyProcess",
    )

    resolved_early = dp_book.resolve("2028 1st (Early)")
    assert resolved_early is not None
    assert resolved_early.value == 2600
    assert resolved_early.secondary_value == 1899
    assert resolved_early.secondary_approx is False
    assert dp_book.picks["2028 1 early"].secondary_value is None

    resolved_flat = dp_book.resolve("2028 1st")
    assert resolved_flat is not None
    assert resolved_flat.value == 2200
    assert resolved_flat.secondary_value == 1899
    assert resolved_flat.secondary_approx is False

    unpriced_mid = Asset(id="2029 1 mid", name="2029 1st (Mid)", kind="pick", position="PICK", value=1900)
    dp_unpriced = ValueBook(
        [unpriced_mid],
        secondary_map={"2028 1": 1899},
        secondary_source="dp",
        secondary_label="DynastyProcess",
    )
    resolved_unpriced = dp_unpriced.resolve("2029 1st")
    assert resolved_unpriced is not None
    assert resolved_unpriced.secondary_value is None
    assert resolved_unpriced.secondary_approx is False


def test_value_book_legacy_none_source_does_not_pull_flat_ktc_key_as_exact():
    flat_fc = Asset(id="2028 1", name="2028 1st", kind="pick", position="PICK", value=2362)
    legacy_book = ValueBook(
        [flat_fc],
        secondary_map={"2028 1": 4600},
        secondary_source=None,
    )
    p = legacy_book.pick_at_tier("2028", 1, "early")
    assert p is not None
    assert p.secondary_value is None

    early_fc = Asset(id="2028 1 early", name="2028 1st (Early)", kind="pick", position="PICK", value=2600)
    legacy_tiered = ValueBook(
        [early_fc],
        secondary_map={"2028 1": 4600},
        secondary_source=None,
    )
    r = legacy_tiered.resolve("2028 1st (Early)")
    assert r is not None
    assert r.secondary_value is None


def test_values_package_exports_dp_and_snapshot():
    from ff.values import DynastyProcessClient, SecondarySnapshot
    from ff.values.dp import DynastyProcessClient as DirectDP
    from ff.values.snapshot import SecondarySnapshot as DirectSnapshot

    assert DynastyProcessClient is DirectDP
    assert SecondarySnapshot is DirectSnapshot

