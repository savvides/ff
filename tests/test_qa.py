"""Unit tests for QA invariant validation and depth chart role formatting."""

import pytest
from ff.contracts import RosterAudit, RosterSlot
from ff.qa.engine import run_qa
from ff.qa.models import QAInvariantError
from ff.qa.validators import validate_cleanup


class BrokenDepthRoleSlot(RosterSlot):
    """Subclass that returns an empty depth_role to simulate invariant violation."""

    @property
    def depth_role(self) -> str:
        return ""


class InvalidFormatDepthRoleSlot(RosterSlot):
    """Subclass that returns an unformatted depth_role."""

    @property
    def depth_role(self) -> str:
        return "INVALID_ROLE"


def test_validate_cleanup_depth_role_valid():
    """Verify that valid RosterSlots with teams and positions produce valid depth_role checks."""
    slots = [
        RosterSlot(player_id="1", name="Jalen Milroe", position="QB", team="SEA", depth_chart_order=3, slot="BENCH", value=466),
        RosterSlot(player_id="2", name="Jalon Daniels", position="QB", team="TB", depth_chart_order=2, slot="BENCH", value=491),
        RosterSlot(player_id="3", name="Seth McGowan", position="RB", team="IND", depth_chart_order=2, slot="BENCH", value=704),
        RosterSlot(player_id="4", name="Tyreek Hill", position="WR", team="FA", slot="BENCH", value=708),
        RosterSlot(player_id="5", name="Travis Kelce", position="TE", team="KC", depth_chart_order=None, slot="START", value=1500),
        RosterSlot(player_id="6", name="No Team Player", position="RB", team=None, slot="BENCH", value=200),
    ]
    audit = RosterAudit(
        team_name="Test Team",
        starter_cap=1,
        bench_cap=5,
        slots=slots,
        drop_candidates=slots[1:],
    )

    checks = validate_cleanup(audit)
    role_check = next((c for c in checks if c.name == "Cleanup Depth Role Formatting Valid"), None)
    assert role_check is not None
    assert role_check.passed is True
    assert role_check.message == ""


def test_validate_cleanup_depth_role_empty_violates_invariant():
    """Verify that a non-empty position/team with empty depth_role fails validation."""
    broken_slot = BrokenDepthRoleSlot(
        player_id="bad1",
        name="Broken Player",
        position="WR",
        team="KC",
        depth_chart_order=1,
        slot="BENCH",
        value=500,
    )
    audit = RosterAudit(
        team_name="Test Team",
        starter_cap=0,
        bench_cap=1,
        slots=[broken_slot],
        drop_candidates=[broken_slot],
    )

    checks = validate_cleanup(audit)
    role_check = next((c for c in checks if c.name == "Cleanup Depth Role Formatting Valid"), None)
    assert role_check is not None
    assert role_check.passed is False
    assert "Invalid depth_role" in role_check.message
    assert "Broken Player" in role_check.message


def test_validate_cleanup_depth_role_unexpected_format_violates_invariant():
    """Verify that an unexpected depth_role format fails validation."""
    invalid_slot = InvalidFormatDepthRoleSlot(
        player_id="bad2",
        name="Bad Format Player",
        position="RB",
        team="SF",
        depth_chart_order=1,
        slot="BENCH",
        value=500,
    )
    audit = RosterAudit(
        team_name="Test Team",
        starter_cap=0,
        bench_cap=1,
        slots=[invalid_slot],
        drop_candidates=[invalid_slot],
    )

    checks = validate_cleanup(audit)
    role_check = next((c for c in checks if c.name == "Cleanup Depth Role Formatting Valid"), None)
    assert role_check is not None
    assert role_check.passed is False
    assert "INVALID_ROLE" in role_check.message


def test_run_qa_strict_depth_role_invariant_raises(monkeypatch):
    """Verify that strict mode raises QAInvariantError when depth_role check fails."""
    monkeypatch.setenv("FF_QA", "strict")
    broken_slot = BrokenDepthRoleSlot(
        player_id="bad1",
        name="Broken Player",
        position="QB",
        team="NE",
        depth_chart_order=2,
        slot="BENCH",
        value=300,
    )
    audit = RosterAudit(
        team_name="Test Team",
        starter_cap=0,
        bench_cap=1,
        slots=[broken_slot],
        drop_candidates=[broken_slot],
    )

    with pytest.raises(QAInvariantError) as exc_info:
        run_qa("cleanup", audit=audit)
    assert "cleanup" in str(exc_info.value)
    assert "Cleanup Depth Role Formatting Valid" in str(exc_info.value)
