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
    # unvalued free agent still appears, named from players_meta, value 0
    assert targets[-1].asset.name == "Deep Stash"
    assert targets[-1].asset.value == 0


def test_include_rostered(book, trending, rosters_raw, users_raw, players_meta):
    rosters = build_rosters(rosters_raw, users_raw)
    targets = waiver_targets(trending, book, rosters, players_meta,
                             free_agents_only=False)
    ids = [t.asset.id for t in targets]
    assert "7564" in ids
    rostered = next(t for t in targets if t.asset.id == "7564")
    assert rostered.is_rostered is True
