"""ff command-line interface.

    ff setup <username>     pick your league, auto-detect its format, save it
    ff roster [team]        price out a roster, with power rank + positions
    ff power                league power rankings by dynasty value
    ff picks [team]         future draft capital by team, tier-valued
    ff values [-p WR]       dynasty rankings for your league format
    ff trade --give --get   analyze a trade (players + picks), with a fairness call
    ff waivers              trending free agents worth grabbing, by value
    ff cleanup [team]       roster capacity: who to drop / stash on taxi for room
    ff draft [-p QB] [-r]   live draft board: your picks + best available by value
"""

from __future__ import annotations

import functools
import inspect
import json
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests
import typer
from pydantic import ValidationError
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from ff import __version__
from ff.analysis import (
    analyze_trade,
    audit_roster,
    available,
    detect_status,
    my_picks,
    optimal_lineup,
    pick_ledger,
    position_deltas,
    projected_points,
    rank_fits,
    top_movers,
    value_all_rosters,
    value_roster,
    waiver_targets,
)
from ff.contracts import Roster
from ff.core.config import Config, config_exists, load_config, save_config
from ff.projections import ProjectionsClient
from ff.services.llm.runner import SUPPORTED_BACKENDS, TerminalRunner
from ff.services.llm.tools import TOOL_SCHEMAS
from ff.sleeper import SleeperClient, build_rosters, detect_format
from ff.values import ValueBook, ValuesClient, normalize_name

app = typer.Typer(add_completion=False, help="Manage a Sleeper dynasty league with free data.")
config_app = typer.Typer(help="Manage configuration settings.")
app.add_typer(config_app, name="config")
console = Console()


# --- shared plumbing -----------------------------------------------------

def _fail(msg: str) -> None:
    console.print(f"[bold red]error[/] {msg}")
    raise typer.Exit(1)


def _guard(fn: Callable) -> Callable:
    """Turn the two expected real-world failures into a clean one-line error
    instead of a traceback: an unreachable/erroring API, and a corrupt config.
    Preserves the wrapped signature so Typer still sees the command's options."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except requests.exceptions.RequestException as e:
            _fail(f"could not reach Sleeper/FantasyCalc ({e}). Check your connection and retry.")
        except (ValidationError, json.JSONDecodeError):
            _fail("config is corrupt or out of date. Run `ff setup <sleeper-username>` to rebuild it.")

    wrapper.__signature__ = inspect.signature(fn)  # keep Typer's option parsing
    return wrapper


def _load() -> Tuple[Config, SleeperClient]:
    if not config_exists():
        _fail("no league configured. Run `ff setup <sleeper-username>` first.")
    return load_config(), SleeperClient()


def _book(cfg: Config) -> ValueBook:
    return ValuesClient().fetch(cfg.format)


def _league_rosters(cfg: Config, sc: SleeperClient) -> List[Roster]:
    return build_rosters(sc.rosters(cfg.league_id), sc.league_users(cfg.league_id))


def _signed(n: int) -> str:
    return f"+{n:,}" if n > 0 else f"{n:,}"


# --- setup ---------------------------------------------------------------

@app.command()
@_guard
def setup(
    username: str = typer.Argument(..., help="Your Sleeper username."),
    season: Optional[str] = typer.Option(None, help="Season year; defaults to current."),
    league_id: Optional[str] = typer.Option(None, help="Skip selection; use this league id."),
    league_index: Optional[int] = typer.Option(
        None, "--league-index", "-n",
        help="Pick the Nth league non-interactively (index from the printed list)."),
) -> None:
    """Find your dynasty league, auto-detect its format, and save it."""
    sc = SleeperClient()
    season = season or sc.state().get("season")

    # Always resolve the user so user_id is saved even when --league-id is given;
    # otherwise `ff roster` cannot tell which team is yours.
    user = sc.user(username)
    user_id = user.get("user_id") if user else None
    if not user_id:
        _fail(f"no Sleeper user named '{username}'.")

    if not league_id:
        leagues = sc.user_leagues(user_id, season)
        if not leagues:  # offseason: this season's leagues may not exist yet
            prev = sc.state().get("previous_season")
            if prev:
                season = prev
                leagues = sc.user_leagues(user_id, season)
        if not leagues:
            _fail(f"no leagues for '{username}' in {season}.")
        if len(leagues) == 1:
            chosen = leagues[0]
        elif league_index is not None:
            if league_index < 0 or league_index >= len(leagues):
                _fail(f"--league-index {league_index} out of range (0-{len(leagues) - 1}).")
            chosen = leagues[league_index]
        else:
            console.print(f"[bold]{username}[/] is in {len(leagues)} leagues for {season}:")
            for i, lg in enumerate(leagues):
                console.print(f"  [cyan]{i}[/]  {lg.get('name')}  "
                              f"({lg.get('total_rosters')} teams)  [dim]id={lg.get('league_id')}[/]")
            if not sys.stdin.isatty():
                _fail("multiple leagues and no interactive terminal. "
                      "Re-run with --league-index N or --league-id <id>.")
            idx = typer.prompt("pick one", type=int)
            if idx < 0 or idx >= len(leagues):
                _fail("selection out of range.")
            chosen = leagues[idx]
        league_id = chosen["league_id"]

    league = sc.league(league_id)
    fmt = detect_format(league)
    cfg = Config(
        league_id=league_id,
        season=str(season),
        name=league.get("name", ""),
        format=fmt,
        username=username,
        user_id=user_id,
    )
    path = save_config(cfg)
    console.print(Panel.fit(
        f"[bold green]Saved[/] [bold]{cfg.name}[/]\n"
        f"format: [cyan]{fmt.label()}[/]\n"
        f"league_id: {cfg.league_id}\n"
        f"config: {path}",
        title="ff setup",
    ))


# --- roster --------------------------------------------------------------

@app.command()
@_guard
def roster(
    team: Optional[str] = typer.Argument(None, help="Team name; defaults to yours."),
    top: int = typer.Option(15, help="How many top assets to list."),
) -> None:
    """Price out a roster: total value, power rank, positions, top assets."""
    cfg, sc = _load()
    if team is None and not cfg.user_id:
        _fail("your team is unknown. Re-run `ff setup <username>` so it records you, "
              "or pass a team name: ff roster \"<team>\".")
    book = _book(cfg)
    rosters = _league_rosters(cfg, sc)
    players_meta = sc.players()

    target = _pick_roster(rosters, team, cfg.user_id)
    if target is None:
        _fail("could not find that team. Try `ff power` to list teams.")

    valuations = value_all_rosters(rosters, book, players_meta)
    val = next(v for v in valuations if v.roster_id == target.roster_id)

    header = (f"[bold]{val.team_name}[/]   value [bold cyan]{val.total_value:,}[/]   "
              f"power rank [bold]#{val.power_rank}[/]/{len(rosters)}   "
              f"starters {val.starters_value:,}")
    console.print(Panel.fit(header, title="roster"))

    pos_table = Table(title="by position", show_edge=False)
    pos_table.add_column("pos"); pos_table.add_column("value", justify="right")
    for pos, v in sorted(val.by_position.items(), key=lambda x: x[1], reverse=True):
        if v:
            pos_table.add_row(pos, f"{v:,}")
    console.print(pos_table)

    t = Table(title=f"top {top} assets")
    for c in ("player", "pos", "age", "value", "ovr", "30d"):
        t.add_column(c, justify="right" if c in ("value", "ovr", "30d", "age") else "left")
    for a in val.assets[:top]:
        t.add_row(a.name, a.position or "-",
                  f"{a.age:.0f}" if a.age else "-", f"{a.value:,}",
                  str(a.overall_rank or "-"),
                  _signed(a.trend_30day) if a.trend_30day else "-")
    console.print(t)
    if val.unvalued:
        console.print(f"[dim]{len(val.unvalued)} unvalued (K/DEF/deep bench) not shown.[/]")
    console.print("[dim]value counts rostered players only, not your draft picks.[/]")


def _pick_roster(rosters: List[Roster], team: Optional[str],
                 user_id: Optional[str]) -> Optional[Roster]:
    if team:
        low = team.lower()
        for r in rosters:
            if low in r.team_name.lower():
                return r
        return None
    if user_id:
        for r in rosters:
            if r.owner_id == user_id:
                return r
    # No silent rosters[0] fallback: returning the wrong team is worse than a
    # clear failure. Callers handle None.
    return None


# --- power ---------------------------------------------------------------

@app.command()
@_guard
def power() -> None:
    """League power rankings by total dynasty value."""
    cfg, sc = _load()
    book = _book(cfg)
    rosters = _league_rosters(cfg, sc)
    valuations = value_all_rosters(rosters, book, sc.players())
    by_id = {r.roster_id: r for r in rosters}

    t = Table(title=f"{cfg.name} - power rankings ({cfg.format.label()})")
    for c in ("#", "team", "dynasty value", "record", "pts for"):
        t.add_column(c, justify="right" if c in ("dynasty value", "pts for", "#") else "left")
    for v in valuations:
        r = by_id[v.roster_id]
        t.add_row(str(v.power_rank), v.team_name, f"{v.total_value:,}",
                  f"{r.wins}-{r.losses}" + (f"-{r.ties}" if r.ties else ""),
                  f"{r.points_for:.0f}")
    console.print(t)
    console.print("[dim]value = rostered players only; draft picks are not counted, "
                  "so pick-rich rebuilders rank low here. Value picks in `ff trade`.[/]")


# --- picks ---------------------------------------------------------------

@app.command()
@_guard
def picks(
    team: Optional[str] = typer.Argument(None, help="Team name; omit for the whole league."),
    years: int = typer.Option(2, help="How many future seasons to show."),
    rounds: Optional[int] = typer.Option(None, help="Rookie rounds per season; "
                                         "overrides auto-detection."),
) -> None:
    """Future draft capital by team: every pick's current owner (endowment
    reconciled with trades), valued like `ff trade`. The half of team value
    that `power` leaves out."""
    cfg, sc = _load()
    book = _book(cfg)
    rosters = _league_rosters(cfg, sc)
    league = sc.league(cfg.league_id)

    # "Future" starts after the latest draft's season: once a year's rookie
    # draft exists its picks live on the draft board (`ff draft`), not here.
    latest = _active_draft(sc, cfg.league_id)
    base = int((latest or {}).get("season") or league.get("season") or cfg.season)
    start = base + 1 if latest else base
    seasons = [str(start + i) for i in range(max(1, years))]
    # Future rookie drafts are sized by the league's draft_rounds setting; the
    # latest draft's own round count is only a fallback because in a first-year
    # league that draft is the startup, whose 20+ rounds would fabricate future
    # picks. --rounds overrides both (the year-one escape hatch).
    rounds_n = int(rounds
                   or (league.get("settings") or {}).get("draft_rounds")
                   or (((latest or {}).get("settings")) or {}).get("rounds")
                   or 4)

    valuations = value_all_rosters(rosters, book, sc.players())
    ranks = {v.roster_id: v.power_rank for v in valuations}
    ledger = pick_ledger(rosters, sc.traded_picks(cfg.league_id), book, ranks,
                         seasons=seasons, rounds=rounds_n)

    if team is None:
        span = seasons[0] if len(seasons) == 1 else f"{seasons[0]}-{seasons[-1][2:]}"
        t = Table(title=f"draft capital - {span} ({cfg.format.label()})")
        for c in ("#", "team", *seasons, "pick value"):
            t.add_column(c, justify="right" if c in ("#", "pick value") else "left")
        for i, tp in enumerate(ledger, 1):
            cells = []
            for season in seasons:
                have = [p.label.split()[1] + ("[cyan]*[/]" if p.acquired else "")
                        for p in tp.picks if p.season == season]
                cells.append(", ".join(have) or "[dim]none[/]")
            t.add_row(str(i), tp.team_name, *cells, f"{tp.total_value:,}")
        console.print(t)
        console.print("[dim]* acquired via trade.[/]")
    else:
        target = _pick_roster(rosters, team, cfg.user_id)
        if target is None:
            _fail("could not find that team. Try `ff power` to list teams.")
        tp = next(x for x in ledger if x.roster_id == target.roster_id)
        rank = next((i for i, x in enumerate(ledger, 1) if x.roster_id == tp.roster_id))
        console.print(Panel.fit(
            f"[bold]{tp.team_name}[/]   pick value [bold cyan]{tp.total_value:,}[/]   "
            f"draft capital rank [bold]#{rank}[/]/{len(ledger)}", title="picks"))
        t = Table()
        for c in ("pick", "origin", "tier", "value"):
            t.add_column(c, justify="right" if c == "value" else "left")
        for p in tp.picks:
            t.add_row(p.label,
                      f"[cyan]from {p.original_team}[/]" if p.acquired else "own",
                      p.tier or "-", f"{p.value:,}")
        console.print(t)
    console.print("[dim]picks only - players are `ff power`. 1sts/2nds are tiered "
                  "early/mid/late by the ORIGINAL team's power rank (a bad team's own "
                  "1st is an early one); other rounds use the flat round value; "
                  "0 = FantasyCalc does not price that round. This year's board: "
                  "`ff draft`.[/]")


# --- values / rankings ---------------------------------------------------

@app.command()
@_guard
def values(
    position: Optional[str] = typer.Option(None, "--position", "-p",
                                            help="QB/RB/WR/TE; omit for overall."),
    limit: int = typer.Option(40, help="How many to list."),
) -> None:
    """Dynasty rankings for your league format."""
    cfg, sc = _load()
    book = _book(cfg)
    assets = book.top(position, limit)
    t = Table(title=f"dynasty rankings - {cfg.format.label()}"
                    + (f" - {position.upper()}" if position else ""))
    right = ("value", "30d", "age", "#", "posrk")
    for c in ("#", "player", "pos", "posrk", "team", "age", "value", "30d"):
        t.add_column(c, justify="right" if c in right else "left")
    for i, a in enumerate(assets, 1):
        posrk = f"{a.position}{a.position_rank}" if a.position_rank else "-"
        t.add_row(str(i), a.name, a.position or "-", posrk, a.team or "-",
                  f"{a.age:.0f}" if a.age else "-", f"{a.value:,}",
                  _signed(a.trend_30day) if a.trend_30day else "-")
    console.print(t)


# --- trade ---------------------------------------------------------------

@app.command()
@_guard
def trade(
    give: str = typer.Option(..., "--give", help="What you send, comma-separated."),
    get: str = typer.Option(..., "--get", help="What you receive, comma-separated."),
) -> None:
    """Analyze a trade. Players and picks both count (e.g. --get '2027 1st')."""
    cfg, sc = _load()
    book = _book(cfg)
    give_tokens = [t for t in give.split(",") if t.strip()]
    get_tokens = [t for t in get.split(",") if t.strip()]
    # Surface any non-exact (fuzzy/surname) match so a substitution is never silent.
    subs = []
    for tok in get_tokens + give_tokens:
        a = book.resolve(tok)
        if a and not a.is_pick and normalize_name(tok) != normalize_name(a.name):
            subs.append((tok.strip(), a.name))
    # side_a = what you receive, side_b = what you give: delta>0 means you win.
    evaluation, unresolved = analyze_trade(
        get_tokens, give_tokens, book, labels=("You get", "You give")
    )

    t = Table(title="trade")
    for c in ("side", "assets", "value"):
        t.add_column(c, justify="right" if c == "value" else "left")
    t.add_row("[green]You get[/]",
              ", ".join(f"{a.name} ({a.value:,})" for a in evaluation.side_a.assets) or "-",
              f"[bold]{evaluation.value_a:,}[/]")
    t.add_row("[red]You give[/]",
              ", ".join(f"{a.name} ({a.value:,})" for a in evaluation.side_b.assets) or "-",
              f"[bold]{evaluation.value_b:,}[/]")
    console.print(t)

    net = evaluation.delta  # >0 = in your favor
    pct = evaluation.pct_diff
    if evaluation.is_fair():
        verdict = f"[bold yellow]fair[/] - within {pct:.0f}%"
    elif net > 0:
        verdict = f"[bold green]you win[/] by {_signed(net)} ({pct:.0f}%)"
    else:
        verdict = f"[bold red]you lose[/] by {_signed(net)} ({pct:.0f}%)"
    console.print(Panel.fit(
        f"net {_signed(net)} value to you   |   {verdict}", title="verdict"))

    deltas = position_deltas(evaluation)
    if deltas:
        line = "   ".join(f"{p} {_signed(v)}" for p, v in
                          sorted(deltas.items(), key=lambda x: abs(x[1]), reverse=True) if v)
        if line:
            console.print(f"[dim]positional swing:[/] {line}")
    for tok, name in subs:
        console.print(f"[dim]matched '{tok}' -> {name}[/]")
    if unresolved:
        console.print(f"[bold red]unmatched (ignored):[/] {', '.join(unresolved)} "
                      f"[dim]- check spelling, or '2027 1st' / '2027 early 1st' for picks[/]")
        for tok in unresolved:
            cands = book.suggest(tok)
            if cands:
                console.print(f"[dim]  did you mean: "
                              f"{', '.join(c.name for c in cands)}?[/]")


# --- waivers -------------------------------------------------------------

@app.command()
@_guard
def waivers(
    limit: int = typer.Option(20, help="How many to show."),
    include_rostered: bool = typer.Option(False, "--all", help="Include rostered players."),
) -> None:
    """Trending adds across Sleeper, joined to dynasty value and your league."""
    cfg, sc = _load()
    book = _book(cfg)
    rosters = _league_rosters(cfg, sc)
    trending = sc.trending(kind="add", limit=max(limit * 3, 50))
    targets = waiver_targets(trending, book, rosters, sc.players(),
                             limit=limit, free_agents_only=not include_rostered)

    t = Table(title="waiver targets - trending adds by dynasty value")
    for c in ("player", "pos", "value", "adds", "status"):
        t.add_column(c, justify="right" if c in ("value", "adds") else "left")
    for tgt in targets:
        a = tgt.asset
        status = "[yellow]rostered[/]" if tgt.is_rostered else "[green]free agent[/]"
        t.add_row(a.name, a.position or "-", f"{a.value:,}", f"{tgt.add_count:,}", status)
    console.print(t)


@app.command()
@_guard
def cleanup(
    team: Optional[str] = typer.Argument(None, help="Team name; defaults to yours."),
    drops: int = typer.Option(8, help="How many drop candidates to list."),
) -> None:
    """Roster cleanup: capacity vs fill, who to drop, and which young players to
    stash on taxi so you free active room for a waiver add without losing value."""
    cfg, sc = _load()
    if team is None and not cfg.user_id:
        _fail("your team is unknown. Re-run `ff setup <username>`, or pass a team name.")
    league = sc.league(cfg.league_id)
    settings = league.get("settings") or {}
    roster_positions = league.get("roster_positions") or []
    book = _book(cfg)
    rosters = _league_rosters(cfg, sc)
    target = _pick_roster(rosters, team, cfg.user_id)
    if target is None:
        _fail("could not find that team. Try `ff power` to list teams.")
    players_meta = sc.players()

    audit = audit_roster(
        target, book, players_meta,
        roster_positions=roster_positions,
        taxi_slots=int(settings.get("taxi_slots") or 0),
        reserve_slots=int(settings.get("reserve_slots") or 0),
        taxi_allow_vets=bool(settings.get("taxi_allow_vets")),
        taxi_years=settings.get("taxi_years"),
        drop_limit=drops,
    )

    if audit.active_open < 0:
        active_txt = (f"[bold red]{audit.active_count}/{audit.active_cap} "
                      f"- OVER by {-audit.active_open}[/]")
    elif audit.active_open == 0:
        active_txt = f"[yellow]{audit.active_count}/{audit.active_cap} - full[/]"
    else:
        active_txt = (f"[green]{audit.active_count}/{audit.active_cap} "
                      f"- {audit.active_open} open[/]")
    console.print(Panel.fit(
        f"[bold]{audit.team_name}[/]\n"
        f"active (start+bench) {active_txt}\n"
        f"taxi {len(audit.taxi)}/{audit.taxi_cap}   IR {len(audit.ir)}/{audit.ir_cap}",
        title="roster cleanup"))

    # Concrete "how to make room" line: taxi stashes + zero-value bench drops each
    # open one active slot right now.
    taxi_ids = {s.player_id for s in audit.taxi_candidates}
    bench_zeros = [s for s in audit.drop_candidates if s.is_active and s.value == 0 and s.player_id not in taxi_ids]
    openable = len(audit.taxi_candidates) + len(bench_zeros)
    if audit.active_open <= 0 and openable:
        console.print(f"[bold]make room:[/] up to [bold]{openable}[/] active slot(s) "
                      f"available now ([green]{len(audit.taxi_candidates)} taxi stash[/], "
                      f"[green]{len(bench_zeros)} zero-value bench drop[/]).")

    dt = Table(title="drop candidates - worst value first")
    right = ("age", "exp", "value", "30d")
    for c in ("player", "pos", "age", "exp", "value", "30d", "where", "frees"):
        dt.add_column(c, justify="right" if c in right else "left")
    for s in audit.drop_candidates:
        frees = "[green]active slot[/]" if s.is_active else f"[dim]{s.slot.lower()} slot only[/]"
        dt.add_row(s.name, s.position or "-",
                   f"{s.age:.0f}" if s.age else "-",
                   str(s.years_exp) if s.years_exp is not None else "-",
                   f"{s.value:,}", _signed(s.trend_30day) if s.trend_30day else "-",
                   s.slot, frees)
    console.print(dt)

    if audit.taxi_candidates:
        tt = Table(title="stash on taxi - frees an active slot, keeps the player")
        for c in ("player", "pos", "age", "value", "30d"):
            tt.add_column(c, justify="right" if c in ("age", "value", "30d") else "left")
        for s in audit.taxi_candidates:
            tt.add_row(s.name, s.position or "-", f"{s.age:.0f}" if s.age else "-",
                       f"{s.value:,}", _signed(s.trend_30day) if s.trend_30day else "-")
        console.print(tt)
    elif audit.taxi_open > 0:
        console.print(f"[dim]{audit.taxi_open} taxi slot(s) open, but no taxi-eligible "
                      f"bench player to stash.[/]")

    console.print("[dim]Dropping a taxi/IR player frees a taxi/IR slot, not an active one; "
                  "only a bench drop or a taxi stash opens room for a waiver add. "
                  "ff is read-only - make the moves in Sleeper.[/]")


@app.command()
@_guard
def movers(
    buy: bool = typer.Option(False, "--buy", help="Show buy-low instead of sell-high."),
    limit: int = typer.Option(20, help="How many to show."),
    min_value: int = typer.Option(1000, "--min-value",
                                  help="Floor on both values; filters deep stashes."),
) -> None:
    """Buy-low / sell-high: biggest gaps between dynasty and win-now value."""
    cfg, sc = _load()
    book = _book(cfg)
    rows = top_movers(book, buy=buy, limit=limit, min_value=min_value)
    kind = "buy-low (dynasty > win-now)" if buy else "sell-high (win-now > dynasty)"
    t = Table(title=f"movers - {kind} - {cfg.format.label()}")
    right = ("dynasty", "redraft", "gap%", "age")
    for c in ("player", "pos", "age", "dynasty", "redraft", "gap%"):
        t.add_column(c, justify="right" if c in right else "left")
    for a, pct in rows:
        t.add_row(a.name, a.position or "-", f"{a.age:.0f}" if a.age else "-",
                  f"{a.value:,}", f"{a.redraft_value:,}", f"{pct:+.0f}%")
    console.print(t)


@app.command()
@_guard
def lineup(
    team: Optional[str] = typer.Argument(None, help="Team name; defaults to yours."),
    week: Optional[int] = typer.Option(None, help="NFL week; defaults to the current/upcoming one."),
    season: Optional[str] = typer.Option(None, help="Season; defaults to your league's."),
) -> None:
    """Optimal start/sit for a week, scored by your league's exact rules (incl TEP)."""
    cfg, sc = _load()
    if team is None and not cfg.user_id:
        _fail("your team is unknown. Re-run `ff setup <username>`, or pass a team name.")

    league = sc.league(cfg.league_id)
    scoring = league.get("scoring_settings") or {}
    roster_positions = league.get("roster_positions") or []
    rosters = _league_rosters(cfg, sc)
    target = _pick_roster(rosters, team, cfg.user_id)
    if target is None:
        _fail("could not find that team. Try `ff power` to list teams.")

    state = sc.state()
    season = season or cfg.season
    week = week or state.get("display_week") or state.get("week") or 1
    if week < 1:
        week = 1

    proj = ProjectionsClient().week(season, week)
    if not proj:
        _fail(f"no projections published for {season} week {week} yet. "
              f"Try a different --week, or wait until they post.")
    players_meta = sc.players()

    lu = optimal_lineup(target, proj, scoring, roster_positions, players_meta,
                        season=season, week=week)
    info = projected_points(target, proj, scoring, players_meta)

    console.print(Panel.fit(
        f"[bold]{target.team_name}[/]   {season} week {week}   "
        f"projected [bold cyan]{lu.total:g}[/]   [dim]({cfg.format.label()})[/]",
        title="optimal lineup"))

    t = Table()
    for c in ("slot", "player", "pos", "proj"):
        t.add_column(c, justify="right" if c == "proj" else "left")
    for s in lu.slots:
        t.add_row(s.slot, s.name, s.position or "-", f"{s.points:g}")
    console.print(t)
    if lu.unsupported_slots:
        console.print(f"[bold yellow]note:[/] this league uses slots the optimizer "
                      f"can't place optimally ({', '.join(sorted(set(lu.unsupported_slots)))}); "
                      f"they're left out of the lineup above.")

    # Start/sit advice vs the lineup currently set on Sleeper.
    optimal_ids = {s.player_id for s in lu.slots if s.player_id}
    current = [p for p in target.starters if p in info]
    if current:
        current_total = round(sum(info[p]["points"] for p in current), 2)
        sit = [p for p in current if p not in optimal_ids]
        start = [s for s in lu.slots if s.player_id and s.player_id not in set(target.starters)]
        if start or sit:
            gain = round(lu.total - current_total, 2)
            console.print(f"[bold green]+{gain:g} projected[/] vs your current lineup "
                          f"([dim]{current_total:g} -> {lu.total:g}[/]):")
            for s in start:
                console.print(f"  [green]START[/] {s.name} ({s.points:g}) in {s.slot}")
            for p in sit:
                console.print(f"  [red]SIT[/]   {info[p]['name']} ({info[p]['points']:g})")
        else:
            console.print("[dim]your current lineup is already optimal.[/]")

    if lu.bench:
        top_bench = ", ".join(f"{b.name} ({b.points:g})" for b in lu.bench[:5])
        console.print(f"[dim]bench: {top_bench}[/]")


# --- draft ---------------------------------------------------------------

def _active_draft(sc: SleeperClient, league_id: str) -> Optional[Dict[str, Any]]:
    """The league's live draft if one is running, else the most recent.

    Prefers an in-progress (or paused) draft, then a not-yet-started one, then
    falls back to the newest by season/start time."""
    drafts = sc.drafts(league_id)
    if not drafts:
        return None
    for status in ("drafting", "paused", "pre_draft"):
        for d in drafts:
            if d.get("status") == status:
                return d
    return sorted(drafts, key=lambda d: (d.get("season", ""), d.get("start_time") or 0),
                  reverse=True)[0]


@app.command()
@_guard
def draft(
    position: Optional[str] = typer.Option(None, "--position", "-p",
                                           help="QB/RB/WR/TE; filter the available list."),
    limit: int = typer.Option(30, help="How many available players to list."),
    rookies: bool = typer.Option(False, "--rookies", "-r", help="Available rookies only."),
    mode: str = typer.Option("auto", "--mode",
                             help="contend|rebuild|auto (auto reads your power rank)."),
    draft_id: Optional[str] = typer.Option(None, "--draft-id",
                                           help="Override the auto-detected draft."),
) -> None:
    """Live draft board scored FOR your team: your picks, where you stand, and the
    best available ranked by fit (roster need + win-now/rebuild horizon), not raw
    market value alone."""
    cfg, sc = _load()
    if not cfg.user_id:
        _fail("your team is unknown. Re-run `ff setup <username>` so it records you.")

    mode = mode.lower()
    if mode not in ("auto", "contend", "rebuild"):
        _fail("--mode must be auto, contend, or rebuild.")

    if not draft_id:
        summary = _active_draft(sc, cfg.league_id)
        if not summary:
            _fail("no draft found for this league.")
        draft_id = summary["draft_id"]
    # Always pull the single-draft endpoint: the /drafts list omits
    # slot_to_roster_id, which pick ownership needs.
    d = sc.draft(draft_id)
    if not d:
        _fail("no draft found for this league.")

    settings = d.get("settings") or {}
    teams = int(settings.get("teams") or cfg.format.num_teams)
    rounds = int(settings.get("rounds") or 0)
    dtype = (d.get("type") or "linear").lower()
    snake = dtype == "snake"
    reversal = int(settings.get("reversal_round") or 0)
    slot_to_roster = {int(k): v for k, v in (d.get("slot_to_roster_id") or {}).items()}
    if dtype not in ("linear", "snake") or rounds < 1:
        _fail(f"draft type '{dtype}' with {rounds} rounds is not supported "
              f"(only snake/linear, slot-based drafts).")

    rosters = _league_rosters(cfg, sc)
    mine = _pick_roster(rosters, None, cfg.user_id)
    if mine is None:
        _fail("could not find your roster in this league.")

    picks = sc.draft_picks(draft_id)
    traded = sc.draft_traded_picks(draft_id)
    made = len(picks)
    on_clock = made + 1

    status = d.get("status")
    rnd_now = (on_clock - 1) // teams + 1 if teams else 0
    head_status = {"drafting": "[green]drafting[/]", "complete": "[dim]complete[/]"}.get(
        status, status or "?")
    progress = (f"complete ({made} picks)" if status == "complete"
                else f"round {rnd_now}/{rounds}, pick [bold]#{on_clock}[/] on the clock")
    console.print(Panel.fit(
        f"[bold]{cfg.name.strip()}[/]   {head_status}   {dtype}   {progress}\n"
        f"[dim]{cfg.format.label()}[/]", title="draft"))

    # your picks (made + upcoming, with gaps)
    owned = my_picks(mine.roster_id, slot_to_roster, traded, picks,
                     teams=teams, rounds=rounds, snake=snake, reversal_round=reversal)
    pt = Table(title="your picks")
    for c in ("pick", "rnd", "status", "when"):
        pt.add_column(c, justify="right" if c in ("pick", "rnd") else "left")
    prev = made
    for p in owned:
        if p.used:
            st = f"[dim]used -> {p.player_name} ({p.position or '-'})[/]"
            when = ""
        else:
            st = "[green]available[/]"
            gap = p.pick_no - prev - 1
            when = ("[bold green]ON THE CLOCK[/]" if p.pick_no == on_clock
                    else f"{gap} pick{'s' if gap != 1 else ''} away")
            prev = p.pick_no
        pt.add_row(f"#{p.pick_no}", str(p.round), st, when)
    console.print(pt)

    # taken = rostered league-wide + already drafted here
    players_meta = sc.players()
    taken: set = set()
    for r in rosters:
        taken.update(str(pid) for pid in r.player_ids)
    drafted_by_me = []
    for pk in picks:
        pid = pk.get("player_id")
        if pid:
            taken.add(str(pid))
            if pk.get("roster_id") == mine.roster_id:
                drafted_by_me.append(str(pid))

    # your roster by position (a needs glance) - includes what you drafted today.
    # Value it through value_roster so positions/values match `roster`/`power`.
    book = _book(cfg)
    have = set(mine.player_ids)
    merged = mine.model_copy(update={
        "player_ids": list(mine.player_ids) + [p for p in drafted_by_me if p not in have]})
    val = value_roster(merged, book, players_meta)

    # Team context FIRST: a pick recommendation that ignores your roster is just
    # the market read back to you. Slots drive both standing and starter-upgrade.
    league = sc.league(cfg.league_id)
    roster_positions = league.get("roster_positions") or []
    all_vals = value_all_rosters(rosters, book, players_meta)
    my_rank = next((v.power_rank for v in all_vals if v.roster_id == mine.roster_id), None)
    val.power_rank = my_rank
    # Status thirds are over the ranked rosters (len(all_vals)), the same
    # denominator as TeamContext.num_teams, not the draft-settings team count.
    status = mode if mode in ("contend", "rebuild") else detect_status(my_rank, len(all_vals))

    pool = available(book, taken, position=position)
    if rookies:
        pool = [a for a in pool
                if (players_meta.get(str(a.id)) or {}).get("years_exp") == 0]
    ctx, fits = rank_fits(pool, val, all_vals, roster_positions, status, limit)

    badge = {"contend": "[green]CONTEND[/]", "rebuild": "[yellow]REBUILD[/]",
             "balanced": "[cyan]BALANCED[/]"}.get(status, status.upper())
    rank_txt = f"power rank {my_rank}/{len(all_vals)}" if my_rank else "power rank n/a"
    console.print(Panel.fit(f"[bold]{val.team_name}[/]   status: {badge}   {rank_txt}",
                            title="your team"))
    if not roster_positions:
        console.print("[dim]roster slots unknown - showing market-anchored fit.[/]")

    stt = Table(title="where you stand")
    for c in ("pos", "your startable", "league median", "gap"):
        stt.add_column(c, justify="right" if c != "pos" else "left")
    for s in ctx.standings:
        flag = " [yellow]thin[/]" if s.is_hole else ""
        stt.add_row(s.position, f"{s.mine:,}", f"{s.median:,}", f"{_signed(s.gap)}{flag}")
    console.print(stt)

    # recommended pick + best available FOR YOU
    if fits:
        top = fits[0]
        console.print(f"[bold green]recommend[/] -> [bold]{top.asset.name}[/] "
                      f"({top.asset.position or '-'}) - {top.why}")
    title = "best available - FOR YOU" + (f" - {position.upper()}" if position else "") + \
            (" (rookies)" if rookies else "")
    at = Table(title=title)
    right = ("fit#", "mkt#", "FitScore", "value", "30d", "posrk")
    for c in ("fit#", "player", "pos", "posrk", "mkt#", "FitScore", "value", "30d", "why"):
        at.add_column(c, justify="right" if c in right else "left")
    tep_on = cfg.format.tep > 0
    for i, f in enumerate(fits, 1):
        a = f.asset
        pos = (a.position or "-") + ("*" if tep_on and a.position == "TE" else "")
        posrk = f"{a.position}{a.position_rank}" if a.position_rank else "-"
        at.add_row(str(i), a.name, pos, posrk, str(f.market_rank),
                   f"{f.fit_score:,.0f}", f"{a.value:,}",
                   _signed(a.trend_30day) if a.trend_30day else "-", f.why)
    console.print(at)
    if tep_on:
        console.print(f"[dim]* TE value runs conservative: FantasyCalc has no TEP "
                      f"param, but your league scores +{cfg.format.tep:g} TEP, so TEs "
                      f"are worth a bit more than shown.[/]")
    console.print("[dim]FitScore = market value adjusted for YOUR roster fit + "
                  "win-now/rebuild horizon. mkt# is the raw dynasty-value rank. "
                  "The pick call is yours.[/]")


@app.command()
def ask(
    query: str = typer.Argument(..., help="Natural language question about your league"),
    backend: Optional[str] = typer.Option(None, "--backend", help="Override LLM backend (agy, gemini, claude, ollama)"),
) -> None:
    """Ask natural language questions about trades, lineups, waivers, or league setup."""
    cfg = load_config() if config_exists() else None
    target_backend = backend or (cfg.llm_backend if cfg else "auto")
    ollama_model = cfg.ollama_model if cfg else "llama3.2"

    runner_inst = TerminalRunner(backend=target_backend, ollama_model=ollama_model)
    system_prompt = f"You are an assistant for dynasty fantasy football. Available tools: {json.dumps(TOOL_SCHEMAS)}"

    response = runner_inst.run(prompt=query, system_prompt=system_prompt)
    console.print(Markdown(response))


@config_app.command(name="set-llm")
@_guard
def set_llm(
    backend: str = typer.Argument(..., help="LLM backend: auto, agy, gemini, claude, ollama"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Ollama model name (defaults to llama3.2)"),
) -> None:
    """Configure the LLM backend used by 'ff ask'."""
    if not config_exists():
        _fail("No league configured. Run 'ff setup <username>' first.")
    try:
        cfg = load_config()
    except FileNotFoundError:
        _fail("No league configured. Run 'ff setup <username>' first.")
    valid_backends = SUPPORTED_BACKENDS + ["auto"]
    if backend not in valid_backends:
        _fail(f"Invalid backend '{backend}'. Must be one of: {', '.join(valid_backends)}")
    cfg.llm_backend = backend
    if model:
        cfg.ollama_model = model
    path = save_config(cfg)
    console.print(f"[bold green]Updated LLM backend[/] to [cyan]{backend}[/]"
                  + (f" (model: [cyan]{model}[/])" if model else "")
                  + f"\nconfig: {path}")


@app.command()
def version() -> None:
    """Print the ff version."""
    console.print(f"ff {__version__}")


if __name__ == "__main__":
    app()
