"""Deterministic Jev result presentation and domain QA."""
from __future__ import annotations

from typing import Any, Dict, Iterable, Sequence

from rich.console import Console
from rich.table import Table
from rich.text import Text

from ff.contracts import Asset, Lineup, RosterAudit, RosterValuation, TeamPicks, WaiverTarget
from ff.qa import render_qa_footer, run_qa
from ff.contracts.models import PlayerComparison, WeeklyWaivers
from ff.services.llm.jev import Route


def _table(console: Console, title: str, columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> None:
    table = Table(title=Text(title))
    for column in columns:
        table.add_column(column)
    count = 0
    for row in rows:
        table.add_row(*(Text(str(cell)) for cell in row))
        count += 1
    if count:
        console.print(table)
    else:
        console.print(f"{title}: no results.", markup=False)


def render_result(route: Route, result: Any, ctx: Dict[str, Any], console: Console) -> None:
    tool, args = route.tool, route.kwargs
    team_id = args.get("team")
    target = next((r for r in ctx.get("rosters", []) if str(r.roster_id) == team_id), None) if team_id else None
    if tool == "get_weekly_waivers":
        render_weekly_waivers(WeeklyWaivers.model_validate(result), target, ctx, console)
        return
    if tool == "get_player_comparison":
        render_comparison(PlayerComparison.model_validate(result), target, ctx, console)
        return
    if tool == "get_roster":
        valuation = RosterValuation.model_validate(result)
        report = run_qa("roster", valuation=valuation, target_roster=target)
        console.print(f"{valuation.team_name}: dynasty value {valuation.total_value:,}; starters {valuation.starters_value:,}", markup=False)
        shown = valuation.assets[:args["limit"]]
        _table(console, "Roster", ("player", "pos", "role", "injury", "value"), (
            (a.name, a.position or "-", a.depth_role, a.injury_tag or "-", f"{a.value:,}")
            for a in shown
        ))
        if len(shown) < len(valuation.assets):
            console.print(f"Showing the top {len(shown)} of {len(valuation.assets)} players; ask for the entire roster to see all.", markup=False)
        if valuation.unvalued:
            console.print(f"Unvalued players: {len(valuation.unvalued)}; totals exclude missing market values.")
    elif tool == "get_power_rankings":
        valuations = [RosterValuation.model_validate(v) for v in result]
        report = run_qa("power", valuations=valuations, rosters=ctx.get("rosters", []))
        _table(console, "League power rankings", ("rank", "team", "value", "starters"), (
            (v.power_rank, v.team_name, f"{v.total_value:,}", f"{v.starters_value:,}") for v in valuations
        ))
    elif tool == "get_dynasty_values":
        assets = [Asset.model_validate(a) for a in result]
        report = run_qa("values", assets=assets, position=args.get("position"), market="fc")
        _table(console, "Dynasty player values", ("rank", "player", "pos", "value"), (
            (i, a.name, a.position or "-", f"{a.value:,}") for i, a in enumerate(assets, 1)
        ))
    elif tool == "get_waivers":
        targets = [WaiverTarget.model_validate(t) for t in result]
        report = run_qa("waivers", targets=targets, rosters=ctx.get("rosters", []),
                        roster_positions=ctx.get("roster_positions"))
        title = "Unrostered players by dynasty opportunity" + (" (trending only)" if args.get("trending_only") else "")
        _table(console, title, ("player", "pos", "role", "value", "opportunity", "adds"), (
            (t.asset.name, t.asset.position or "-", t.depth_role, f"{t.asset.value:,}", t.opportunity_score, t.add_count or "-")
            for t in targets
        ))
        if len(targets) < args["limit"]:
            console.print(f"Only {len(targets)} of {args['limit']} requested results matched the filters.", markup=False)
        console.print("Unrostered does not establish waiver claim status or immediate pickup eligibility; check Sleeper. Adds: '-' means outside the trending sample. Rankings use dynasty opportunity, not weekly projected points.")
    elif tool == "get_picks":
        ledger = [TeamPicks.model_validate(t) for t in result]
        selected = [target] if target else ctx.get("rosters", [])
        # A team-filtered ledger must be checked against the same team subset.
        report = run_qa("picks", ledger=ledger, rosters=selected)
        _table(console, "Future draft picks", ("owner", "pick", "original team", "tier", "value"), (
            (t.team_name, p.label, p.original_team, p.tier or "flat", f"{p.value:,}")
            for t in ledger for p in t.picks
        ))
        for t in ledger:
            console.print(f"{t.team_name}: total pick value {t.total_value:,}", markup=False)
    elif tool == "get_roster_cleanup":
        audit = RosterAudit.model_validate(result)
        report = run_qa("cleanup", audit=audit)
        console.print(f"{audit.team_name}: active {audit.active_count}/{audit.active_cap}; taxi {len(audit.taxi)}/{audit.taxi_cap}; IR {len(audit.ir)}/{audit.ir_cap}", markup=False)
        _table(console, "Drop candidates", ("player", "pos", "slot", "value", "frees active slot"), (
            (s.name, s.position or "-", s.slot, f"{s.value:,}", "yes" if s.is_active else "no") for s in audit.drop_candidates
        ))
        _table(console, "Taxi stashes that free active room", ("player", "pos", "value"), (
            (s.name, s.position or "-", f"{s.value:,}") for s in audit.taxi_candidates
        ))
    elif tool == "get_lineup":
        lineup = Lineup.model_validate(result)
        report = run_qa("lineup", lineup=lineup, target_roster=target, scoring=ctx.get("scoring"), weekly=ctx.get("weekly"))
        console.print(f"{lineup.season} week {lineup.week}: actual + remaining projections {lineup.total:.2f}")
        for title, slots in (("Starting lineup", lineup.slots), ("Bench", lineup.bench)):
            _table(console, title, ("slot", "player", "pos", "points", "basis", "status"), (
                (s.slot, s.name, s.position or "-", f"{s.points:.2f}", s.points_kind, ("LOCKED; " if s.locked else "") + s.availability) for s in slots
            ))
        render_weekly_notes(lineup, console)
        if lineup.unsupported_slots:
            console.print("Unsupported lineup slots: " + ", ".join(lineup.unsupported_slots), markup=False)
        missing = [s.name for s in lineup.slots + lineup.bench if s.player_id and s.player_id not in ctx.get("projections", {})]
        if missing:
            console.print("Missing projections (scored as zero): " + ", ".join(missing), markup=False)
    else:
        raise ValueError("Unsupported Jev result")
    render_qa_footer(report, console)


def render_weekly_notes(lineup: Lineup, console: Console) -> None:
    if lineup.as_of:
        console.print(f"Availability and schedule checked {lineup.as_of.isoformat()} (UTC).")
        console.print("Live games show actual points so far; totals exclude their unplayed remainder. Recheck Sleeper before making changes.")
    if any(w.startswith("Conditional:") for w in lineup.warnings):
        console.print("Each injury scenario changes one player at a time; backups may overlap.")
    for warning in sorted(lineup.warnings, key=lambda w: 0 if w.startswith("Conditional:") else (2 if w.startswith("Reporting context") else 1)):
        console.print(warning, markup=False)


def render_comparison(result: PlayerComparison, target: Any, ctx: dict, console: Console) -> None:
    console.print(result.recommendation, markup=False)
    _table(console, "Start/sit comparison", ("start", "full-game projection", "availability", "whole-lineup total", "constraint"), (
        (o.name, f"{o.projected_points:.2f}", o.availability,
         f"{o.lineup.total:.2f}" if o.lineup else "-", o.reason or "other player sits") for o in result.options))
    render_weekly_notes(result.baseline, console)
    report = run_qa("compare", result=result, target_roster=target, weekly=ctx["weekly"])
    render_qa_footer(report, console)


def render_weekly_waivers(result: WeeklyWaivers, target: Any, ctx: dict, console: Console) -> None:
    console.print(f"Weekly waiver lineup improvement: {result.baseline.season} week {result.baseline.week}; "
                  f"baseline {result.baseline.total:.2f}; {result.candidates_evaluated} candidates evaluated.")
    _table(console, "Unrostered players by lineup gain", ("player", "pos", "projection", "lineup gain", "displaces"), (
        (t.name, t.position, f"{t.projected_points:.2f}", f"+{t.lineup_gain:.2f}", ", ".join(t.displaced) or "-") for t in result.targets))
    for candidate in result.targets:
        kickoff = candidate.kickoff.strftime("%a %m-%d %H:%M UTC") if candidate.kickoff else "unverified"
        console.print(f"{candidate.name}: {candidate.availability}; kickoff {kickoff}.", markup=False)
    console.print("Gains assume acquisition before kickoff and room on the active roster. No drop is selected. "
                  "Unrostered does not establish claim status, waiver clearance or immediate pickup eligibility; check Sleeper. "
                  "Zero gain means depth only; questionable players and the baseline remain conditional.")
    render_weekly_notes(result.baseline, console)
    for warning in result.warnings:
        console.print(warning, markup=False)
    render_qa_footer(run_qa("weekly_waivers", result=result, target_roster=target, rosters=ctx["rosters"],
                            weekly=ctx["weekly"], roster_positions=ctx["roster_positions"]), console)
