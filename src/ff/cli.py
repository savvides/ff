"""ff command-line interface.

    ff setup <username>     pick your league, auto-detect its format, save it
    ff plan                 your team on one page: stance, this week's to-dos, who to shop/target
    ff standings            playoff odds and projected draft slot, simulated
    ff fab                  waiver budgets left and what this league pays for claims
    ff offers --sell        packages for your asset that pass the offer rule
    ff roster [team]        price out a roster, with power rank + positions
    ff power                league power rankings by dynasty value
    ff picks [team]         future draft capital by team, tier-valued
    ff values [-p WR]       dynasty rankings for your league format
    ff trade --give --get   analyze a trade (players + picks), with a fairness call
    ff waivers              trending free agents worth grabbing, by value
    ff cleanup [team]       roster capacity: who to drop / move to IR / stash on taxi for room
    ff draft [-p QB] [-r]   live draft board: your picks + best available by value
"""

from __future__ import annotations

import functools
import inspect
import json
import re
import statistics
import subprocess
import sys
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, NoReturn, Optional, Sequence, Set, Tuple

import requests
import typer
from pydantic import ValidationError
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ff import __version__
from ff.analysis.fab import bid_summary, winning_bids
from ff.analysis.plan import buy_candidates, sell_candidates, trade_stance
from ff.analysis.compare import compare_players, resolve_player
from ff.analysis.weekly_waivers import weekly_waivers
from ff.analysis import (
    analyze_trade,
    offer_verdict,
    audit_roster,
    available,
    detect_status,
    find_arbitrage_movers,
    ir_eligible_statuses,
    my_picks,
    optimal_lineup,
    pick_ledger,
    position_deltas,
    secondary_position_deltas,
    projected_points,
    simulate_season,
    rank_fits,
    top_movers,
    value_all_rosters,
    value_roster,
    waiver_targets,
)
from ff.contracts import Asset, Lineup, Roster, RosterValuation, StandingProjection
from ff.contracts.models import PlayerComparison, WeeklyWaivers
from ff.core.config import Config, config_exists, load_config, save_config
from ff.projections import ProjectionsClient
from ff.qa import render_qa_footer, render_qa_full_report, run_qa
from ff.services.llm.dispatcher import dispatch_tool
from ff.services.llm.onboarding import onboard_user
from ff.services.llm.runner import SUPPORTED_BACKENDS, TerminalRunner
from ff.services.llm.tools import ALLOWED_TOOLS, TOOL_SCHEMAS
from ff.services.weekly import load_weekly
from ff.sleeper import SleeperClient, build_rosters, detect_format, player_name
from ff.values import ValueBook, ValuesClient, normalize_name, normalize_pick
from ff.values.calculators_live import check_calculators

app = typer.Typer(add_completion=False, help="Manage a Sleeper dynasty league with free data.")
config_app = typer.Typer(help="Manage configuration settings.")
app.add_typer(config_app, name="config")
console = Console()


# --- shared plumbing -----------------------------------------------------

def _fail(msg: str) -> NoReturn:
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
            _fail(f"could not reach a football data provider ({e}). Check your connection and retry.")
        except (ValidationError, json.JSONDecodeError):
            _fail("config is corrupt or out of date. Run `ff setup <sleeper-username>` to rebuild it.")
        except ValueError as e:
            _fail(str(e))

    wrapper.__signature__ = inspect.signature(fn)  # type: ignore[attr-defined]  # keep Typer's option parsing
    return wrapper


def _load() -> Tuple[Config, SleeperClient]:
    if not config_exists():
        _fail("no league configured. Run `ff setup <sleeper-username>` first.")
    cfg = load_config()
    sc = SleeperClient()
    try:
        league = sc.league(cfg.league_id)
        if league:
            fresh_fmt = detect_format(league)
            if fresh_fmt != cfg.format:
                cfg.format = fresh_fmt
                try:
                    save_config(cfg)
                except Exception:
                    pass
    except Exception:
        pass
    return cfg, sc


def _book(cfg: Config, include_secondary: bool = True, include_ktc: bool = True,
          fresh: bool = False, sc: Optional[SleeperClient] = None) -> ValueBook:
    fmt = cfg.format
    if sc is not None:
        try:
            league = sc.league(cfg.league_id)
            if league:
                fmt = detect_format(league)
        except Exception:
            pass
    client = ValuesClient()
    should_include = include_secondary and include_ktc
    try:
        return client.fetch(fmt, include_secondary=should_include, fresh=fresh)
    except TypeError:
        return client.fetch(fmt, include_ktc=should_include)


def _league_rosters(cfg: Config, sc: SleeperClient) -> List[Roster]:
    return build_rosters(sc.rosters(cfg.league_id), sc.league_users(cfg.league_id))


def _trending_adds(sc: SleeperClient, limit: int) -> List[Dict[str, Any]]:
    """Trending-add candidates for waiver ranking: three per requested row, at least 50."""
    return sc.trending(kind="add", limit=max(limit * 3, 50))


def _pick_window(sc: SleeperClient, cfg: Config, league: Dict[str, Any],
                 years: int = 2, rounds: Optional[int] = None) -> Tuple[List[str], int]:
    """(future seasons, rookie rounds per season) for a pick ledger."""
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
    return seasons, rounds_n


def _season_sim(cfg: Config, sc: SleeperClient, league: Dict[str, Any],
                rosters: List[Roster]) -> List[StandingProjection]:
    """Simulated rest of the regular season; empty before the first game."""
    settings = league.get("settings") or {}
    median = bool(settings.get("league_average_match"))
    done = max((r.wins + r.losses + r.ties for r in rosters), default=0) // (2 if median else 1)
    if not done:
        return []
    start = int(settings.get("start_week") or 1)
    end = int(settings.get("playoff_week_start") or 15)
    scores: Dict[int, List[float]] = {r.roster_id: [] for r in rosters}
    remaining = []
    for week in range(start, end):
        final = week < start + done
        rows = sc.matchups(cfg.league_id, week, ttl=24 * 3600 if final else 1800)
        games: Dict[int, List[int]] = {}
        for m in rows:
            if m.get("matchup_id") is None or m.get("roster_id") not in scores:
                continue
            if final:
                scores[m["roster_id"]].append(float(m.get("points") or 0))
            else:
                games.setdefault(m["matchup_id"], []).append(m["roster_id"])
        if not final:
            remaining.append([(g[0], g[1]) for g in games.values() if len(g) == 2])
    return simulate_season(rosters, scores, remaining, median_game=median,
                           playoff_teams=int(settings.get("playoff_teams") or 6))


def _finish_ranks(sim: List[StandingProjection],
                  valuations: List[RosterValuation]) -> Tuple[Dict[int, Optional[int]], str]:
    """({roster_id: expected finish, 1 = best}, basis) for tiering next year's
    picks: the simulated draft order once games exist, else roster value."""
    if sim:
        order = sorted(sim, key=lambda p: p.draft_slot, reverse=True)
        return {p.roster_id: i for i, p in enumerate(order, 1)}, "projected finish"
    return {v.roster_id: v.power_rank for v in valuations}, "power rank"


def _current_week(state: Dict[str, Any]) -> int:
    """The NFL week whose lineup is still open: the later of Sleeper's `week` and
    `display_week`, never below 1.

    The two flip at different times around the turn of a week, in either order
    (Sleeper returned week 4 / display_week 3 on Tuesday 2026-09-29, after week 3
    ended; its docs example shows week 2 / display_week 3), so neither is safe alone.
    """
    return max(1, int(state.get("week") or 0), int(state.get("display_week") or 0))


class _LazyContext(dict):
    """Lazy evaluation context for LLM dispatcher tools to avoid eager network/cache reads."""

    def __init__(self, cfg: Config, sc: SleeperClient, include_secondary: bool = True):
        super().__init__()
        self["config"] = cfg
        self["onboard_user"] = onboard_user
        self["season"] = str(cfg.season)
        self._cfg = cfg
        self._sc = sc
        self._include_secondary = include_secondary
        self._cache: Dict[str, Any] = {}

    def _get_league(self) -> Dict[str, Any]:
        if "_league" not in self._cache:
            self._cache["_league"] = self._sc.league(self._cfg.league_id) or {}
        return self._cache["_league"]

    def _get_state(self) -> Dict[str, Any]:
        if "_state" not in self._cache:
            self._cache["_state"] = self._sc.state() or {}
        return self._cache["_state"]

    def _get_pick_window(self) -> Tuple[List[str], int]:
        # One drafts read (uncached upstream) serves both 'seasons' and 'rounds'.
        if "_pick_window" not in self._cache:
            self._cache["_pick_window"] = _pick_window(self._sc, self._cfg, self._get_league())
        return self._cache["_pick_window"]

    def __getitem__(self, key: str) -> Any:
        if key in self:
            return super().__getitem__(key)
        val = self._compute(key)
        self[key] = val
        return val

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def _compute(self, key: str) -> Any:
        if key == "prepare_weekly":
            return lambda team: _prepare_weekly(self, team)
        if key == "rosters":
            return _league_rosters(self._cfg, self._sc)
        elif key == "value_book":
            return _book(self._cfg, include_secondary=self._include_secondary, sc=self._sc)
        elif key == "players_meta":
            return self._sc.players()
        elif key == "projections":
            week = self["week"]
            season = str(self._cfg.season)
            try:
                return ProjectionsClient().week(season, week)
            except Exception:
                return {}
        elif key == "scoring":
            return self._get_league().get("scoring_settings") or {}
        elif key == "roster_positions":
            return self._get_league().get("roster_positions") or []
        elif key == "traded_picks":
            return self._sc.traded_picks(self._cfg.league_id)
        elif key == "season_sim":
            return _season_sim(self._cfg, self._sc, self._get_league(), self["rosters"])
        elif key == "seasons":
            return self._get_pick_window()[0]
        elif key == "rounds":
            return self._get_pick_window()[1]
        elif key == "week":
            state = self._get_state()
            return _current_week(state)
        elif key == "taxi_slots":
            settings = self._get_league().get("settings") or {}
            return int(settings.get("taxi_slots") or 0)
        elif key == "reserve_slots":
            settings = self._get_league().get("settings") or {}
            return int(settings.get("reserve_slots") or 0)
        elif key == "taxi_allow_vets":
            settings = self._get_league().get("settings") or {}
            return bool(settings.get("taxi_allow_vets"))
        elif key == "taxi_years":
            settings = self._get_league().get("settings") or {}
            return settings.get("taxi_years")
        elif key == "ir_statuses":
            return ir_eligible_statuses(self._get_league().get("settings") or {})
        raise KeyError(key)


def _analysis_ctx(cfg: Config, sc: SleeperClient, include_secondary: bool = True) -> _LazyContext:
    """I/O bundle the LLM dispatcher needs so tools see the same data as `ff` commands."""
    return _LazyContext(cfg, sc, include_secondary)


def _prepare_weekly(ctx: _LazyContext, team: Optional[str]) -> Roster:
    """Refresh one consistent current-week snapshot for every weekly entry point."""
    cfg, sc = ctx._cfg, ctx._sc
    ctx._cache["_state"] = state = sc.state(fresh=True) or {}
    ctx._cache["_league"] = sc.league(cfg.league_id, fresh=True)
    ctx["week"] = _current_week(state)
    if str(state.get("season")) != str(cfg.season):
        raise ValueError("The configured season is not current. Run `ff setup <username>`.")
    if ctx._get_league().get("season_type", "regular") != "regular":
        raise ValueError("Weekly advice supports regular-season leagues only.")
    ctx["rosters"] = build_rosters(sc.rosters(cfg.league_id, fresh=True), sc.league_users(cfg.league_id))
    target = next((r for r in ctx["rosters"] if str(r.roster_id) == team), None)
    if target is None:
        target = _pick_roster(ctx["rosters"], team, cfg.user_id)
    if target is None:
        raise ValueError("Could not find that team in the fresh roster snapshot.")
    candidates = None
    if ctx.get("weekly_candidates", False):
        ctx["projections"], candidates = ProjectionsClient().snapshot(str(cfg.season), ctx["week"], fresh=True)
    else:
        ctx["projections"] = ProjectionsClient().week(str(cfg.season), ctx["week"], fresh=True)
    if not ctx["projections"]:
        raise ValueError(f"No projections available for {cfg.season} week {ctx['week']}.")
    ctx["weekly"], ctx["players_meta"] = load_weekly(
        sc, cfg.league_id, target, str(cfg.season), ctx["week"], ctx._get_league(), ctx["players_meta"], candidate_meta=candidates)
    ctx["weekly_team"] = str(target.roster_id)
    return target


def _signed(n: int) -> str:
    return f"+{n:,}" if n > 0 else f"{n:,}"


_KTC_DOWN = "KeepTradeCut values are unavailable right now"


def _has_ktc(book: ValueBook) -> bool:
    return any(a.secondary_value is not None for a in book.assets)


def _ktc_site_verdict(evaluation: Any) -> str:
    """KTC's own verdict wording: 'Fair Trade', or who it favors, on its measure (the
    gap as a share of both sides, fair at 5% or less)."""
    site_pct = evaluation.secondary_site_pct or 0.0
    larger = evaluation.secondary_pct_diff or 0.0
    if evaluation.secondary_is_fair():
        return f"[bold yellow]Fair Trade[/] ({site_pct:.1f}% of both sides)"
    who = "you" if (evaluation.secondary_delta or 0) > 0 else "them"
    color = "green" if who == "you" else "red"
    return (f"[bold {color}]favors {who}[/] by {abs(evaluation.secondary_delta or 0):,} "
            f"({larger:.1f}% of the larger side; {site_pct:.1f}% of both)")


def _print_offer_rule(evaluation: Any, book: ValueBook) -> None:
    """The offer rule on site-matching numbers, or why it cannot be judged."""
    problems = check_calculators(book.secondary_html)
    v = offer_verdict(evaluation, calculator_problems=problems)
    rule = f"under {v.threshold_pct:g}% in FantasyCalc and KTC, and KTC says Fair"
    if v.status == "CANNOT_JUDGE":
        console.print(f"[bold yellow]offer rule: cannot judge[/] ({rule}): " + "; ".join(v.reasons))
    else:
        mark = "[bold green]PASS[/]" if v.passes else "[bold red]FAIL[/]"
        console.print(f"offer rule: {mark} ({rule}): FC {v.fc_pct:.2f}%, KTC {v.ktc_pct:.2f}%, "
                      f"KTC site {'Fair' if v.ktc_site_fair else 'Favors one side'}")


def _print_provenance(book: ValueBook, cfg: Config, include_secondary: bool) -> None:
    """Where the numbers came from, so nobody has to go check the sites."""
    def at(ts: Optional[float]) -> str:
        return datetime.fromtimestamp(ts).strftime("%H:%M") if ts else "?"
    fmt = cfg.format
    fc_tep = fmt.fantasycalc_tep()
    parts = [f"FantasyCalc {at(book.fetched_at)} ({fmt.label()}" + (f", tep={fc_tep}" if fc_tep else "") + ")"]
    if include_secondary and book.secondary_top:
        tier = ["", " TE+", " TE++"][fmt.ktc_tep_tier()]
        parts.append(f"KTC {at(book.secondary_fetched_at)} ({'SF' if fmt.superflex else '1QB'}{tier}, "
                     f"top {book.secondary_top:,})")
    console.print("[dim]values: " + " | ".join(parts) + "[/]")


def _ktc_missing(book: ValueBook) -> str:
    """Why a KTC number is missing, so a FantasyCalc-only fallback is never silent."""
    if _has_ktc(book):
        return "KeepTradeCut has no value for part of this; showing FantasyCalc only."
    return f"{_KTC_DOWN}; showing FantasyCalc only."


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
    season_val = str(season or sc.state().get("season") or "")

    # Always resolve the user so user_id is saved even when --league-id is given;
    # otherwise `ff roster` cannot tell which team is yours.
    user = sc.user(username)
    raw_uid = user.get("user_id") if user else None
    if not raw_uid:
        _fail(f"no Sleeper user named '{username}'.")
    user_id = str(raw_uid)

    if not league_id:
        leagues = sc.user_leagues(user_id, season_val)
        if not leagues:  # offseason: this season's leagues may not exist yet
            prev = sc.state().get("previous_season")
            if prev:
                season_val = str(prev)
                leagues = sc.user_leagues(user_id, season_val)
        if not leagues:
            _fail(f"no leagues for '{username}' in {season_val}.")
        if len(leagues) == 1:
            chosen = leagues[0]
        elif league_index is not None:
            if league_index < 0 or league_index >= len(leagues):
                _fail(f"--league-index {league_index} out of range (0-{len(leagues) - 1}).")
            chosen = leagues[league_index]
        else:
            console.print(f"[bold]{username}[/] is in {len(leagues)} leagues for {season_val}:")
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
    if not league:
        _fail(f"could not find Sleeper league with id '{league_id}'.")
    if not season and league.get("season"):
        season_val = str(league["season"])
    fmt = detect_format(league)
    cfg = Config(
        league_id=league_id,
        season=int(season_val),
        name=league.get("name", ""),
        league_name=league.get("name", ""),
        format=fmt,
        username=username,
        user_name=username,
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
    qa_rep = run_qa("setup", config=cfg)
    render_qa_footer(qa_rep, console)


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
    book = _book(cfg, include_secondary=False)
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
    pos_table.add_column("pos")
    pos_table.add_column("value", justify="right")
    for pos, v in sorted(val.by_position.items(), key=lambda x: x[1], reverse=True):
        if v:
            pos_table.add_row(pos, f"{v:,}")
    console.print(pos_table)

    t = Table(title=f"top {top} assets")
    for c in ("player", "pos", "role", "age", "value", "ovr", "30d"):
        t.add_column(c, justify="right" if c in ("value", "ovr", "30d", "age") else "left")
    for a in val.assets[:top]:
        name_cell = f"{a.name} [bold red]{a.injury_tag}[/]" if a.injury_tag else a.name
        t.add_row(name_cell, a.position or "-", a.depth_role,
                  f"{a.age:.0f}" if a.age else "-", f"{a.value:,}",
                  str(a.overall_rank or "-"),
                  _signed(a.trend_30day) if a.trend_30day else "-")
    console.print(t)
    if val.unvalued:
        console.print(f"[dim]{len(val.unvalued)} unvalued (K/DEF/deep bench) not shown.[/]")
    console.print("[dim]value counts rostered players only, not your draft picks.[/]")
    qa_rep = run_qa("roster", valuation=val, target_roster=target)
    render_qa_footer(qa_rep, console)


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
    book = _book(cfg, include_secondary=False)
    rosters = _league_rosters(cfg, sc)
    valuations = value_all_rosters(rosters, book, sc.players())
    by_id = {r.roster_id: r for r in rosters}

    league = sc.league(cfg.league_id) or {}
    sim = _season_sim(cfg, sc, league, rosters)
    seasons, rounds_n = _pick_window(sc, cfg, league, 3)
    ledger = pick_ledger(rosters, sc.traded_picks(cfg.league_id), book,
                         _finish_ranks(sim, valuations)[0], seasons=seasons, rounds=rounds_n)
    pick_value = {tp.roster_id: tp.total_value for tp in ledger}
    total = {v.roster_id: v.total_value + pick_value.get(v.roster_id, 0) for v in valuations}
    total_rank = {rid: i for i, rid in enumerate(sorted(total, key=lambda k: -total[k]), 1)}

    t = Table(title=f"{cfg.name} - power rankings ({cfg.format.label()})")
    for c in ("#", "team", "players", "picks", "total", "total #", "record", "pts for"):
        t.add_column(c, justify="left" if c in ("team", "record") else "right")
    for v in valuations:
        r = by_id[v.roster_id]
        t.add_row(str(v.power_rank), v.team_name, f"{v.total_value:,}",
                  f"{pick_value.get(v.roster_id, 0):,}", f"{total[v.roster_id]:,}",
                  str(total_rank[v.roster_id]),
                  f"{r.wins}-{r.losses}" + (f"-{r.ties}" if r.ties else ""),
                  f"{r.points_for:.0f}")
    console.print(t)
    console.print(f"[dim]# ranks rostered players (who wins now); picks = {seasons[0]}-{seasons[-1][2:]} "
                  "draft capital (`ff picks`); total = both, the long-run asset base. "
                  "Playoff odds: `ff standings`.[/]")
    qa_rep = run_qa("power", valuations=valuations, rosters=rosters)
    render_qa_footer(qa_rep, console)


# --- standings -----------------------------------------------------------

@app.command()
@_guard
def standings() -> None:
    """Standings with simulated playoff odds and projected rookie-draft slot."""
    cfg, sc = _load()
    league = sc.league(cfg.league_id) or {}
    rosters = _league_rosters(cfg, sc)
    sim = _season_sim(cfg, sc, league, rosters)
    if not sim:
        _fail("no games played yet this season; standings start after week 1.")
    by_id = {r.roster_id: r for r in rosters}
    settings = league.get("settings") or {}
    t = Table(title=f"{cfg.name} - standings and outlook")
    for c in ("#", "team", "record", "pts for", "exp wins", "playoffs", "draft slot"):
        t.add_column(c, justify="left" if c in ("team", "record") else "right")
    for i, p in enumerate(sim, 1):
        r = by_id[p.roster_id]
        mine = r.owner_id == cfg.user_id
        t.add_row(str(i), f"[bold]{p.team_name}[/]" if mine else p.team_name,
                  f"{r.wins}-{r.losses}" + (f"-{r.ties}" if r.ties else ""),
                  f"{r.points_for:.0f}", f"{p.exp_wins:.1f}",
                  f"{p.playoff_odds:.0%}", f"{p.draft_slot:.1f}")
    console.print(t)
    console.print(f"[dim]4,000 simulated finishes of the regular season (playoffs start week "
                  f"{settings.get('playoff_week_start', '?')}, {settings.get('playoff_teams', '?')} teams): "
                  "each team scores around its points per game, regressed toward the league "
                  "average. Draft slot assumes reverse order of standings, playoff teams last; "
                  "it sets early/mid/late pick prices in `ff picks`.[/]")


# --- plan ----------------------------------------------------------------

@app.command()
@_guard
def plan() -> None:
    """Your team in one page: where you stand and what to do about it now."""
    cfg, sc = _load()
    ctx = _analysis_ctx(cfg, sc, include_secondary=False)
    league = ctx._get_league()
    settings = league.get("settings") or {}
    rosters: List[Roster] = ctx["rosters"]
    me = _pick_roster(rosters, None, cfg.user_id)
    if me is None:
        _fail("your team is unknown. Re-run `ff setup <username>`.")
    book: ValueBook = ctx["value_book"]
    meta = ctx["players_meta"]
    valuations = value_all_rosters(rosters, book, meta)
    mine = next(v for v in valuations if v.roster_id == me.roster_id)
    sim = ctx["season_sim"]
    outlook = next((p for p in sim if p.roster_id == me.roster_id), None)
    ledger = pick_ledger(rosters, ctx["traded_picks"], book, _finish_ranks(sim, valuations)[0],
                         seasons=_pick_window(sc, cfg, league, 3)[0], rounds=ctx["rounds"])
    pick_rank = next(i for i, tp in enumerate(ledger, 1) if tp.roster_id == me.roster_id)
    my_picks_value = ledger[pick_rank - 1].total_value
    stance = trade_stance(mine.power_rank, len(rosters), outlook.playoff_odds if outlook else None)
    week = ctx["week"]
    deadline = int(settings.get("trade_deadline") or 0)
    budget = int(settings.get("waiver_budget") or 0)

    head = [f"[bold]{me.team_name}[/]   {me.wins}-{me.losses}" + (f"-{me.ties}" if me.ties else "")]
    if outlook:
        head.append(f"playoff odds [bold]{outlook.playoff_odds:.0%}[/]   expected wins "
                    f"{outlook.exp_wins:.1f}   projected draft slot [bold]{outlook.draft_slot:.1f}[/]")
    head.append(f"players {mine.total_value:,} (#{mine.power_rank}/{len(rosters)})   "
                f"picks {my_picks_value:,} (#{pick_rank}/{len(rosters)})")
    head.append(f"stance: [bold cyan]{stance}[/] - " + {
        "seller": "this season will not end in a title; turn points you cannot use into future value",
        "buyer": "you are in the hunt; turn future value into points now",
        "hold": "neither clearly in nor out; do not pay for either direction yet"}[stance])
    console.print(Panel.fit("\n".join(head), title=f"plan - week {week}"))

    console.print("[bold]this week[/]")
    try:
        target = _prepare_weekly(ctx, None)
        lu = optimal_lineup(target, ctx["projections"], ctx["scoring"], ctx["roster_positions"],
                            ctx["players_meta"], season=str(cfg.season), week=week, weekly=ctx["weekly"])
        empty = sum(p == "0" for p in target.starters)
        swaps = len({s.player_id for s in lu.slots if s.player_id} - set(target.starters))
        if empty or swaps:
            console.print(f"  [yellow]lineup:[/] {swaps} better starter(s) on your bench"
                          + (f", {empty} empty starting slot(s)" if empty else "") + " - run `ff lineup`")
        else:
            console.print("  [green]lineup:[/] already optimal")
        for w in lu.warnings:
            if w.startswith("IR lock:"):
                console.print(f"  [red]{w}[/]")
    except (ValueError, requests.RequestException) as e:
        console.print(f"  [dim]lineup check unavailable: {e}[/]")
    audit = audit_roster(
        me, book, meta, roster_positions=league.get("roster_positions") or [],
        taxi_slots=int(settings.get("taxi_slots") or 0), reserve_slots=int(settings.get("reserve_slots") or 0),
        taxi_allow_vets=bool(settings.get("taxi_allow_vets")), taxi_years=settings.get("taxi_years"),
        is_superflex=bool(cfg.format.superflex), ir_statuses=ir_eligible_statuses(settings))
    for label, moves in (("IR", audit.ir_candidates), ("taxi", audit.taxi_candidates)):
        if moves:
            console.print(f"  [yellow]free roster room:[/] move {', '.join(s.name for s in moves)} to {label}")
    if budget:
        left = sorted(((budget - r.fab_used, r.team_name) for r in rosters), reverse=True)
        console.print(f"  waiver budget: ${budget - me.fab_used} left of ${budget} "
                      f"(most in the league: ${left[0][0]}, {left[0][1]}) - bid history in `ff fab`")

    console.print("[bold]trades[/]")
    if deadline and week > deadline:
        console.print(f"  [dim]the trade deadline (week {deadline}) has passed; this is your offseason list.[/]")
    elif deadline:
        console.print(f"  trade deadline: week {deadline} ({deadline - week + 1} lineup week(s) left, this one included)")
    owner = {pid: r.team_name for r in rosters for pid in r.player_ids}
    sells = sell_candidates(mine.assets, stance)
    # Deal with teams going the other way: a seller's partners are the buyers.
    odds = {p.roster_id: p.playoff_odds for p in sim}
    other = {"seller": "buyer", "buyer": "seller"}.get(stance)
    partners = [r for v in valuations for r in rosters if r.roster_id == v.roster_id != me.roster_id
                and trade_stance(v.power_rank, len(rosters), odds.get(v.roster_id)) == other]
    partner_ids = {pid for r in (partners or [r for r in rosters if r is not me]) for pid in r.player_ids}
    buys = buy_candidates(book, {a.id for a in book.assets} - partner_ids, stance)
    for title, rows, col in (("shop these", sells, None),
                             (f"target these (on {other} rosters)", buys, "owner")):
        if not rows:
            continue
        t = Table(title=title, title_justify="left")
        for c in ("player", "pos", "age", "value", "win-now", *([col] if col else []), "why"):
            t.add_column(c, justify="right" if c in ("age", "value", "win-now") else "left")
        for a, why in rows:
            t.add_row(a.name, a.position or "-", f"{a.age:.0f}" if a.age else "-", f"{a.value:,}",
                      f"{a.redraft_value:,}" if a.redraft_value else "-",
                      *([owner.get(a.id, "free agent")] if col else []), why)
        console.print(t)
    if not sells and not buys:
        console.print("  [dim]nothing on your roster or the market stands out for your stance.[/]")
    console.print("[dim]value = FantasyCalc dynasty value; win-now = its redraft value on the same scale. "
                  "Price any deal with `ff trade`. Stance uses `ff standings` odds once games exist, "
                  "else roster rank. ff is read-only.[/]")


# --- fab -----------------------------------------------------------------

def _fab_claims(cfg: Config, sc: SleeperClient) -> list:
    week = _current_week(sc.state() or {})
    return winning_bids([row for w in range(week + 1) for row in sc.transactions(cfg.league_id, w)])


@app.command()
@_guard
def fab(limit: int = typer.Option(12, help="How many recent contested claims to list.")) -> None:
    """Waiver budgets left and what this league has actually paid for claims."""
    cfg, sc = _load()
    league = sc.league(cfg.league_id) or {}
    budget = int((league.get("settings") or {}).get("waiver_budget") or 0)
    if (league.get("settings") or {}).get("waiver_type") != 2 or not budget:
        _fail("this league does not use a waiver budget (FAB).")
    rosters = _league_rosters(cfg, sc)
    meta = sc.players()
    claims = _fab_claims(cfg, sc)
    names = {r.roster_id: r.team_name for r in rosters}

    t = Table(title=f"waiver budgets (of ${budget})")
    for c in ("team", "left", "spent"):
        t.add_column(c, justify="left" if c == "team" else "right")
    for r in sorted(rosters, key=lambda r: r.fab_used):
        mine = r.owner_id == cfg.user_id
        t.add_row(f"[bold]{r.team_name}[/]" if mine else r.team_name,
                  f"${budget - r.fab_used}", f"${r.fab_used}")
    console.print(t)

    if not claims:
        console.print("[dim]no waiver bids recorded this season yet.[/]")
        return
    t = Table(title="winning bids this season")
    for c in ("group", "claims", "median", "75th pct", "max"):
        t.add_column(c, justify="left" if c == "group" else "right")
    groups = [("all", claims), ("contested", [c for c in claims if c.bidders > 1])]
    groups += [(pos, [c for c in claims if (meta.get(c.player_id) or {}).get("position") == pos])
               for pos in ("QB", "RB", "WR", "TE")]
    for label, group in groups:
        s = bid_summary([c.bid for c in group])
        if s:
            t.add_row(label, str(s["n"]), f"${s['median']:g}", f"${s['p75']:g}", f"${s['max']:g}")
    console.print(t)

    all_contested = [c for c in claims if c.runner_up is not None]
    contested = all_contested[:limit]
    if contested:
        t = Table(title="recent contested claims")
        for c in ("wk", "player", "pos", "winner", "bid", "next best", "bidders"):
            t.add_column(c, justify="right" if c in ("bid", "next best", "bidders", "wk") else "left")
        for c in contested:
            t.add_row(str(c.week), player_name(c.player_id, meta),
                      (meta.get(c.player_id) or {}).get("position") or "-",
                      names.get(c.roster_id, "?"), f"${c.bid}", f"${c.runner_up}", str(c.bidders))
        console.print(t)
        over = statistics.median(c.bid - (c.runner_up or 0) for c in all_contested)
        console.print(f"[dim]winners of contested claims paid a median ${over:g} more than they needed to.[/]")
    console.print("[dim]Sleeper shows a losing bid only when another team won the player, so "
                  "uncontested claims have no 'next best'. A rival can never bid more than "
                  "their budget left. ff is read-only; place bids in Sleeper.[/]")


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
    book = _book(cfg, include_secondary=False)
    rosters = _league_rosters(cfg, sc)
    league = sc.league(cfg.league_id) or {}
    seasons, rounds_n = _pick_window(sc, cfg, league, years, rounds)

    valuations = value_all_rosters(rosters, book, sc.players())
    ranks, basis = _finish_ranks(_season_sim(cfg, sc, league, rosters), valuations)
    traded = sc.traded_picks(cfg.league_id)
    ledger = pick_ledger(rosters, traded, book, ranks,
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
    console.print("[dim]picks only - players are `ff power`. Picks FantasyCalc tiers are priced "
                  f"early/mid/late by the ORIGINAL team's {basis} (a bad team's own "
                  "1st is an early one; see `ff standings`); other picks use the flat round value; "
                  "0 = FantasyCalc does not price that round. This year's board: "
                  "`ff draft`.[/]")
    qa_rep = run_qa("picks", ledger=ledger, rosters=rosters, traded_picks=traded)
    render_qa_footer(qa_rep, console)


# --- values / rankings ---------------------------------------------------

@app.command()
@_guard
def values(
    position: Optional[str] = typer.Option(None, "--position", "-p",
                                            help="QB/RB/WR/TE; omit for overall."),
    limit: int = typer.Option(40, help="How many to list."),
    market: str = typer.Option("both", "--market", "-m",
                               help="Market: fc, ktc, or both (default: both)."),
) -> None:
    """Dynasty rankings for your league format."""
    market = market.lower()
    if market not in ("fc", "dealer", "ktc", "both"):
        _fail("--market must be fc, ktc, or both.")

    cfg, sc = _load()
    include_secondary = market != "fc"
    book = _book(cfg, include_secondary=include_secondary)

    if market in ("dealer", "ktc"):
        pool = [a for a in book.assets if not a.is_pick]
        if position:
            pool = [a for a in pool if a.position == position.upper()]
        assets = sorted(pool, key=lambda a: a.secondary_value or 0, reverse=True)[:limit]
    else:
        assets = book.top(position, limit)

    has_secondary = any(a.secondary_value is not None for a in assets)
    dual_market = market == "both" and has_secondary

    title = f"dynasty rankings - {cfg.format.label()}" + (f" - {position.upper()}" if position else "")
    if market in ("dealer", "ktc"):
        title += " - KeepTradeCut"

    t = Table(title=title)
    if dual_market:
        right: Set[str] = {"FC", "KTC", "30d", "age", "#", "posrk"}
        for c in ("#", "player", "pos", "posrk", "team", "age", "FC", "KTC", "30d"):
            t.add_column(c, justify="right" if c in right else "left")
        for i, a in enumerate(assets, 1):
            posrk = f"{a.position}{a.position_rank}" if a.position_rank else "-"
            sec_str = f"{a.secondary_value:,}" if a.secondary_value is not None else "-"
            t.add_row(str(i), a.name, a.position or "-", posrk, a.team or "-",
                      f"{a.age:.0f}" if a.age else "-", f"{a.value:,}",
                      sec_str,
                      _signed(a.trend_30day) if a.trend_30day else "-")
    elif market in ("dealer", "ktc"):
        right = {"KTC", "30d", "age", "#", "posrk"}
        for c in ("#", "player", "pos", "posrk", "team", "age", "KTC", "30d"):
            t.add_column(c, justify="right" if c in right else "left")
        for i, a in enumerate(assets, 1):
            posrk = f"{a.position}{a.position_rank}" if a.position_rank else "-"
            sec_str = f"{a.secondary_value:,}" if a.secondary_value is not None else "-"
            t.add_row(str(i), a.name, a.position or "-", posrk, a.team or "-",
                      f"{a.age:.0f}" if a.age else "-", sec_str,
                      _signed(a.trend_30day) if a.trend_30day else "-")
    else:
        right = {"value", "30d", "age", "#", "posrk"}
        for c in ("#", "player", "pos", "posrk", "team", "age", "value", "30d"):
            t.add_column(c, justify="right" if c in right else "left")
        for i, a in enumerate(assets, 1):
            posrk = f"{a.position}{a.position_rank}" if a.position_rank else "-"
            t.add_row(str(i), a.name, a.position or "-", posrk, a.team or "-",
                      f"{a.age:.0f}" if a.age else "-", f"{a.value:,}",
                      _signed(a.trend_30day) if a.trend_30day else "-")
    console.print(t)
    if market != "fc" and not has_secondary:
        console.print(f"[yellow]{_ktc_missing(book)}[/]")
    qa_rep = run_qa("values", assets=assets, position=position, market=market)
    render_qa_footer(qa_rep, console)


# --- trade ---------------------------------------------------------------

@app.command()
@_guard
def trade(
    give: str = typer.Option(..., "--give", help="What you send, comma-separated."),
    get: str = typer.Option(..., "--get", help="What you receive, comma-separated."),
    market: str = typer.Option("both", "--market", "-m",
                               help="Market: fc, ktc, or both (default: both)."),
) -> None:
    """Analyze a trade. Players and picks both count (e.g. --get '2027 1st')."""
    market = market.lower()
    if market not in ("fc", "dealer", "ktc", "both"):
        _fail("--market must be fc, ktc, or both.")

    cfg, sc = _load()
    include_secondary = market != "fc"
    # Live values for both markets: a verdict should match what the sites show now.
    book = _book(cfg, include_secondary=include_secondary, fresh=True)
    give_tokens = [t for t in give.split(",") if t.strip()]
    get_tokens = [t for t in get.split(",") if t.strip()]
    # Surface any non-exact (fuzzy/surname) match so a substitution is never silent.
    subs = []
    for tok in get_tokens + give_tokens:
        a = book.resolve(tok)
        if a and not a.is_pick and normalize_name(tok) != normalize_name(a.name):
            subs.append((tok.strip(), a.name))
    # side_a = what you receive, side_b = what you give: delta>0 means you win.
    players_meta = sc.players()
    evaluation, unresolved = analyze_trade(
        get_tokens, give_tokens, book, labels=("You get", "You give"),
        include_secondary=include_secondary,
        players_meta=players_meta,
    )

    def _fmt_trade_asset(a: Asset, val: Optional[int]) -> str:
        lbl = (f" [{a.depth_tag}]" if a.depth_tag else "") + (f" {a.injury_tag}" if a.injury_tag else "")
        val_str = f"{val:,}" if val is not None else "unpriced"
        return f"{a.name}{lbl} ({val_str})"

    has_secondary = (
        evaluation.secondary_value_a is not None
        and evaluation.secondary_value_b is not None
    )
    dual_market = market == "both" and has_secondary

    # With KTC unable to price the trade, fall back to FantasyCalc's columns so the
    # table always shows the numbers the verdict below is computed from.
    show_fc = market in ("fc", "both") or not has_secondary
    show_ktc = market != "fc" and has_secondary
    table = Table(title="trade")
    table.add_column("side")
    table.add_column("assets")
    if show_fc:
        table.add_column("FC", justify="right")
    if show_ktc:
        table.add_column("KTC", justify="right")
    for label, style, side in (("You get", "green", evaluation.side_a),
                               ("You give", "red", evaluation.side_b)):
        cells = [f"[{style}]{label}[/]", ", ".join(
            _fmt_trade_asset(x, x.value if show_fc else x.secondary_value) for x in side.assets) or "-"]
        if show_fc:
            cells.append(f"{side.total:,}")
        if show_ktc:
            cells.append(f"{side.secondary_total:,}" if side.secondary_total is not None else "-")
        table.add_row(*cells)
        fc_adj = side.adjustment if show_fc else None
        ktc_adj = side.secondary_adjustment if show_ktc else None
        if fc_adj or ktc_adj:
            adj = ["", "[dim]+ site package adjustment[/]"]
            tot = ["", "[bold]= site total[/]"]
            if show_fc:
                adj.append(f"+{fc_adj:,}" if fc_adj else "")
                tot.append(f"[bold]{side.adjusted_total:,}[/]")
            if show_ktc:
                adj.append(f"{ktc_adj:+,}" if ktc_adj else "")
                sec_total = side.secondary_adjusted_total
                tot.append(f"[bold]{sec_total:,}[/]" if sec_total is not None else "-")
            table.add_row(*adj)
            table.add_row(*tot)
    console.print(table)
    if market != "fc" and not has_secondary:
        console.print(f"[yellow]{_ktc_missing(book)}[/]")
    if show_ktc and evaluation.secondary_hidden:
        console.print("[dim]KTC counts its value adjustment in the verdict but hides it on its "
                      "page, where the team totals show the raw sums.[/]")

    if dual_market:
        net_fc = evaluation.delta
        pct_fc = evaluation.pct_diff
        if evaluation.is_fair():
            verdict_fc = f"[bold yellow]fair[/] - within {pct_fc:.0f}%"
        elif net_fc > 0:
            verdict_fc = f"[bold green]you win[/] by {_signed(net_fc)} ({pct_fc:.0f}%)"
        else:
            verdict_fc = f"[bold red]you lose[/] by {_signed(net_fc)} ({pct_fc:.0f}%)"

        sec_net = evaluation.secondary_delta or 0
        verdict_sec = _ktc_site_verdict(evaluation)

        arb_label = evaluation.secondary_arbitrage_label()
        banner_lines = [
            f"FC:     net {_signed(net_fc)} value to you   |   {verdict_fc}",
            f"KTC:    net {_signed(sec_net)} value to you   |   {verdict_sec}",
        ]
        if arb_label:
            banner_lines.append(f"arbitrage: [bold cyan]{arb_label}[/]")
        console.print(Panel.fit(
            "\n".join(banner_lines),
            title="verdict",
            subtitle=f"[bold cyan]{arb_label}[/]" if arb_label else None,
        ))
    elif market in ("dealer", "ktc") and has_secondary:
        net = evaluation.secondary_delta or 0
        console.print(Panel.fit(
            f"net {_signed(net)} value to you   |   {_ktc_site_verdict(evaluation)}",
            title="verdict (KTC)"))
    else:
        net = evaluation.delta  # >0 = in your favor
        pct = evaluation.pct_diff
        if evaluation.is_fair():
            verdict = f"[bold yellow]fair[/] - within {pct:.0f}%"
        elif net > 0:
            verdict = f"[bold green]you win[/] by {_signed(net)} ({pct:.0f}%)"
        else:
            verdict = f"[bold red]you lose[/] by {_signed(net)} ({pct:.0f}%)"
        title = "verdict (FantasyCalc - KTC cannot price this)" if market in ("dealer", "ktc") else "verdict"
        console.print(Panel.fit(f"net {_signed(net)} value to you   |   {verdict}", title=title))

    if market == "both":
        _print_offer_rule(evaluation, book)
    else:
        console.print("[dim]offer rule: needs both markets - run without --market to judge it.[/]")
    _print_provenance(book, cfg, include_secondary)

    if market in ("dealer", "ktc") and has_secondary:
        deltas = secondary_position_deltas(evaluation)
    else:
        deltas = position_deltas(evaluation)
    if deltas:
        line = "   ".join(f"{p} {_signed(v)}" for p, v in
                          sorted(deltas.items(), key=lambda x: abs(x[1]), reverse=True) if v)
        if line:
            console.print(f"[dim]positional swing (raw, before package adjustments):[/] {line}")
    for tok, name in subs:
        console.print(f"[dim]matched '{tok}' -> {name}[/]")
    _print_generic_pick_hints(cfg, sc, book, give_tokens + get_tokens)
    if unresolved:
        console.print(f"[bold red]unmatched (ignored):[/] {', '.join(unresolved)} "
                      f"[dim]- check spelling, or '2027 1st' / '2027 early 1st' for picks[/]")
        for tok in unresolved:
            cands = book.suggest(tok)
            if cands:
                console.print(f"[dim]  did you mean: "
                              f"{', '.join(c.name for c in cands)}?[/]")
    qa_rep = run_qa("trade", evaluation=evaluation, give_tokens=give_tokens, get_tokens=get_tokens)
    render_qa_footer(qa_rep, console)


def _print_generic_pick_hints(cfg: Config, sc: SleeperClient, book: ValueBook,
                              tokens: List[str]) -> None:
    """A round pick typed without a tier is priced as nobody's pick in
    particular; when the market tiers that round, show what it is really worth."""
    keys = sorted({k for k in map(normalize_pick, tokens) if k and f"{k} early" in book.picks})
    if not keys:
        return
    league = sc.league(cfg.league_id) or {}
    rosters = _league_rosters(cfg, sc)
    valuations = value_all_rosters(rosters, book, sc.players())
    ranks, basis = _finish_ranks(_season_sim(cfg, sc, league, rosters), valuations)
    seasons = sorted({k.split()[0] for k in keys})
    ledger = pick_ledger(rosters, sc.traded_picks(cfg.league_id), book, ranks,
                         seasons=seasons, rounds=max(int(k.split()[1]) for k in keys))
    mine = _pick_roster(rosters, None, cfg.user_id)
    for key in keys:
        season, rnd = key.split()
        flat = book.picks.get(key)
        tiers = " / ".join(f"{t} {book.picks[f'{key} {t}'].value:,}" for t in ("early", "mid", "late"))
        console.print(f"[yellow]'{flat.name if flat else key}' is priced as a generic pick"
                      + (f" ({flat.value:,})" if flat else "") + f". By tier: {tiers}.[/]")
        by_tier: Dict[str, List[str]] = {}
        for tp in ledger:
            for pk in tp.picks:
                if pk.season == season and pk.round == int(rnd) and pk.tier:
                    is_mine = bool(mine and tp.roster_id == mine.roster_id)
                    held = "[bold]you hold it[/]" if is_mine else f"held by {tp.team_name}"
                    by_tier.setdefault(pk.tier, []).append(
                        pk.original_team + (f" ({held})" if pk.acquired or is_mine else ""))
        for t in ("early", "mid", "late"):
            if by_tier.get(t):
                console.print(f"[dim]  {t} (original team, by {basis}): {', '.join(by_tier[t])}[/]")
        console.print(f"[dim]  name the tier for an exact price, e.g. "
                      f"'{season} early {flat.name.split()[1] if flat else 'round ' + rnd}'.[/]")


@app.command()
@_guard
def offers(
    sell: List[str] = typer.Option(..., "--sell", help="Asset you sell (repeatable)."),
    to: Optional[List[str]] = typer.Option(None, "--to", help="Manager's Sleeper username or team name "
                                           "(repeatable); default: every other team."),
    with_: Optional[List[str]] = typer.Option(None, "--with", help="Asset of yours allowed as a balancer "
                                              "(repeatable); default: your vets 27+ and picks after round 1."),
    max_age: float = typer.Option(26, help="Oldest player you would take back."),
    limit: int = typer.Option(5, help="Packages to show per manager."),
) -> None:
    """Find packages for what you sell that pass the offer rule in both markets,
    ranked by how well they fit your roster."""
    from ff.offers import main  # ff.offers imports this module

    argv = ["--max-age", str(max_age), "--limit", str(limit)]
    for flag, vals in (("--sell", sell), ("--to", to), ("--with", with_)):
        for v in vals or []:
            argv += [flag, v]
    raise typer.Exit(main(argv))


def _render_table(console: Console, title: str, columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> None:
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
    _render_table(console, "Start/sit comparison", ("start", "full-game projection", "availability", "whole-lineup total", "constraint"), (
        (o.name, f"{o.projected_points:.2f}", o.availability,
         f"{o.lineup.total:.2f}" if o.lineup else "-", o.reason or "other player sits") for o in result.options))
    render_weekly_notes(result.baseline, console)
    report = run_qa("compare", result=result, target_roster=target, weekly=ctx["weekly"])
    render_qa_footer(report, console)


def render_weekly_waivers(result: WeeklyWaivers, target: Any, ctx: dict, console: Console) -> None:
    console.print(f"Weekly waiver lineup improvement: {result.baseline.season} week {result.baseline.week}; "
                  f"baseline {result.baseline.total:.2f}; {result.candidates_evaluated} candidates evaluated.")
    _render_table(console, "Unrostered players by lineup gain", ("player", "pos", "projection", "lineup gain", "displaces"), (
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


# --- waivers -------------------------------------------------------------

@app.command()
@_guard
def waivers(
    limit: int = typer.Option(20, help="How many to show."),
    include_rostered: bool = typer.Option(False, "--all", help="Include rostered players."),
    position: Optional[str] = typer.Option(None, "--position", "-p", help="Filter by position."),
    trending_only: bool = typer.Option(False, "--trending", help="Only players in Sleeper's trending adds."),
    weekly: bool = typer.Option(False, "--weekly", help="Rank by current-week lineup improvement instead of dynasty value."),
) -> None:
    """Unrostered players by dynasty opportunity, or current-week lineup gain."""
    cfg, sc = _load()
    if weekly:
        if include_rostered:
            _fail("--weekly ranks unrostered acquisition candidates; it cannot be combined with --all.")
        ctx = _analysis_ctx(cfg, sc, include_secondary=False)
        ctx["weekly_candidates"] = True
        target = _prepare_weekly(ctx, None)
        trending_ids = {str(t["player_id"]) for t in _trending_adds(sc, limit)} if trending_only else None
        result = weekly_waivers(target, ctx["rosters"], ctx["projections"], ctx["scoring"],
                                ctx["roster_positions"], ctx["players_meta"], ctx["weekly"], str(cfg.season),
                                ctx["week"], position=position, limit=limit, trending_ids=trending_ids)
        render_weekly_waivers(result, target, ctx, console)
        return
    book = _book(cfg, include_secondary=False)
    rosters = _league_rosters(cfg, sc)
    trending = _trending_adds(sc, limit)
    roster_positions = (sc.league(cfg.league_id) or {}).get("roster_positions") or []
    players_meta = sc.players(fresh=True)
    targets = waiver_targets(
        trending,
        book,
        rosters,
        players_meta,
        limit=limit,
        free_agents_only=not include_rostered,
        is_superflex=bool(cfg.format.superflex),
        position=position,
        roster_positions=roster_positions,
        trending_only=trending_only,
    )

    t = Table(title="waiver targets - dynasty opportunity" + (" (trending only)" if trending_only else ""))
    for c in ("player", "pos", "role", "value", "adds", "status"):
        t.add_column(c, justify="right" if c in ("value", "adds") else "left")
    for tgt in targets:
        a = tgt.asset
        status = "[yellow]rostered[/]" if tgt.is_rostered else "[green]unrostered[/]"
        t.add_row(a.name, a.position or "-", tgt.depth_role, f"{a.value:,}", f"{tgt.add_count:,}" if tgt.add_count else "-", status)
    console.print(t)
    console.print("Unrostered does not establish waiver claim status or immediate pickup eligibility; check Sleeper. Adds: '-' means outside the trending sample. Rankings use dynasty opportunity, not weekly projected points.")
    qa_rep = run_qa("waivers", targets=targets, rosters=rosters, roster_positions=roster_positions)
    render_qa_footer(qa_rep, console)


# --- news / injuries -----------------------------------------------------

@app.command()
@_guard
def news(
    team: Optional[str] = typer.Argument(None, help="Team name; omit for the whole league."),
    limit: int = typer.Option(15, help="How many trending adds/drops to display."),
) -> None:
    """Player health, depth chart roles, injuries, and trending news across Sleeper."""
    cfg, sc = _load()
    book = _book(cfg, include_secondary=False)
    rosters = _league_rosters(cfg, sc)
    players_meta = sc.players()
    valuations = value_all_rosters(rosters, book, players_meta)

    if team:
        target = _pick_roster(rosters, team, cfg.user_id)
        if target is None:
            _fail("could not find that team. Try `ff power` to list teams.")
        target_rosters = [v for v in valuations if v.roster_id == target.roster_id]
    else:
        target_rosters = valuations

    injured_assets = []
    for val in target_rosters:
        for a in val.assets:
            if a.injury_tag or (a.status and a.status != "Active"):
                injured_assets.append((val.team_name, a))

    if injured_assets:
        title = f"injuries & player status ({target_rosters[0].team_name if len(target_rosters) == 1 else 'league-wide'})"
        t_inj = Table(title=title)
        for c in ("team", "player", "depth", "injury", "status", "value"):
            t_inj.add_column(c, justify="right" if c in ("value",) else "left")
        for tname, a in sorted(injured_assets, key=lambda x: x[1].value, reverse=True):
            t_inj.add_row(
                tname,
                a.name,
                a.depth_tag or a.position or "-",
                a.injury_tag or "-",
                a.injury_status or a.status or "Active",
                f"{a.value:,}",
            )
        console.print(t_inj)
    else:
        console.print("[dim]No reported injuries or reserve designations found.[/]")

    # Fetch the same superset `waivers` does and slice locally: the disk cache
    # keys on url+params, so a per-command --limit would mint its own entry and
    # its own round trip for what is one logical feed.
    fetch = max(limit * 3, 50)
    adds = sc.trending(kind="add", lookback_hours=24, limit=fetch)[:limit]
    drops = sc.trending(kind="drop", lookback_hours=24, limit=fetch)[:limit]

    if adds or drops:
        t_trend = Table(title="Sleeper trending movement (24h)")
        for c in ("type", "player", "pos/team", "status", "count", "value"):
            t_trend.add_column(c, justify="right" if c in ("count", "value") else "left")
        for label, items in (("[green]+ ADD[/]", adds), ("[red]- DROP[/]", drops)):
            for item in items:
                pid = str(item.get("player_id") or "")
                meta = (players_meta or {}).get(pid, {})
                asset = book.value_for_sleeper_id(pid)
                t_trend.add_row(
                    label,
                    player_name(pid, players_meta),
                    f"{meta.get('position', '-')}/{meta.get('team', '-')}",
                    meta.get("injury_status") or meta.get("status") or "Active",
                    f"{item.get('count', 0):,}",
                    f"{asset.value:,}" if asset else "-",
                )
        console.print(t_trend)
    qa_rep = run_qa("news", injured_assets=injured_assets, trending=(adds + drops))
    render_qa_footer(qa_rep, console)


@app.command()
@_guard
def cleanup(
    team: Optional[str] = typer.Argument(None, help="Team name; defaults to yours."),
    drops: int = typer.Option(8, help="How many drop candidates to list."),
) -> None:
    """Roster cleanup: capacity vs fill, who to drop, who can move to IR, and which
    young players to stash on taxi so you free active room for a waiver add without
    losing value."""
    cfg, sc = _load()
    if team is None and not cfg.user_id:
        _fail("your team is unknown. Re-run `ff setup <username>`, or pass a team name.")
    league = sc.league(cfg.league_id) or {}
    settings = league.get("settings") or {}
    roster_positions = league.get("roster_positions") or []
    book = _book(cfg, include_secondary=False)
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
        is_superflex=bool(cfg.format.superflex),
        drop_limit=drops,
        ir_statuses=ir_eligible_statuses(settings),
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

    # Concrete "how to make room" line: IR moves, taxi stashes, and zero-value
    # bench drops each open one active slot right now.
    moved_ids = {s.player_id for s in audit.ir_candidates + audit.taxi_candidates}
    bench_zeros = [s for s in audit.drop_candidates if s.is_active and s.value == 0 and s.player_id not in moved_ids]
    openable = len(audit.ir_candidates) + len(audit.taxi_candidates) + len(bench_zeros)
    if audit.active_open <= 0 and openable:
        console.print(f"[bold]make room:[/] up to [bold]{openable}[/] active slot(s) "
                      f"available now ([green]{len(audit.ir_candidates)} IR move[/], "
                      f"[green]{len(audit.taxi_candidates)} taxi stash[/], "
                      f"[green]{len(bench_zeros)} zero-value bench drop[/]).")

    dt = Table(title="drop candidates - worst value first")
    right = ("age", "exp", "value", "30d")
    for c in ("player", "pos", "team", "role", "age", "exp", "value", "30d", "where", "frees"):
        dt.add_column(c, justify="right" if c in right else "left")
    for s in audit.drop_candidates:
        frees = "[green]active slot[/]" if s.is_active else f"[dim]{s.slot.lower()} slot only[/]"
        dt.add_row(
            s.name, s.position or "-",
            s.team or "FA",
            s.depth_role,
            f"{s.age:.0f}" if s.age else "-",
            str(s.years_exp) if s.years_exp is not None else "-",
            f"{s.value:,}", _signed(s.trend_30day) if s.trend_30day else "-",
            s.slot, frees
        )
    console.print(dt)

    if audit.ir_candidates:
        it = Table(title="move to IR - frees an active slot, keeps the player")
        for c in ("player", "pos", "team", "status", "value", "where"):
            it.add_column(c, justify="right" if c == "value" else "left")
        for s in audit.ir_candidates:
            it.add_row(s.name, s.position or "-", s.team or "FA", s.injury_status or "-",
                       f"{s.value:,}", s.slot)
        console.print(it)
        console.print("[dim]If an IR player's designation clears, Sleeper blocks adds and drops "
                      "until you move that player back to the active roster.[/]")

    if audit.taxi_candidates:
        tt = Table(title="stash on taxi - frees an active slot, keeps the player")
        for c in ("player", "pos", "team", "role", "age", "value", "30d"):
            tt.add_column(c, justify="right" if c in ("age", "value", "30d") else "left")
        for s in audit.taxi_candidates:
            tt.add_row(
                s.name, s.position or "-",
                s.team or "FA",
                s.depth_role,
                f"{s.age:.0f}" if s.age else "-",
                f"{s.value:,}", _signed(s.trend_30day) if s.trend_30day else "-",
            )
        console.print(tt)
    elif audit.taxi_open > 0:
        console.print(f"[dim]{audit.taxi_open} taxi slot(s) open, but no taxi-eligible "
                      f"bench player to stash.[/]")

    console.print("[dim]Dropping a taxi/IR player frees a taxi/IR slot, not an active one; "
                  "only a bench drop, a taxi stash, or an IR move opens room for a waiver add. "
                  "ff is read-only - make the moves in Sleeper.[/]")
    qa_rep = run_qa("cleanup", audit=audit)
    render_qa_footer(qa_rep, console)


@app.command()
@_guard
def movers(
    buy: bool = typer.Option(False, "--buy", help="Show buy-low instead of sell-high (or Dealer > FC for arbitrage)."),
    sell: bool = typer.Option(False, "--sell", help="Show sell-high (or FC > Dealer for arbitrage)."),
    limit: int = typer.Option(20, help="How many to show."),
    min_value: int = typer.Option(1000, "--min-value",
                                  help="Floor on both values; filters deep stashes."),
    arbitrage: bool = typer.Option(False, "--arbitrage", "-a",
                                   help="Scan for market discrepancies between FantasyCalc and KeepTradeCut."),
) -> None:
    """Buy-low / sell-high: biggest gaps between dynasty and win-now value, or market arbitrage."""
    cfg, sc = _load()
    book = _book(cfg, include_secondary=arbitrage)

    if arbitrage:
        rosters = _league_rosters(cfg, sc)
        market_filter = None
        if buy and not sell:
            market_filter = "ktc"
        elif sell and not buy:
            market_filter = "fc"

        arb_movers = find_arbitrage_movers(
            rosters=rosters,
            book=book,
            min_value=min_value,
            limit=limit,
            market=market_filter,
        )

        if market_filter in ("dealer", "ktc"):
            kind = "KTC > FC (buy on FC / hype)"
        elif market_filter == "fc":
            kind = "FC > KTC (value veterans / sell on KTC)"
        else:
            kind = "market discrepancies (FC vs KTC)"

        t = Table(title=f"arbitrage movers - {kind} - {cfg.format.label()}")
        right_arb: Set[str] = {"FC", "KTC", "KTC@FC", "diff", "gap%", "age"}
        for c in ("player", "pos", "owner", "FC", "KTC", "KTC@FC", "diff", "gap%", "bias"):
            t.add_column(c, justify="right" if c in right_arb else "left")
        for m in arb_movers:
            a = m.asset
            owner = m.team_name or "-"
            bias_color = "[cyan]KTC[/]" if m.market_bias in ("Dealer", "KTC") else ("[yellow]FC[/]" if m.market_bias == "FC" else "EVEN")
            t.add_row(
                a.name,
                a.position or "-",
                owner,
                f"{m.fc_value:,}",
                f"{m.secondary_value:,}",
                f"{m.compared_value:,}",
                _signed(m.diff),
                f"{m.pct_diff:.0f}%",
                bias_color,
            )
        console.print(t)
        if not _has_ktc(book):
            console.print(f"[yellow]{_KTC_DOWN}; there is nothing to compare.[/]")
        elif not arb_movers:
            console.print("[dim]No market arbitrage opportunities found above the value floor.[/]")
        else:
            console.print("[dim]KTC@FC = FantasyCalc's value at the asset's KTC rank, since the two "
                          "markets use different scales. diff = KTC@FC - FC; bias = the market that "
                          "ranks the asset higher.[/]")
        qa_rep = run_qa("movers", movers=arb_movers, mode="arbitrage")
        render_qa_footer(qa_rep, console)
        return

    rows = top_movers(book, buy=buy, limit=limit, min_value=min_value)
    kind = "buy-low (dynasty > win-now)" if buy else "sell-high (win-now > dynasty)"
    t = Table(title=f"movers - {kind} - {cfg.format.label()}")
    right: Set[str] = {"dynasty", "redraft", "gap%", "age"}
    for c in ("player", "pos", "age", "dynasty", "redraft", "gap%"):
        t.add_column(c, justify="right" if c in right else "left")
    for a, pct in rows:
        t.add_row(a.name, a.position or "-", f"{a.age:.0f}" if a.age else "-",
                  f"{a.value:,}", f"{a.redraft_value:,}", f"{pct:+.0f}%")
    console.print(t)
    qa_rep = run_qa("movers", movers=rows, mode="gap")
    render_qa_footer(qa_rep, console)


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

    league = sc.league(cfg.league_id, fresh=True) or {}
    scoring = league.get("scoring_settings") or {}
    roster_positions = league.get("roster_positions") or []
    rosters = build_rosters(sc.rosters(cfg.league_id, fresh=True), sc.league_users(cfg.league_id))
    target = _pick_roster(rosters, team, cfg.user_id)
    if target is None:
        _fail("could not find that team. Try `ff power` to list teams.")

    state = sc.state(fresh=True) or {}
    season = season or str(cfg.season)
    week = week or _current_week(state)
    if week < 1:
        week = 1

    proj = ProjectionsClient().week(season, week, fresh=True)
    if not proj:
        _fail(f"no projections published for {season} week {week} yet. "
              f"Try a different --week, or wait until they post.")
    players_meta = sc.players()

    weekly = None
    if season == str(state.get("season")) and week == _current_week(state):
        if league.get("season_type", "regular") != "regular":
            _fail("Weekly advice supports regular-season leagues only.")
        weekly, players_meta = load_weekly(sc, cfg.league_id, target, season, week, league, players_meta)
    else:
        console.print("Projection-only scenario: current injuries and game locks are not applied.")
    lu = optimal_lineup(target, proj, scoring, roster_positions, players_meta,
                        season=season, week=week, weekly=weekly)
    info = projected_points(target, proj, scoring, players_meta)
    for slot in lu.slots + lu.bench:
        if slot.player_id in info:
            info[slot.player_id]["points"] = slot.points

    console.print(Panel.fit(
        f"[bold]{target.team_name}[/]   {season} week {week}   "
        f"{'actual + remaining projections' if weekly else 'projected'} [bold cyan]{lu.total:g}[/]   [dim]({cfg.format.label()})[/]",
        title="optimal lineup"))

    t = Table()
    for c in ("slot", "player", "pos", "points", "basis", "status"):
        t.add_column(c, justify="right" if c == "points" else "left")
    for s in lu.slots:
        t.add_row(s.slot, s.name, s.position or "-", f"{s.points:g}", s.points_kind,
                  ("LOCKED; " if s.locked else "") + s.availability)
    console.print(t)
    render_weekly_notes(lu, console)
    if lu.unsupported_slots:
        console.print(f"[bold yellow]note:[/] this league uses slots the optimizer "
                      f"can't place optimally ({', '.join(sorted(set(lu.unsupported_slots)))}); "
                      f"they're left out of the lineup above.")

    # Compare the same actual/projected basis on both sides.
    optimal_ids = {s.player_id for s in lu.slots if s.player_id}
    roster_positions = league.get("roster_positions") or []
    unsupported_set = set(lu.unsupported_slots or [])
    supported_starters = []
    for idx, p in enumerate(target.starters):
        if p and p in info:
            slot_name = roster_positions[idx] if idx < len(roster_positions) else None
            if slot_name not in unsupported_set:
                supported_starters.append(p)
    current = supported_starters
    if current:
        current_total = round(sum(info[p]["points"] for p in current), 2)
        sit = [p for p in current if p not in optimal_ids]
        start = [s for s in lu.slots if s.player_id and s.player_id not in set(supported_starters)]
        if start or sit:
            gain = round(lu.total - current_total, 2)
            gain_str = f"+{gain:g}" if gain >= 0 else f"{gain:g}"
            console.print(f"[bold green]{gain_str} points[/] vs your current lineup "
                          f"([dim]{current_total:g} -> {lu.total:g}[/]):")
            for s in start:
                console.print(f"  [green]START[/] {s.name} ({s.points:g}) in {s.slot}")
            for p in sit:
                console.print(f"  [red]SIT[/]   {info[p]['name']} ({info[p]['points']:g})")
        else:
            if weekly and [s.player_id or "0" for s in lu.slots] != target.starters:
                console.print("Selected starters are unchanged; use the slot assignments above to preserve late-game flexibility.")
            else:
                console.print("[dim]your current lineup is already optimal.[/]")

    if lu.bench:
        top_bench = ", ".join(f"{b.name} ({b.points:g})" for b in lu.bench[:5])
        console.print(f"[dim]bench: {top_bench}[/]")
    qa_rep = run_qa("lineup", lineup=lu, target_roster=target, scoring=scoring, weekly=weekly)
    render_qa_footer(qa_rep, console)


@app.command()
@_guard
def compare(
    player_a: str = typer.Argument(..., help="First player's full name or Sleeper ID."),
    player_b: str = typer.Argument(..., help="Second player's full name or Sleeper ID."),
    team: Optional[str] = typer.Option(None, help="Team name; defaults to yours."),
) -> None:
    """Compare two rostered players for current-week start/sit, including game locks."""
    cfg, sc = _load()
    ctx = _analysis_ctx(cfg, sc, include_secondary=False)
    ids = [resolve_player(p, ctx["players_meta"]) for p in (player_a, player_b)]
    target = _prepare_weekly(ctx, team)
    result = compare_players(ids, target, ctx["projections"], ctx["scoring"], ctx["roster_positions"],
                             ctx["players_meta"], ctx["weekly"], str(cfg.season), ctx["week"])
    render_comparison(result, target, ctx, console)


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

    status = str(d.get("status") or "")
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
            is_active_draft = status in ("drafting", "in_progress")
            if p.pick_no == on_clock:
                when = "[bold green]ON THE CLOCK[/]" if is_active_draft else "upcoming"
            else:
                when = f"{gap} pick{'s' if gap != 1 else ''} away"
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
    book = _book(cfg, include_secondary=False)
    have = set(mine.player_ids)
    merged = mine.model_copy(update={
        "player_ids": list(mine.player_ids) + [p for p in drafted_by_me if p not in have]})
    val = value_roster(merged, book, players_meta)

    # Team context FIRST: a pick recommendation that ignores your roster is just
    # the market read back to you. Slots drive both standing and starter-upgrade.
    league = sc.league(cfg.league_id) or {}
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
    # FantasyCalc prices TE premium only as te+/te++; flag TEs when the league's
    # premium is one it cannot express (e.g. +0.25), so the gap stays visible.
    tep_on = cfg.format.tep > 0 and cfg.format.fantasycalc_tep() is None
    for i, f in enumerate(fits, 1):
        a = f.asset
        pos = (a.position or "-") + ("*" if tep_on and a.position == "TE" else "")
        posrk = f"{a.position}{a.position_rank}" if a.position_rank else "-"
        at.add_row(str(i), a.name, pos, posrk, str(f.market_rank),
                   f"{f.fit_score:,.0f}", f"{a.value:,}",
                   _signed(a.trend_30day) if a.trend_30day else "-", f.why)
    console.print(at)
    if tep_on:
        console.print(f"[dim]* TE value runs conservative: FantasyCalc's TE premium "
                      f"starts at +0.5, but your league scores +{cfg.format.tep:g} TEP, "
                      f"so TEs are worth a bit more than shown.[/]")
    console.print("[dim]FitScore = market value adjusted for YOUR roster fit + "
                  "win-now/rebuild horizon. mkt# is the raw dynasty-value rank. "
                  "The pick call is yours.[/]")
    qa_rep = run_qa("draft", my_picks=owned, taken=taken, fits=fits, team_val=val)
    render_qa_footer(qa_rep, console)


_LLM_BACKENDS = SUPPORTED_BACKENDS + ["auto"]


@app.command()
@_guard
def ask(
    query: str = typer.Argument(..., help="Natural language question about your league"),
    backend: Optional[str] = typer.Option(None, "--backend", help="Override backend (agy, gemini, claude, ollama)"),
) -> None:
    """Ask natural language questions about trades, lineups, waivers, or league setup."""
    cfg = load_config() if config_exists() else None
    target_backend = (backend or (cfg.llm_backend if cfg else "auto")).lower()
    if target_backend not in _LLM_BACKENDS:
        _fail(f"Invalid backend '{target_backend}'. Must be one of: {', '.join(_LLM_BACKENDS)}")
    ollama_model = cfg.ollama_model if cfg else "llama3.2"

    try:
        runner_inst = TerminalRunner(backend=target_backend, ollama_model=ollama_model)
    except RuntimeError as e:
        _fail(str(e))

    system_prompt = (
        f"You are an AI assistant for a Sleeper dynasty fantasy football CLI (`ff`).\n"
        f"Available tools: {json.dumps(TOOL_SCHEMAS)}\n"
        f"If the query requires league data, trade calculations, lineup optimization, waivers, draft fit, or onboarding, "
        f"respond with ONLY a JSON tool call block in this format:\n"
        f'{{"tool": "<tool_name>", "kwargs": {{ ... }}}}\n'
        f"Do NOT include conversational text when issuing a tool call. If no tool is needed, respond in plain Markdown."
    )

    try:
        first_response = runner_inst.run(prompt=query, system_prompt=system_prompt)
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, RuntimeError) as e:
        _fail(f"LLM runner failed ({e}).")

    tool_call = None
    try:
        data = json.loads(first_response.strip())
        if isinstance(data, dict) and "tool" in data:
            tool_call = data
    except Exception:
        match = re.search(r"```(?:json)?\s*(\{\s*\"tool\".*?\})\s*```", first_response, re.DOTALL)
        if match:
            try:
                tool_call = json.loads(match.group(1))
            except Exception:
                pass

    if not tool_call:
        console.print(Markdown(first_response))
        qa_rep = run_qa("ask", tool_name=None, result={}, query=query)
        render_qa_footer(qa_rep, console)
        return

    tool_name = tool_call.get("tool")
    kwargs = tool_call.get("kwargs") or {}
    if not isinstance(kwargs, dict):
        kwargs = {}

    if tool_name not in ALLOWED_TOOLS:
        console.print(f"[red]Unknown tool '{tool_name}'.[/] Known tools: {', '.join(sorted(ALLOWED_TOOLS))}.")
        qa_rep = run_qa("ask", tool_name=str(tool_name), result={"error": f"Unknown tool: {tool_name}"}, query=query)
        render_qa_footer(qa_rep, console)
        return

    if tool_name == "setup_league":
        username = kwargs.get("username")
        if not username:
            console.print("[yellow]Please provide your Sleeper username to complete onboarding.[/]")
            return
        try:
            cfg = onboard_user(username=username, league_id=kwargs.get("league_id"))
        except ValueError as e:
            console.print(f"[red]{e}[/]")
            return
        console.print(f"[bold green]Successfully onboarded Sleeper league[/] [cyan]{cfg.league_name or cfg.league_id}[/] for user [bold]{username}[/]!")
        qa_rep = run_qa("ask", tool_name=tool_name, result={"username": username}, query=query)
        render_qa_footer(qa_rep, console)
        return

    if not cfg:
        console.print("[yellow]No league configured yet.[/] Please provide your Sleeper username to get started (e.g. `ff ask 'setup league for username'`).")
        return

    sc = SleeperClient()
    ctx = _analysis_ctx(cfg, sc)

    try:
        if tool_name == "get_waivers":
            ctx["trending"] = _trending_adds(sc, int(kwargs.get("limit") or 25))
        result = dispatch_tool(tool_name, kwargs, ctx)
    except Exception as e:
        console.print(f"[red]Error executing tool calculation '{tool_name}':[/] {e}")
        qa_rep = run_qa("ask", tool_name=tool_name, result={"error": str(e)}, query=query)
        render_qa_footer(qa_rep, console)
        return

    synthesis_prompt = (
        f"User Query: '{query}'\n"
        f"Executed Tool: '{tool_name}' with args {json.dumps(kwargs)}\n"
        f"Deterministic Calculation Result:\n{json.dumps(result, indent=2)}\n\n"
        f"Provide a concise, helpful, human-friendly explanation of these results in plain Markdown."
    )
    try:
        final_response = runner_inst.run(prompt=synthesis_prompt)
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, RuntimeError) as e:
        _fail(f"LLM runner failed ({e}).")
    console.print(Markdown(final_response))
    qa_rep = run_qa("ask", tool_name=tool_name, result=result, query=query)
    render_qa_footer(qa_rep, console)


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
    backend_clean = backend.lower()
    if backend_clean not in _LLM_BACKENDS:
        _fail(f"Invalid backend '{backend}'. Must be one of: {', '.join(_LLM_BACKENDS)}")
    cfg.llm_backend = backend_clean
    if model:
        cfg.ollama_model = model
    path = save_config(cfg)
    console.print(f"[bold green]Updated LLM backend[/] to [cyan]{backend_clean}[/]"
                  + (f" (model: [cyan]{model}[/])" if model else "")
                  + f"\nconfig: {path}")


@app.command(name="qa")
@_guard
def qa_cmd(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show granular check details."),
) -> None:
    """Run full-system diagnostic invariant audits across all league domains."""
    cfg, sc = _load()
    reports: List[Any] = []

    # 1. Setup audit
    reports.append(run_qa("setup", config=cfg))

    # 2. Rosters & Power audit
    book = _book(cfg, include_secondary=True)
    rosters = _league_rosters(cfg, sc)
    players_meta = sc.players()
    valuations = value_all_rosters(rosters, book, players_meta)
    reports.append(run_qa("power", valuations=valuations, rosters=rosters))

    my_roster = _pick_roster(rosters, None, cfg.user_id)
    if my_roster:
        my_val = next((v for v in valuations if v.roster_id == my_roster.roster_id), valuations[0])
        reports.append(run_qa("roster", valuation=my_val, target_roster=my_roster))

    # 3. Draft picks ledger audit
    latest = _active_draft(sc, cfg.league_id)
    league = sc.league(cfg.league_id) or {}
    base = int((latest or {}).get("season") or league.get("season") or cfg.season)
    start = base + 1 if latest else base
    seasons = [str(start + i) for i in range(2)]
    rounds_n = int((league.get("settings") or {}).get("draft_rounds") or 4)
    ranks, _ = _finish_ranks(_season_sim(cfg, sc, league, rosters), valuations)
    traded = sc.traded_picks(cfg.league_id)
    ledger = pick_ledger(rosters, traded, book, ranks, seasons=seasons, rounds=rounds_n)
    reports.append(run_qa("picks", ledger=ledger, rosters=rosters, traded_picks=traded))

    # 4. Values audit
    top_assets = book.top(limit=20)
    reports.append(run_qa("values", assets=top_assets, market="both"))

    # 5. Cleanup audit
    if my_roster:
        settings = league.get("settings") or {}
        audit = audit_roster(
            my_roster, book, players_meta,
            roster_positions=league.get("roster_positions") or [],
            taxi_slots=int(settings.get("taxi_slots") or 0),
            reserve_slots=int(settings.get("reserve_slots") or 0),
            taxi_allow_vets=bool(settings.get("taxi_allow_vets")),
            taxi_years=settings.get("taxi_years"),
            ir_statuses=ir_eligible_statuses(settings),
        )
        reports.append(run_qa("cleanup", audit=audit))

    # 6. Waivers audit
    trending_adds = sc.trending(kind="add", limit=50)
    targets = waiver_targets(trending_adds, book, rosters, players_meta, limit=20,
                             roster_positions=league.get("roster_positions") or [])
    reports.append(run_qa("waivers", targets=targets, rosters=rosters,
                          roster_positions=league.get("roster_positions") or []))

    # 7. Movers / Arbitrage audit
    arb_movers = find_arbitrage_movers(rosters=rosters, book=book, min_value=1000, limit=20)
    reports.append(run_qa("movers", movers=arb_movers, mode="arbitrage"))

    if verbose:
        for r in reports:
            render_qa_footer(r, console, mode="verbose")
    render_qa_full_report(reports, console)


@app.command(name="doctor", hidden=True)
@_guard
def doctor_cmd(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show granular check details."),
) -> None:
    """Diagnostic system health check (alias for `ff qa`)."""
    qa_cmd(verbose=verbose)


@app.command()
def version() -> None:
    """Print the ff version."""
    console.print(f"ff {__version__}")


if __name__ == "__main__":
    app()
