"""Weekly advice must respect the clock, exact slots and availability."""
from datetime import datetime, timedelta, timezone

import pytest

from ff.analysis.lineup import optimal_lineup
from ff.contracts import Roster
from ff.contracts.models import WeeklyContext, WeeklyPlayer


NOW = datetime(2026, 9, 27, 17, tzinfo=timezone.utc)


def facts(**overrides):
    rows = {p: WeeklyPlayer(kickoff=NOW + timedelta(hours=i + 1), game_status="scheduled")
            for i, p in enumerate(["a", "b", "c"])}
    rows.update(overrides)
    return WeeklyContext(as_of=NOW, players=rows)


def solve(context, starters=None):
    roster = Roster(roster_id=1, player_ids=["a", "b", "c"],
                    starters=starters if starters is not None else ["a", "0"])
    return optimal_lineup(roster, {"a": {"rec": 5}, "b": {"rec": 10}, "c": {"rec": 20}},
                          {"rec": 1}, ["WR", "FLEX", "BN"],
                          {p: {"position": "WR", "full_name": p} for p in roster.player_ids},
                          weekly=context)


@pytest.mark.parametrize("actual", [0.0, -2.0])
def test_locked_starter_stays_in_exact_slot_with_actual_score(actual):
    lu = solve(facts(a=WeeklyPlayer(game_status="final", actual=actual)))
    assert [s.player_id for s in lu.slots] == ["a", "c"]
    assert lu.slots[0].locked and lu.slots[0].points == actual
    assert lu.slots[0].points_kind == "actual"


def test_locked_bench_never_enters_lineup():
    lu = solve(facts(c=WeeklyPlayer(game_status="live", actual=40)))
    assert {s.player_id for s in lu.slots} == {"a", "b"}


@pytest.mark.parametrize("offset,locked", [(1, False), (0, True), (-1, True)])
def test_kickoff_boundary(offset, locked):
    lu = solve(facts(a=WeeklyPlayer(game_status="scheduled", kickoff=NOW + timedelta(seconds=offset))))
    assert lu.slots[0].locked is locked
    if locked:
        assert lu.slots[0].player_id == "a"


def test_live_actuals_are_not_added_to_full_game_projection():
    lu = solve(facts(a=WeeklyPlayer(game_status="live", actual=3)))
    assert lu.total == 23
    assert lu.slots[0].points_kind == "actual so far"


@pytest.mark.parametrize("status", ["Out", "IR", "Suspended", "PUP"])
def test_confirmed_unavailable_player_is_not_started(status):
    lu = solve(facts(c=WeeklyPlayer(game_status="scheduled", kickoff=NOW + timedelta(hours=3), injury_status=status)))
    assert {s.player_id for s in lu.slots} == {"a", "b"}


def test_questionable_is_conditional_not_automatically_excluded():
    lu = solve(facts(c=WeeklyPlayer(game_status="scheduled", kickoff=NOW + timedelta(hours=3), injury_status="Questionable")))
    assert "c" in {s.player_id for s in lu.slots}
    assert next(s for s in lu.slots if s.player_id == "c").availability == "Questionable"


def test_unknown_timing_preserves_current_slot_and_blocks_bench():
    lu = solve(facts(a=WeeklyPlayer(), c=WeeklyPlayer()))
    assert [s.player_id for s in lu.slots] == ["a", "b"]
    assert lu.warnings


def test_empty_starter_slot_is_not_shifted():
    lu = solve(facts(a=WeeklyPlayer(game_status="final", actual=0)), ["0", "a"])
    assert lu.slots[1].player_id == "a" and lu.slots[1].locked


def test_later_selected_player_gets_flexible_slot_without_losing_points():
    lu = solve(facts())
    assert [s.player_id for s in lu.slots] == ["b", "c"]
    assert lu.total == 30


def test_unsupported_league_cannot_get_actionable_weekly_advice():
    with pytest.raises(ValueError, match="AutoSub"):
        solve(facts().model_copy(update={"blocked_reason": "AutoSubs need verified pairing data"}))


def test_missing_kickoff_is_not_an_unlocked_game():
    lu = solve(facts(c=WeeklyPlayer(game_status="scheduled")))
    assert "c" not in {s.player_id for s in lu.slots}


def test_conditional_backup_warns_before_earlier_replacement_kickoff():
    context = facts(c=WeeklyPlayer(game_status="scheduled", kickoff=NOW + timedelta(hours=3), injury_status="Questionable"))
    lu = solve(context)
    warning = next(w for w in lu.warnings if w.startswith("Conditional:"))
    assert "If out: a" in warning
    assert (NOW + timedelta(hours=1)).isoformat() in warning


def test_questionable_starter_with_unknown_timing_remains_frozen():
    lu = solve(facts(a=WeeklyPlayer(injury_status="Questionable")))
    assert lu.slots[0].player_id == "a"
    assert any("timing unverified" in w for w in lu.warnings)


def test_qa_detects_a_locked_player_moving_or_actual_score_changing():
    from ff.qa.validators import validate_lineup
    context = facts(a=WeeklyPlayer(game_status="final", actual=0))
    roster = Roster(roster_id=1, player_ids=["a", "b", "c"], starters=["a", "0"])
    lu = solve(context)
    assert all(c.passed for c in validate_lineup(lu, roster, weekly=context))
    lu.slots[0].points = 10
    assert not next(c for c in validate_lineup(lu, roster, weekly=context) if c.name == "Lineup Actual Scores").passed
    lu.slots.reverse()
    assert not next(c for c in validate_lineup(lu, roster, weekly=context) if c.name == "Lineup Preserves Frozen Slots").passed


def test_constrained_solver_matches_exhaustive_legal_lineups():
    """Independent enumeration checks the whole-lineup comparison calculation."""
    import itertools
    import random
    from ff.analysis.lineup import SLOT_ELIGIBILITY
    rng = random.Random(718)
    positions = {"a": "QB", "b": "WR", "c": "TE", "d": "RB", "e": "WR", "f": "QB"}
    slots = ["QB", "WR", "FLEX", "SUPER_FLEX"]
    roster = Roster(roster_id=1, player_ids=list(positions), starters=["a", "b", "c", "d"])
    meta = {p: {"position": pos} for p, pos in positions.items()}
    for _ in range(20):
        scores = {p: rng.randint(0, 30) for p in positions}
        scores["b"] = -2  # locked actual, even when every bench player looks better
        context = WeeklyContext(as_of=NOW, players={p: WeeklyPlayer(game_status="scheduled", kickoff=NOW + timedelta(hours=1)) for p in positions})
        context.players["b"] = WeeklyPlayer(game_status="final", actual=-2)
        result = optimal_lineup(roster, {p: {"rec": n} for p, n in scores.items()}, {"rec": 1}, slots, meta,
                                 weekly=context, required_start="f", exclude={"e"}, contingencies=False)
        legal = [order for order in itertools.permutations([p for p in positions if p != "e"], 4)
                 if order[1] == "b" and "f" in order and all(positions[p] in SLOT_ELIGIBILITY[s] for p, s in zip(order, slots))]
        assert result.total == max(sum(scores[p] for p in order) for order in legal)
