"""Live API contract checks - excluded from the gate suite (they hit the real
Sleeper + FantasyCalc APIs). Run on demand with `pytest -m live` to confirm the
upstream payload shapes haven't drifted.
"""

import pytest

from ff.contracts import Format
from ff.sleeper import SleeperClient
from ff.values import ValuesClient

pytestmark = pytest.mark.live


def test_fantasycalc_live_has_players_and_picks():
    book = ValuesClient().fetch(Format(superflex=True, num_qbs=2, num_teams=12, ppr=1.0))
    assert len(book.by_sleeper_id) > 100   # real player pool
    assert len(book.picks) > 10            # real draft picks
    # a star resolves by name and carries a positive value + rank
    star = book.resolve("Jahmyr Gibbs")
    assert star is not None and star.value > 0 and star.overall_rank


def test_fantasycalc_values_actually_track_format():
    # Superflex must value QBs far higher than 1QB. If FantasyCalc silently
    # ignored numQbs, these would be equal - exactly the regression to catch.
    one = ValuesClient().fetch(Format(superflex=False, num_qbs=1, num_teams=12, ppr=1.0))
    sf = ValuesClient().fetch(Format(superflex=True, num_qbs=2, num_teams=12, ppr=1.0))
    qb_one = one.resolve("Josh Allen")
    qb_sf = sf.resolve("Josh Allen")
    assert qb_one and qb_sf
    assert qb_sf.value > qb_one.value


def test_sleeper_live_trending_and_state():
    sc = SleeperClient()
    state = sc.state()
    assert state.get("season")
    trending = sc.trending(kind="add", limit=5)
    assert trending and "player_id" in trending[0]
