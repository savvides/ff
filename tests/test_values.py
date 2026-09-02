"""ValueBook: the player/pick lookups that everything else relies on."""

from ff.values import normalize_name, normalize_pick


def test_value_by_sleeper_id(book):
    assert book.value_for_sleeper_id("9221").name == "Jahmyr Gibbs"
    assert book.value_for_sleeper_id("9221").value == 8000
    assert book.value_for_sleeper_id("does-not-exist") is None


def test_resolve_exact_and_apostrophe(book):
    assert book.resolve("Jahmyr Gibbs").id == "9221"
    # apostrophe / casing should not matter
    assert book.resolve("jamarr chase").id == "7564"


def test_resolve_fuzzy_typo(book):
    # missing a letter still resolves to the right player
    asset = book.resolve("Bijan Robison")
    assert asset is not None and asset.id == "8138"


def test_resolve_unknown_returns_none(book):
    assert book.resolve("Totally Fake Player") is None


def test_resolve_does_not_swap_distinct_similar_name(book):
    # "Brian Robinson" is a real, different RB absent from the book. The old 0.85
    # cutoff silently returned Bijan Robinson (value 9000). It must now fail safe.
    assert book.resolve("Brian Robinson") is None


def test_resolve_surname_only_when_unambiguous(book):
    assert book.resolve("Gibbs").id == "9221"
    assert book.resolve("Bowers").id == "6666"
    assert book.resolve("Chase").id == "7564"


def test_name_collision_keeps_higher_value():
    from ff.contracts import Asset
    from ff.values import ValueBook
    b = ValueBook([
        Asset(id="1", name="Mike Williams", position="WR", value=100),
        Asset(id="2", name="Mike Williams", position="WR", value=40),
    ])
    assert b.resolve("Mike Williams").value == 100  # not silently shadowed


def test_ambiguous_surname_returns_none():
    from ff.contracts import Asset
    from ff.values import ValueBook
    b = ValueBook([
        Asset(id="1", name="Aaron Jones", position="RB", value=100),
        Asset(id="2", name="Jacoby Jones", position="WR", value=40),
    ])
    assert b.resolve("Jones") is None  # two distinct players -> refuse to guess


def test_suggest_offers_ambiguous_surname_candidates():
    from ff.contracts import Asset
    from ff.values import ValueBook
    b = ValueBook([
        Asset(id="1", name="Tee Higgins", position="WR", value=3000),
        Asset(id="2", name="Jayden Higgins", position="WR", value=1700),
    ])
    assert {a.name for a in b.suggest("Higgins")} == {"Tee Higgins", "Jayden Higgins"}
    assert b.resolve("Higgins") is None  # suggest never auto-resolves


def test_resolve_round_pick(book):
    # Regression: the tiered "2027 1st (Early/Mid/Late)" entries load after the
    # flat one; before tier-aware keys they all collapsed onto "2027 1" and the
    # last tier silently overwrote this flat value.
    assert book.resolve("2027 1st").value == 3000
    assert book.resolve("2026 2nd").value == 1500


def test_resolve_tiered_pick(book):
    assert book.resolve("2027 1st (Early)").value == 4200
    assert book.resolve("2027 early 1st").value == 4200
    assert book.resolve("2027 Late 1st").value == 2400


def test_resolve_tiered_ask_falls_back_to_flat(book):
    # No tiered 2028 entries exist -> a tiered ask uses the flat round value.
    assert book.resolve("2028 early 1st").value == 2200


def test_resolve_flat_ask_falls_back_to_mid():
    # Only tiered entries exist -> a flat ask takes mid, the neutral slot.
    from ff.values.client import _asset_from_entry
    from ff.values import ValueBook
    b = ValueBook([_asset_from_entry(
        {"player": {"id": i, "name": f"2029 1st ({t})", "position": "PICK"},
         "value": v}) for i, (t, v) in enumerate([("Early", 40), ("Mid", 30), ("Late", 20)])])
    assert b.resolve("2029 1st").value == 30


def test_resolve_slot_pick_exact(book):
    assert book.resolve("2026 Pick 1.05").value == 3500
    assert book.resolve("2026 1.05").value == 3500


def test_resolve_slot_pick_falls_back_to_round(book):
    # we have no value for 1.07 specifically -> use the round-level 1st value
    assert book.resolve("2026 1.07").value == 4000


def test_top_overall_excludes_picks(book):
    top = book.top(limit=3)
    assert [a.name for a in top] == ["Ja'Marr Chase", "Bijan Robinson", "Jahmyr Gibbs"]
    assert all(not a.is_pick for a in top)


def test_top_by_position(book):
    wr = book.top(position="WR")
    assert [a.name for a in wr] == ["Ja'Marr Chase", "Rome Odunze"]


def test_normalize_helpers():
    assert normalize_name("Ja'Marr Chase Jr.") == "jamarr chase"
    assert normalize_pick("2027 1st") == "2027 1"
    assert normalize_pick("2026 Pick 1.05") == "2026 pick 1.05"
    assert normalize_pick("Josh Allen") is None
    assert normalize_pick("2027 1st (Early)") == "2027 1 early"
    assert normalize_pick("2027 Mid 1st") == "2027 1 mid"
    assert normalize_pick("2027 round 2 late") == "2027 2 late"


def test_asset_from_entry_with_dealer_map():
    from ff.values.client import _asset_from_entry
    player_entry = {
        "player": {"sleeperId": "9221", "name": "Jahmyr Gibbs", "position": "RB"},
        "value": 8000,
    }
    pick_entry = {
        "player": {"id": 101, "name": "2027 1st (Early)", "position": "PICK"},
        "value": 4200,
    }
    dealer_map = {
        "9221": 9906,
        "2027 1 early": 5000,
    }

    # Test via dealer_map parameter
    a_player = _asset_from_entry(player_entry, dealer_map=dealer_map)
    assert a_player.secondary_value == 9906
    assert a_player.dealer_value == 9906
    assert a_player.ktc_value == 9906

    a_pick = _asset_from_entry(pick_entry, dealer_map=dealer_map)
    assert a_pick.secondary_value == 5000
    assert a_pick.dealer_value == 5000
    assert a_pick.ktc_value == 5000

    # Test via secondary_map parameter
    a_player_sec = _asset_from_entry(player_entry, secondary_map=dealer_map)
    assert a_player_sec.secondary_value == 9906

    # Test with no map
    a_player_none = _asset_from_entry(player_entry)
    assert a_player_none.secondary_value is None


def test_values_client_fetch_dynasty_dealer():
    from unittest.mock import MagicMock, patch
    from ff.contracts import Format
    from ff.values.client import ValuesClient
    from ff.values.dealer import DynastyDealerClient

    mock_dealer = MagicMock(spec=DynastyDealerClient)
    mock_dealer.fetch_values.return_value = {"9221": 9906}

    fc_data = [
        {"player": {"sleeperId": "9221", "name": "Jahmyr Gibbs", "position": "RB"}, "value": 8000}
    ]

    with patch("ff.values.client.get_json", return_value=fc_data):
        client = ValuesClient(dealer_client=mock_dealer)
        book = client.fetch(Format(), include_secondary=True)
        assert mock_dealer.fetch_values.called
        asset = book.resolve("Jahmyr Gibbs")
        assert asset is not None
        assert asset.value == 8000
        assert asset.secondary_value == 9906
        assert asset.dealer_value == 9906

        # include_secondary=False
        mock_dealer.reset_mock()
        book_no_sec = client.fetch(Format(), include_secondary=False)
        assert not mock_dealer.fetch_values.called
        asset_no_sec = book_no_sec.resolve("Jahmyr Gibbs")
        assert asset_no_sec.secondary_value is None

        # include_ktc=False backward-compat parameter
        mock_dealer.reset_mock()
        book_no_ktc = client.fetch(Format(), include_ktc=False)
        assert not mock_dealer.fetch_values.called
        asset_no_ktc = book_no_ktc.resolve("Jahmyr Gibbs")
        assert asset_no_ktc.secondary_value is None


def test_values_client_type_hints_resolvable():
    import typing
    import ff.values.client as client_module

    hints_asset = typing.get_type_hints(client_module._asset_from_entry)
    assert hints_asset["return"] is client_module.Asset

    hints_fetch = typing.get_type_hints(client_module.ValuesClient.fetch)
    assert hints_fetch["return"] is client_module.ValueBook


