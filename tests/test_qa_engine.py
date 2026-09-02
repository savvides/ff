"""Unit tests for the QA execution engine and renderer."""

import os
import pytest
from rich.console import Console
from ff.contracts import Asset, RosterValuation, Roster
from ff.qa.engine import run_qa, render_qa_footer, render_qa_full_report, get_qa_mode
from ff.qa.models import QAInvariantError, QAReport, QACheck


def test_run_qa_roster_valid():
    a1 = Asset(id="1", name="Player 1", value=5000, position="QB")
    val = RosterValuation(
        roster_id=1,
        team_name="Team A",
        total_value=5000,
        starters_value=5000,
        power_rank=1,
        by_position={"QB": 5000},
        assets=[a1],
    )
    roster = Roster(roster_id=1, team_name="Team A", player_ids=["1"])

    report = run_qa("roster", valuation=val, target_roster=roster)
    assert report.command == "roster"
    assert report.passed is True
    assert report.checks_passed >= 5
    assert report.checks_failed == 0
    assert report.duration_ms >= 0.0


def test_run_qa_strict_mode(monkeypatch):
    monkeypatch.setenv("FF_QA", "strict")
    # Corrupt total_value
    a1 = Asset(id="1", name="Player 1", value=5000, position="QB")
    val = RosterValuation(
        roster_id=1,
        team_name="Team A",
        total_value=9999,  # Mismatch!
        starters_value=5000,
        power_rank=1,
        by_position={"QB": 5000},
        assets=[a1],
    )

    with pytest.raises(QAInvariantError) as exc_info:
        run_qa("roster", valuation=val)
    assert "roster" in str(exc_info.value)
    assert "Roster Total Math Match" in str(exc_info.value)


def test_render_qa_footer_summary():
    c1 = QACheck(name="Check 1", passed=True)
    report = QAReport.from_checks("roster", [c1], duration_ms=0.5)
    console = Console(record=True, width=120)
    render_qa_footer(report, console, mode="summary")
    output = console.export_text()
    assert "QA" in output
    assert "passed" in output


def test_render_qa_footer_verbose():
    c1 = QACheck(name="Check Alpha", passed=True)
    c2 = QACheck(name="Check Beta", passed=False, message="Beta failed")
    report = QAReport.from_checks("power", [c1, c2], duration_ms=0.75)
    console = Console(record=True, width=120)
    render_qa_footer(report, console, mode="verbose")
    output = console.export_text()
    assert "Check Alpha" in output
    assert "Check Beta" in output
    assert "Beta failed" in output


def test_render_qa_full_report():
    c1 = QACheck(name="Check 1", passed=True)
    r1 = QAReport.from_checks("roster", [c1], duration_ms=0.5)
    r2 = QAReport.from_checks("power", [c1], duration_ms=0.4)
    console = Console(record=True, width=120)
    render_qa_full_report([r1, r2], console)
    output = console.export_text()
    assert "QA Health Scorecard" in output
    assert "roster" in output
    assert "power" in output


def test_get_qa_mode(monkeypatch):
    monkeypatch.setenv("FF_QA", "verbose")
    assert get_qa_mode() == "verbose"

    monkeypatch.setenv("FF_QA", "strict")
    assert get_qa_mode() == "strict"

    monkeypatch.setenv("FF_QA", "0")
    assert get_qa_mode() == "off"

    monkeypatch.setenv("FF_QA", "1")
    assert get_qa_mode() == "summary"

    monkeypatch.delenv("FF_QA", raising=False)
    assert get_qa_mode() == "off"
