from datetime import datetime, timedelta, timezone

import pytest

from ff.analysis.compare import compare_players, comparison_players, resolve_player
from ff.contracts import Roster
from ff.contracts.models import WeeklyContext, WeeklyPlayer

META = {"a": {"full_name": "Nico Collins", "position": "WR"},
        "b": {"full_name": "Cooper Kupp", "position": "WR"},
        "c": {"full_name": "John Collins", "position": "WR"}}


def test_names_require_unique_alias_and_support_full_name_initials_ids():
    assert resolve_player("Nico Collins", META) == "a"
    assert resolve_player("N. Collins", META) == "a"
    assert resolve_player("a", META) == "a"
    with pytest.raises(ValueError, match="ambiguous"):
        resolve_player("Collins", META)
    with pytest.raises(ValueError, match="not found"):
        resolve_player("Cooper Kup", META)


def test_id_lookup_survives_missing_name_metadata():
    assert resolve_player("9001", {"9001": {}}) == "9001"


def test_question_name_spans_do_not_double_count_surnames():
    assert comparison_players("Should I start Nico Collins or Cooper Kupp?", META) == ["a", "b"]
    with pytest.raises(ValueError, match="ambiguous"):
        comparison_players("Start Collins or Kupp?", META)
    with pytest.raises(ValueError, match="exactly two"):
        comparison_players("Start Nico Collins?", META)


def test_roster_number_is_not_mistaken_for_player_id():
    meta = {**META, "2": {"full_name": "Different Player"}}
    assert comparison_players("Start Nico Collins or Cooper Kupp for roster 2?", meta) == ["a", "b"]


def compare(slots=None, locked=False):
    now = datetime(2026, 9, 27, tzinfo=timezone.utc)
    weekly = WeeklyContext(as_of=now, players={p: WeeklyPlayer(
        game_status="scheduled", kickoff=now + timedelta(hours=1)) for p in META})
    if locked:
        weekly.players["a"] = WeeklyPlayer(game_status="final", actual=-2)
    roster = Roster(roster_id=1, player_ids=list(META), starters=["a"])
    return compare_players(["a", "b"], roster, {"a": {"rec": 10}, "b": {"rec": 8}, "c": {"rec": 6}},
                           {"rec": 1}, slots or ["WR", "BN", "BN"], META, weekly, "2026", 3)


def test_comparison_measures_whole_lineup_difference():
    result = compare()
    assert result.difference == 2
    assert result.options[0].lineup.total == 10
    assert "Start Nico Collins" in result.recommendation


def test_both_can_belong_in_lineup():
    result = compare(["WR", "FLEX", "BN"])
    assert "Both players" in result.recommendation
    assert [o.lineup.total for o in result.options] == [16, 14]
    assert result.baseline.total == 18


def test_locked_choice_cannot_be_removed():
    result = compare(locked=True)
    assert result.options[0].lineup.total == -2
    assert result.options[1].lineup is None
    assert "locked" in result.options[1].reason
    assert result.recommendation.startswith("Keep Nico Collins in the locked slot")


def test_unowned_player_is_not_a_start_sit_option():
    with pytest.raises(ValueError, match="both players"):
        compare_players(["a", "b"], Roster(roster_id=1, player_ids=["a"]), {}, {}, ["WR"], META,
                        WeeklyContext(as_of=datetime.now(timezone.utc)), "2026", 3)
