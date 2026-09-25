from __future__ import annotations

"""Waiver targets: trending joined to value + roster availability."""

from ff.analysis import waiver_targets
from ff.sleeper import build_rosters


def test_free_agents_only_and_sorted(book, trending, rosters_raw, users_raw, players_meta):
    rosters = build_rosters(rosters_raw, users_raw)
    targets = waiver_targets(trending, book, rosters, players_meta)

    # 7564 (Chase) is rostered -> filtered out. 5555 + 7777 are free agents.
    ids = [t.asset.id for t in targets]
    assert "7564" not in ids
    # most valuable free agent first
    assert targets[0].asset.name == "Rome Odunze"
    assert targets[0].asset.value == 4500
    assert targets[0].add_count == 4200
    assert targets[0].team == "CHI"
    assert targets[0].depth_chart_order == 1
    assert targets[0].depth_role == "WR1"
    # unvalued free agent still appears, named from players_meta, value 0
    assert targets[-1].asset.name == "Deep Stash"
    assert targets[-1].asset.value == 0
    assert targets[-1].team == "CHI"
    assert targets[-1].depth_chart_order == 4
    assert targets[-1].depth_role == "WR4"


def test_include_rostered(book, trending, rosters_raw, users_raw, players_meta):
    rosters = build_rosters(rosters_raw, users_raw)
    targets = waiver_targets(trending, book, rosters, players_meta,
                             free_agents_only=False)
    ids = [t.asset.id for t in targets]
    assert "7564" in ids
    rostered = next(t for t in targets if t.asset.id == "7564")
    assert rostered.is_rostered is True
    assert rostered.team == "CIN"
    assert rostered.depth_chart_order == 1
    assert rostered.depth_role == "WR1"



def test_position_filter_before_limit():
    from ff.contracts import Asset
    from ff.values import ValueBook

    book = ValueBook([
        Asset(id="wr", name="Receiver", position="WR", value=5000),
        Asset(id="rb", name="Runner", position="RB", value=1000),
    ])
    trending = [{"player_id": p, "count": 1} for p in ("wr", "rb")]
    targets = waiver_targets(trending, book, [], limit=1, is_superflex=False, position="rb")
    # The higher-valued WR must not take the only slot before the RB filter.
    assert [t.asset.id for t in targets] == ["rb"]


def test_full_pool_includes_nontrending_players_and_respects_league_slots():
    from ff.contracts import Asset, Roster
    from ff.values import ValueBook

    meta = {
        "rb": {"full_name": "Quiet Runner", "position": "RB", "team": "CIN", "active": True},
        "qb": {"full_name": "Quiet Quarterback", "position": "QB", "team": "CHI", "active": True},
        "k": {"full_name": "Trending Kicker", "position": "K", "team": "TB", "active": True},
        "owned": {"position": "RB", "team": "NYJ", "active": True},
        "retired": {"position": "QB", "team": "CHI", "active": False},
    }
    book = ValueBook([Asset(id="unsigned", name="Unsigned Prospect", position="WR", value=100)])
    roster = Roster(roster_id=1, team_name="Team", player_ids=["owned"], taxi=["owned"])
    trending = [{"player_id": "k", "count": 5000}]
    targets = waiver_targets(trending, book, [roster], meta, roster_positions=["RB", "SUPER_FLEX"])
    assert {t.asset.id for t in targets} == {"rb", "qb", "unsigned"}
    assert all(t.add_count == 0 for t in targets)
    for pos, pid in [("RB", "rb"), ("QB", "qb")]:
        filtered = waiver_targets(trending, book, [roster], meta, position=pos, limit=1,
                                  roster_positions=["RB", "SUPER_FLEX"])
        assert [t.asset.id for t in filtered] == [pid]


def test_trending_filter_is_explicit_and_empty_trends_do_not_hide_full_pool():
    from ff.values import ValueBook

    meta = {"rb": {"full_name": "Runner", "position": "RB", "team": "CIN", "active": True}}
    assert [t.asset.id for t in waiver_targets([], ValueBook([]), [], meta)] == ["rb"]
    assert waiver_targets([], ValueBook([]), [], meta, trending_only=True) == []


def test_kickers_are_allowed_only_when_the_league_can_start_them():
    from ff.values import ValueBook

    meta = {"k": {"full_name": "Kicker", "position": "K", "team": "TB", "active": True}}
    for slots, expected in [(["FLEX"], []), (["K"], ["k"]), ([], [])]:
        targets = waiver_targets([], ValueBook([]), [], meta, roster_positions=slots)
        assert [t.asset.id for t in targets] == expected


def test_overlapping_flex_slots_allow_their_positions():
    from ff.values import ValueBook

    meta = {p: {"full_name": p, "position": p, "team": "CIN", "active": True}
            for p in ("QB", "RB", "WR", "TE", "K")}
    for slot, expected in [("WRRB_FLEX", {"WR", "RB"}), ("REC_FLEX", {"WR", "TE"})]:
        targets = waiver_targets([], ValueBook([]), [], meta, roster_positions=[slot])
        assert {t.asset.position for t in targets} == expected
