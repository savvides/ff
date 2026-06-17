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
    assert book.resolve("2027 1st").value == 3000
    assert book.resolve("2026 2nd").value == 1500


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
