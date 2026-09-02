"""Execution engine, mode resolution, and Rich renderers for the QA system."""

from __future__ import annotations

import os
import time
from typing import Any, Callable, Dict, List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ff.qa.models import QACheck, QAInvariantError, QAReport
from ff.qa.validators import (
    validate_ask,
    validate_cleanup,
    validate_draft,
    validate_lineup,
    validate_movers,
    validate_news,
    validate_picks,
    validate_power,
    validate_roster,
    validate_setup,
    validate_trade,
    validate_values,
    validate_waivers,
)

VALIDATOR_MAP: Dict[str, Callable[..., List[QACheck]]] = {
    "setup": validate_setup,
    "roster": validate_roster,
    "power": validate_power,
    "picks": validate_picks,
    "values": validate_values,
    "trade": validate_trade,
    "movers": validate_movers,
    "lineup": validate_lineup,
    "cleanup": validate_cleanup,
    "news": validate_news,
    "waivers": validate_waivers,
    "draft": validate_draft,
    "ask": validate_ask,
}

_LAST_REPORT: Optional[QAReport] = None


def get_qa_mode() -> str:
    """Resolve the active QA mode from the FF_QA environment variable.

    Returns:
        'off': checks run silently (default).
        'summary': prints a 1-line verification footer after command execution.
        'verbose': prints a full tabular inspection of every invariant check.
        'strict': raises QAInvariantError on any invariant failure.
    """
    raw = os.getenv("FF_QA", "").strip().lower()
    if raw in ("1", "true", "summary", "on"):
        return "summary"
    if raw in ("verbose", "detail"):
        return "verbose"
    if raw == "strict":
        return "strict"
    return "off"


def run_qa(command_name: str, **kwargs: Any) -> QAReport:
    """Execute domain invariants for the given command and generate a QAReport."""
    global _LAST_REPORT

    start = time.perf_counter()
    validator = VALIDATOR_MAP.get(command_name)

    if validator is not None:
        try:
            checks = validator(**kwargs)
        except Exception as exc:
            checks = [QACheck(name=f"{command_name} Exception", passed=False, message=str(exc))]
    else:
        checks = [QACheck(name=f"{command_name} Unknown", passed=True, message="No validator registered")]

    duration_ms = (time.perf_counter() - start) * 1000.0
    report = QAReport.from_checks(command_name, checks, duration_ms=duration_ms)
    _LAST_REPORT = report

    mode = get_qa_mode()
    if mode == "strict" and not report.passed:
        raise QAInvariantError(command_name, report.errors)

    return report


def get_last_qa_report() -> Optional[QAReport]:
    """Retrieve the most recent QA report from memory."""
    return _LAST_REPORT


def render_qa_footer(report: QAReport, console: Console, mode: Optional[str] = None) -> None:
    """Render the post-command QA status footer to the console."""
    resolved_mode = mode or get_qa_mode()

    if resolved_mode == "off":
        if not report.passed:
            # If an error occurred even in off mode, surface a subtle warning
            console.print(f"[dim red]⚠ QA Invariant Warning in {report.command}: {len(report.errors)} issue(s) detected[/]")
        return

    if resolved_mode in ("summary", "strict"):
        if report.passed:
            console.print(f"[dim green]✔ QA: {report.checks_passed} checks passed ({report.duration_ms:.1f}ms)[/]")
        else:
            console.print(f"[bold red]✖ QA: {report.checks_failed}/{len(report.checks)} checks failed ({report.duration_ms:.1f}ms)[/]")
            for err in report.errors:
                console.print(f"  [red]• {err}[/]")
        if report.warnings:
            for warn in report.warnings:
                console.print(f"  [yellow]• {warn}[/]")

    elif resolved_mode == "verbose":
        t = Table(title=f"QA Inspection — {report.command} ({report.duration_ms:.1f}ms)", show_edge=False)
        t.add_column("status", justify="center", width=8)
        t.add_column("check name", style="bold")
        t.add_column("details")

        for c in report.checks:
            if c.passed:
                status = "[green]PASS[/]"
                details = f"[dim]{c.message or 'OK'}[/]"
            elif c.is_warning:
                status = "[yellow]WARN[/]"
                details = f"[yellow]{c.message}[/]"
            else:
                status = "[bold red]FAIL[/]"
                details = f"[red]{c.message}[/]"
            t.add_row(status, c.name, details)

        console.print(t)


def render_qa_full_report(reports: List[QAReport], console: Console) -> None:
    """Render a comprehensive multi-command QA health scorecard."""
    total_checks = sum(len(r.checks) for r in reports)
    total_passed = sum(r.checks_passed for r in reports)
    total_failed = sum(r.checks_failed for r in reports)
    total_duration = sum(r.duration_ms for r in reports)

    all_passed = all(r.passed for r in reports)

    t = Table(title=f"QA Health Scorecard — {len(reports)} Commands Audited")
    t.add_column("command", style="bold")
    t.add_column("status", justify="center")
    t.add_column("passed", justify="right")
    t.add_column("failed", justify="right")
    t.add_column("latency", justify="right")
    t.add_column("notes")

    for r in reports:
        status = "[green]PASS[/]" if r.passed else "[bold red]FAIL[/]"
        notes = f"[red]{len(r.errors)} errors[/]" if r.errors else ("[yellow]warnings[/]" if r.warnings else "[dim]clean[/]")
        t.add_row(
            r.command,
            status,
            str(r.checks_passed),
            str(r.checks_failed),
            f"{r.duration_ms:.1f}ms",
            notes,
        )

    console.print(t)

    badge = "[bold green]ALL INVARIANTS PASSED[/]" if all_passed else "[bold red]INVARIANT FAILURES DETECTED[/]"
    console.print(Panel.fit(
        f"Result: {badge}\n"
        f"Checks: [green]{total_passed} passed[/] / [red]{total_failed} failed[/] ({total_checks} total)\n"
        f"Total Audit Latency: [cyan]{total_duration:.1f}ms[/]",
        title="QA Summary",
    ))
