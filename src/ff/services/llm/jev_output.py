"""Deterministic Jev result presentation and domain QA."""
from __future__ import annotations

from typing import Any, Dict, Iterable, Sequence

from rich.console import Console
from rich.table import Table
from rich.text import Text

from ff.contracts import Asset, Lineup, RosterAudit, RosterValuation, TeamPicks, WaiverTarget
from ff.qa import render_qa_footer, run_qa
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
        report = run_qa("lineup", lineup=lineup, target_roster=target, scoring=ctx.get("scoring"))
        console.print(f"{lineup.season} week {lineup.week}: projected total {lineup.total:.2f}")
        for title, slots in (("Starting lineup", lineup.slots), ("Bench", lineup.bench)):
            _table(console, title, ("slot", "player", "pos", "projected points"), (
                (s.slot, s.name, s.position or "-", f"{s.points:.2f}") for s in slots
            ))
        if lineup.unsupported_slots:
            console.print("Unsupported lineup slots: " + ", ".join(lineup.unsupported_slots), markup=False)
        missing = [s.name for s in lineup.slots + lineup.bench if s.player_id and s.player_id not in ctx.get("projections", {})]
        if missing:
            console.print("Missing projections (scored as zero): " + ", ".join(missing), markup=False)
    else:
        raise ValueError("Unsupported Jev result")
    render_qa_footer(report, console)
