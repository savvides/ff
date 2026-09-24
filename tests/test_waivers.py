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
