"""ff command-line interface.

    ff setup <username>     pick your league, auto-detect its format, save it
    ff roster [team]        price out a roster, with power rank + positions
    ff power                league power rankings by dynasty value
    ff values [-p WR]       dynasty rankings for your format (FantasyPros killer)
    ff trade --give --get   analyze a trade (players + picks), with a fairness call
    ff waivers              trending free agents worth grabbing, by value
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
from rich.panel import Panel
from rich.table import Table

from ff import __version__
from ff.analysis import (
    analyze_trade,
    position_deltas,
    top_movers,
    value_all_rosters,
    value_roster,
    waiver_targets,
)
from ff.contracts import Format, Roster
from ff.core.config import Config, config_exists, load_config, save_config
from ff.sleeper import SleeperClient, build_rosters, detect_format
from ff.values import ValueBook, ValuesClient, normalize_name

app = typer.Typer(add_completion=False, help="Manage a Sleeper dynasty league with free data.")
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


# --- values / rankings ---------------------------------------------------

@app.command()
@_guard
def values(
    position: Optional[str] = typer.Option(None, "--position", "-p",
                                            help="QB/RB/WR/TE; omit for overall."),
    limit: int = typer.Option(40, help="How many to list."),
) -> None:
    """Dynasty rankings for your league format - the FantasyPros rankings page, free."""
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
                      f"[dim]- check spelling or use 'YEAR 1st' for picks[/]")
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
def version() -> None:
    """Print the ff version."""
    console.print(f"ff {__version__}")


if __name__ == "__main__":
    app()
