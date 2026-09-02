"""Unit tests for QA models and data structures."""

import pytest
from ff.qa.models import QACheck, QAReport, QAInvariantError


def test_qa_check_creation_passing():
    check = QACheck(name="Roster Total Match", passed=True, message="Total equals asset sum")
    assert check.name == "Roster Total Match"
    assert check.passed is True
    assert check.message == "Total equals asset sum"
    assert check.is_warning is False


def test_qa_check_creation_warning():
    check = QACheck(name="Unvalued Assets", passed=False, message="3 players unvalued", is_warning=True)
    assert check.passed is False
    assert check.is_warning is True


def test_qa_report_from_checks():
    c1 = QACheck(name="Asset IDs Valid", passed=True)
    c2 = QACheck(name="Positional Sums Match", passed=True)
    c3 = QACheck(name="Starters Value Bound", passed=False, message="Starters value > total value", is_warning=False)
    c4 = QACheck(name="Injury Status Check", passed=False, message="Injury tag missing on IR player", is_warning=True)

    report = QAReport.from_checks("roster", [c1, c2, c3, c4], duration_ms=0.85)

    assert report.command == "roster"
    assert report.passed is False
    assert len(report.checks) == 4
    assert report.checks_passed == 2
    assert report.checks_failed == 2
    assert len(report.errors) == 1
    assert "Starters value > total value" in report.errors[0]
    assert len(report.warnings) == 1
    assert "Injury tag missing on IR player" in report.warnings[0]
    assert report.duration_ms == 0.85


def test_qa_report_all_passing():
    c1 = QACheck(name="Check 1", passed=True)
    c2 = QACheck(name="Check 2", passed=True)
    report = QAReport.from_checks("power", [c1, c2], duration_ms=0.42)

    assert report.passed is True
    assert report.checks_passed == 2
    assert report.checks_failed == 0
    assert len(report.errors) == 0
    assert len(report.warnings) == 0


def test_qa_invariant_error():
    err = QAInvariantError("roster", ["Starters value exceeds total value"])
    assert "roster" in str(err)
    assert "Starters value exceeds total value" in str(err)
    assert err.command == "roster"
    assert len(err.errors) == 1
