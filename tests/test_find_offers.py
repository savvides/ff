"""ff.offers: only packages that pass the offer rule on site-adjusted
numbers come back, best rebuild fit first."""

from ff import offers as find_offers
from ff.contracts import Asset

TOP = 9999
SALE = Asset(id="1", name="Vet QB", position="QB", age=38, value=3000, secondary_value=5000, redraft_value=2800)


def _theirs():
    return [
        Asset(id="2", name="Young Twin", position="WR", age=24, value=3000, secondary_value=5000),
        Asset(id="3", name="Old Twin", position="WR", age=31, value=3000, secondary_value=5000),
        Asset(id="4", name="Stud", position="RB", age=23, value=8000, secondary_value=9000),
        Asset(id="5", name="Half A", position="WR", age=24, value=1500, secondary_value=2500),
        Asset(id="6", name="Half B", position="WR", age=24, value=1500, secondary_value=2500),
    ]


def test_only_passing_packages_come_back_and_each_re_judges_as_pass():
    rows = find_offers.search([SALE], _theirs(), [], top=TOP)
    assert [r["get"] for r in rows] == [["Young Twin"]]
    for r in rows:
        _, verdict = find_offers.judge([SALE], [a for a in _theirs() if a.name in r["get"]], top=TOP)
        assert verdict.passes and r["fc_pct"] < 10 and r["ktc_pct"] < 10


def test_older_players_are_never_offered_back():
    names = {n for r in find_offers.search([SALE], _theirs(), [], top=TOP, limit=50) for n in r["get"]}
    assert "Old Twin" not in names


def test_a_raw_even_two_for_one_fails_once_the_sites_adjust_it():
    # 3000 vs 1500 + 1500 sums even, but FantasyCalc credits the single-asset side
    # floor(min(1500 * 0.6982, 753)) = 753 -> 3753 vs 3000, a 20% gap.
    _, verdict = find_offers.judge([SALE], [a for a in _theirs() if a.name.startswith("Half")], top=TOP)
    assert verdict.status == "FAIL" and round(verdict.fc_pct, 1) == 20.1
    rows = find_offers.search([SALE], _theirs(), [], top=TOP, limit=50)
    assert ["Half A", "Half B"] not in [r["get"] for r in rows]


def test_ledger_picks_are_priced_at_their_projected_tier_and_labeled_by_origin():
    from ff.contracts import FuturePick
    from ff.values import ValueBook
    flat = Asset(id="2028 4", name="2028 4th", kind="pick", position="PICK", value=800,
                 secondary_value=1600, secondary_approx=True)
    book = ValueBook([flat], secondary_top=9999,
                     secondary_map={"2028 4 early": 1900, "2028 4 mid": 1600, "2028 4 late": 1300})
    picks = [FuturePick(season="2028", round=4, original_roster_id=7),
             FuturePick(season="2028", round=4, original_roster_id=8)]  # both project Late
    origins = {}
    assets = find_offers._roster_assets(book, [], picks, lambda rid: "late",
                                        lambda rid: f"from roster {rid}", origins)
    assert [(a.name, a.value, a.secondary_value, a.secondary_approx) for a in assets] == [
        ("2028 4th (Late)", 800, 1300, False), ("2028 4th (Late) #2", 800, 1300, False)]
    assert origins == {"2028 4th (Late)": "from roster 7", "2028 4th (Late) #2": "from roster 8"}


def test_two_picks_at_the_same_tier_can_both_be_asked_for_and_are_not_listed_twice():
    pick = Asset(id="2028 2 late", name="2028 2nd (Late)", kind="pick", position="PICK",
                 value=3000, secondary_value=5000)
    twin = pick.model_copy(update={"name": "2028 2nd (Late) #2"})
    assert [r["get"] for r in find_offers.search([SALE], [pick, twin], [], top=TOP)] == [["2028 2nd (Late)"]]
    other = Asset(id="1b", name="Vet WR", position="WR", age=33, value=3000, secondary_value=5000)
    assert [r["get"] for r in find_offers.search([SALE, other], [pick, twin], [], top=TOP)] == [
        ["2028 2nd (Late)", "2028 2nd (Late) #2"]]


RPOS = ["QB", "RB", "WR", "TE", "FLEX", "SUPER_FLEX", "BN", "BN"]
MY_PLAYERS = [  # a weak QB room, two strong TEs
    SALE.model_copy(update={"position": "WR"}),
    Asset(id="m1", name="My QB", position="QB", age=30, value=500, secondary_value=1200),
    Asset(id="m2", name="My TE1", position="TE", age=23, value=6000, secondary_value=7000),
    Asset(id="m3", name="My TE2", position="TE", age=24, value=5000, secondary_value=6000),
    Asset(id="m4", name="My RB", position="RB", age=24, value=4000, secondary_value=5500),
    Asset(id="m5", name="My RB2", position="RB", age=25, value=3500, secondary_value=5000),
    Asset(id="m6", name="My WR", position="WR", age=24, value=4500, secondary_value=6000),
]


def test_a_young_starter_at_a_need_outranks_a_surplus_piece_of_equal_value():
    theirs = [
        Asset(id="q", name="Young QB", position="QB", age=24, value=3000, secondary_value=5000),
        Asset(id="t", name="Young TE", position="TE", age=23, value=3000, secondary_value=5000),
    ]
    rows = find_offers.search([SALE], theirs, [], top=TOP, my_players=MY_PLAYERS,
                              roster_positions=RPOS, needs={"QB"}, limit=50)
    singles = [r for r in rows if len(r["get"]) == 1]
    assert [r["get"] for r in singles] == [["Young QB"], ["Young TE"]]  # both pass; the QB fills the need
    assert singles[0]["roles"]["Young QB"] == "starts at QB"
    assert singles[1]["roles"]["Young TE"] == "surplus TE, behind My TE1, My TE2"  # TE2 starts at FLEX
    assert singles[1]["net_youth"] == 0  # a surplus piece is not counted as gained young value


def test_warnings_for_injured_falling_or_dropped_pieces():
    hurt = Asset(id="f", name="Hurt TE", position="TE", age=23, value=1800, secondary_value=3600,
                 injury_status="Questionable", injury_body_part="Ankle", trend_30day=-715)
    warn = find_offers.flags(hurt, dropped={"f"})
    assert warn[0].startswith("Q") and "value -715 in 30 days" in warn
    assert "among Sleeper's most-dropped players today" in warn


def test_a_flagged_starter_is_not_counted_as_young_value():
    theirs = [
        Asset(id="q", name="Young QB", position="QB", age=24, value=3000, secondary_value=5000),
        Asset(id="f", name="Hurt QB", position="QB", age=24, value=3000, secondary_value=5000,
              injury_status="Questionable", injury_body_part="Ankle"),
    ]
    rows = find_offers.search([SALE], theirs, [], top=TOP, my_players=MY_PLAYERS,
                              roster_positions=RPOS, needs={"QB"}, dropped=set(), limit=50)
    singles = [r for r in rows if len(r["get"]) == 1]
    assert [r["get"] for r in singles] == [["Young QB"], ["Hurt QB"]]
    assert singles[1]["roles"]["Hurt QB"] == "starts at QB" and singles[1]["net_youth"] == 0


def _stub_offers_env(monkeypatch, league, rosters_raw, users_raw, players_meta, traded_picks,
                     trending, book, *, seen_vc=None):
    from ff.core.config import Config
    from ff.sleeper import detect_format

    cfg = Config(
        league_id="LG1", season="2026", name="Test Dynasty",
        format=detect_format(league), username="alice", user_id="userA",
    )

    class _StubSleeper:
        def state(self, sport="nfl", *, fresh=False):
            return {"season": "2026", "previous_season": "2025"}

        def league(self, lid, *, fresh=False):
            return league

        def rosters(self, lid, *, fresh=False):
            return rosters_raw

        def league_users(self, lid):
            return users_raw

        def players(self, sport="nfl", *, fresh=False):
            return players_meta

        def trending(self, sport="nfl", kind="add", lookback_hours=24, limit=25):
            return trending

        def traded_picks(self, lid):
            return traded_picks

        def matchups(self, lid, week, *, ttl=0):
            return []

        def drafts(self, lid):
            return [{"draft_id": "DR1", "status": "complete", "type": "linear",
                     "season": "2026", "settings": {"teams": 3, "rounds": 2}}]

    class _StubVC:
        def __init__(self, *args, **kwargs):
            if seen_vc is not None:
                seen_vc.append(kwargs)

        def fetch(self, fmt, **kwargs):
            return book

    monkeypatch.setattr(find_offers, "load_config", lambda: cfg)
    monkeypatch.setattr(find_offers, "SleeperClient", lambda *a, **k: _StubSleeper())
    monkeypatch.setattr(find_offers, "ValuesClient", _StubVC)
    monkeypatch.setattr(find_offers, "check_calculators", lambda *a, **k: [])


def test_offers_search_with_dp_market():
    sale_dp = Asset(id="1", name="Vet QB", position="QB", age=38, value=3000, secondary_value=2000,
                    redraft_value=2800)
    theirs_dp = [
        Asset(id="2", name="Young WR", position="WR", age=24, value=3050, secondary_value=2050),
        Asset(id="3", name="DP Overvalued", position="WR", age=24, value=3000, secondary_value=4000),
        Asset(id="4", name="Old WR", position="WR", age=31, value=3000, secondary_value=2000),
    ]
    rows = find_offers.search(
        [sale_dp], theirs_dp, [], top=None,
        secondary_source="dp", secondary_label="DynastyProcess",
    )
    assert [r["get"] for r in rows] == [["Young WR"]]
    assert rows[0]["fc_pct"] < 10
    assert rows[0]["secondary_pct"] is not None and rows[0]["secondary_pct"] < 10
    assert rows[0]["ktc_pct"] is None
    _, verdict = find_offers.judge(
        [sale_dp], [theirs_dp[0]], top=None,
        secondary_source="dp", secondary_label="DynastyProcess",
    )
    assert verdict.passes and verdict.secondary_source == "dp"


def test_offers_search_fc_only_mode():
    sale_no_sec = Asset(id="1", name="Vet QB", position="QB", age=38, value=3000,
                        secondary_value=None, redraft_value=2800)
    theirs_no_sec = [
        Asset(id="2", name="Young WR", position="WR", age=24, value=3050, secondary_value=None),
        Asset(id="3", name="Reach WR", position="WR", age=24, value=5000, secondary_value=None),
    ]
    rows = find_offers.search([sale_no_sec], theirs_no_sec, [], top=None, fc_only=True)
    assert [r["get"] for r in rows] == [["Young WR"]]
    assert rows[0]["fc_pct"] < 10
    assert rows[0]["secondary_pct"] is None
    assert rows[0]["ktc_totals"] == (None, None)


def test_offers_main_empty_secondary_market_gives_actionable_error(
    monkeypatch, capsys, league, rosters_raw, users_raw, players_meta, traded_picks, trending, book,
):
    from ff.values import ValueBook

    empty_sec_book = ValueBook(
        [a.model_copy() for a in book.assets],
        secondary_map={},
        secondary_source="dp",
        secondary_label="DynastyProcess",
        secondary_top=None,
    )
    _stub_offers_env(monkeypatch, league, rosters_raw, users_raw, players_meta,
                     traded_picks, trending, empty_sec_book)

    rc = find_offers.main(["--sell", "Ja'Marr Chase"])
    out = capsys.readouterr().out
    assert rc != 0
    assert "values unavailable" in out
    assert "--fc-only" in out
    assert "--ktc-file" in out


def test_offers_main_unpriced_rostered_asset_distinct_from_missing(
    monkeypatch, capsys, league, rosters_raw, users_raw, players_meta, traded_picks, trending, book,
):
    from ff.values import ValueBook

    # Roster 1 owns Ja'Marr Chase (7564) and Jahmyr Gibbs (9221); DP only prices Chase & Bijan.
    dp_map = {"7564": 9000, "8138": 8900}
    assets = [
        a.model_copy(update={"secondary_value": dp_map.get(a.id)})
        for a in book.assets
    ]
    dp_book = ValueBook(
        assets,
        secondary_map=dp_map,
        secondary_source="dp",
        secondary_label="DynastyProcess",
        secondary_top=None,
    )
    _stub_offers_env(monkeypatch, league, rosters_raw, users_raw, players_meta,
                     traded_picks, trending, dp_book)

    rc_unpriced = find_offers.main(["--sell", "Jahmyr Gibbs"])
    out_unpriced = capsys.readouterr().out
    assert rc_unpriced != 0
    assert "on your roster in FantasyCalc, but unpriced in DynastyProcess (pass --fc-only or --market ktc)" in out_unpriced
    assert "not on your roster" not in out_unpriced

    rc_missing = find_offers.main(["--sell", "Bijan Robinson"])
    out_missing = capsys.readouterr().out
    assert rc_missing != 0
    assert "not on your roster" in out_missing


def test_offers_main_dp_skips_2029_picks_with_note_and_prints_tep_caveat(
    monkeypatch, capsys, league, rosters_raw, users_raw, players_meta, traded_picks, trending, book,
):
    from ff.values import ValueBook

    dp_map = {"7564": 9000, "8138": 8900, "2027 1": 3100, "2028 1": 2200}
    assets = [a.model_copy(update={"secondary_value": dp_map.get(a.id)}) for a in book.assets]
    assets.append(Asset(id="2029 1", name="2029 1st", kind="pick", position="PICK",
                        value=2000, secondary_value=None))
    dp_book = ValueBook(
        assets,
        secondary_map=dp_map,
        secondary_source="dp",
        secondary_label="DynastyProcess",
        secondary_top=None,
        secondary_notes=["DynastyProcess values do not adjust for TE premium"],
    )
    _stub_offers_env(monkeypatch, league, rosters_raw, users_raw, players_meta,
                     traded_picks, trending, dp_book)

    rc = find_offers.main(["--sell", "Ja'Marr Chase", "--to", "Gridiron Kings", "--years", "3"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "2029" in out and "skipped" in out.lower()
    assert out.count("DynastyProcess values do not adjust for TE premium") == 1
    assert "Bijan Robinson" in out
