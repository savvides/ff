"""Competitive window, duration, and seasonal liquidity filters (pure analysis)."""

from __future__ import annotations

from datetime import date
from statistics import median
from typing import Any, Dict, FrozenSet, List, Literal, Optional, Sequence, Set, Tuple

from ff.analysis.lineup import _assign, starting_slots
from ff.analysis.movers import value_redraft_gap
from ff.contracts import (
    Asset,
    AssetDurationFlag,
    DecisionFilter,
    Roster,
    RosterValuation,
    SeasonPhase,
    TeamPicks,
    TeamWindow,
    TradeEvaluation,
)
from ff.sleeper import player_name
from ff.values import ValueBook

PhaseKey = Literal[
    "in_season_early",
    "in_season_peak",
    "playoffs",
    "offseason_draft",
    "offseason_quiet",
]
DiagnosedWindow = Literal["CONTEND", "MIDDLE_TRAP", "REBUILD"]
TargetMode = Literal["contend", "rebuild", "middle_trap"]
TargetSource = Literal["auto", "config", "override"]
PivotLean = Literal["PIVOT_CONTEND", "PIVOT_REBUILD"]
FlagSeverity = Literal["HIGH", "MODERATE", "INFO"]
FilterSignal = Literal["ALIGNED", "TAILWIND", "NEUTRAL", "CAUTION", "HEADWIND", "MISMATCH", "N/A"]

_MEANINGFUL_SHIFT = 1000
_SEASONAL_SHIFT = 1500
_SERIOUS_INJURY_STATUSES: FrozenSet[str] = frozenset(
    {"ir", "injured reserve", "pup", "physically unable to perform", "out", "doubtful"}
)
_NON_ACTIVE_VET_STATUSES: FrozenSet[str] = _SERIOUS_INJURY_STATUSES | frozenset({"sus", "suspended"})

_DIAG_TO_TARGET: Dict[DiagnosedWindow, TargetMode] = {
    "CONTEND": "contend",
    "MIDDLE_TRAP": "middle_trap",
    "REBUILD": "rebuild",
}
_SEVERITY_ORDER: Dict[str, int] = {"HIGH": 0, "MODERATE": 1, "INFO": 2}

_PHASE_META: Dict[PhaseKey, Tuple[str, str, str]] = {
    "in_season_early": (
        "Early Season (Wk 1-4)",
        "caution",
        "Early sample noise: avoid overpaying for short-term spikes before true tiers settle.",
    ),
    "in_season_peak": (
        "Peak In-Season (Oct-Nov)",
        "points_premium",
        "Contenders pay a premium for weekly points; future picks and injured stars trade at a discount.",
    ),
    "playoffs": (
        "Playoff Push / Playoffs",
        "win_now_lock",
        "Trade deadlines and playoff locks favor proven immediate production over speculative upside.",
    ),
    "offseason_draft": (
        "Offseason Rookie Hype (Mar-May)",
        "picks_premium",
        "Rookie picks carry peak seasonal liquidity while proven veterans trade at a discount.",
    ),
    "offseason_quiet": (
        "Offseason Liquidity Window",
        "vet_discount",
        "Quiet market favors acquiring undervalued veterans and offloading aging RB risk before camp.",
    ),
}


def _phase_from_month(month: int) -> PhaseKey:
    if month in (3, 4, 5):
        return "offseason_draft"
    if month == 9:
        return "in_season_early"
    if month in (10, 11):
        return "in_season_peak"
    if month == 12:
        return "playoffs"
    return "offseason_quiet"


def detect_season_phase(
    state: Optional[Dict[str, Any]] = None,
    today: Optional[date] = None,
) -> SeasonPhase:
    """Resolve the NFL seasonal liquidity regime from Sleeper state and date."""
    ref_date = today or date.today()
    month = ref_date.month

    wk: Optional[int] = None
    season_type: Optional[str] = None
    if state:
        raw_wk = max(int(state.get("week") or 0), int(state.get("display_week") or 0))
        wk = raw_wk if raw_wk > 0 else None
        season_type = str(state.get("season_type") or "").strip().lower() or None

    if season_type is None and wk is not None and wk >= 1:
        season_type = "regular"

    phase: PhaseKey
    if season_type == "regular" and wk is not None:
        if wk <= 4:
            phase = "in_season_early"
        elif wk <= 13:
            phase = "in_season_peak"
        else:
            phase = "playoffs"
    elif season_type == "post":
        phase = "playoffs"
    elif season_type == "off":
        phase = "offseason_draft" if month in (3, 4, 5) else "offseason_quiet"
    elif season_type == "pre":
        phase = "offseason_quiet"
    else:
        phase = _phase_from_month(month)

    label, liquidity_bias, summary = _PHASE_META[phase]
    return SeasonPhase(
        phase=phase,
        label=label,
        liquidity_bias=liquidity_bias,
        week=wk,
        season_type=season_type,
        summary=summary,
    )


def _percentiles(values: Sequence[float]) -> List[float]:
    """Average-rank percentiles in [0.0, 100.0]; [50.0] for a single-team league."""
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [50.0]
    out: List[float] = []
    for v in values:
        below = sum(1 for x in values if x < v)
        equal = sum(1 for x in values if x == v)
        out.append((below + (equal - 1) / 2.0) / (n - 1) * 100.0)
    return out


def _copy_and_enrich(asset: Asset, meta_entry: Optional[Dict[str, Any]]) -> Asset:
    copy = asset.model_copy()
    if isinstance(meta_entry, dict):
        copy.fill_from_meta(meta_entry)
        if copy.position is None and meta_entry.get("position"):
            copy.position = meta_entry.get("position")
    return copy


def _roster_assets(
    roster: Roster,
    val: Optional[RosterValuation],
    book: ValueBook,
    meta: Dict[str, Any],
) -> List[Asset]:
    assets: List[Asset] = []
    seen: Set[str] = set()
    if val is not None:
        for a in val.assets:
            if a.id in seen:
                continue
            seen.add(a.id)
            assets.append(_copy_and_enrich(a, meta.get(a.id)))
    for pid in roster.player_ids:
        if pid in seen:
            continue
        seen.add(pid)
        valued = book.value_for_sleeper_id(pid)
        if valued is not None:
            assets.append(_copy_and_enrich(valued, meta.get(pid)))
        else:
            raw_meta = meta.get(pid)
            m: Dict[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}
            assets.append(
                _copy_and_enrich(Asset(id=pid, name=player_name(pid, meta), value=0), m)
            )
    return assets


def _active_starter_win_now(
    roster: Roster,
    assets: List[Asset],
    roster_positions: List[str],
    *,
    has_redraft: bool = True,
) -> Tuple[int, Set[str]]:
    """Sum win-now value and return starter IDs for active (non-taxi/IR) players."""
    excluded = set(roster.taxi) | set(roster.reserve)
    active = [a for a in assets if not a.is_pick and a.id not in excluded]
    if not active:
        return 0, set()

    def _win_score(asset: Asset) -> float:
        if has_redraft:
            return float(asset.redraft_value or 0)
        return float(asset.redraft_value if asset.redraft_value is not None else asset.value)

    ordered = sorted(active, key=lambda a: (-_win_score(a), -a.value, a.id))
    scores: Dict[str, float] = {}
    positions: Dict[str, Optional[str]] = {}
    for a in ordered:
        if a.id not in scores:
            scores[a.id] = _win_score(a)
            positions[a.id] = a.position

    starting = starting_slots(roster_positions)
    if starting:
        chosen = _assign(positions, scores, starting)
        starter_ids = {pid for pid in chosen.values() if pid is not None}
    else:
        starter_ids = set(list(scores.keys())[:9])

    total = sum(int(round(scores[pid])) for pid in starter_ids)
    return total, starter_ids


def _win_now_weights(season_phase: SeasonPhase, has_max_pf: bool) -> Tuple[float, float, float]:
    if season_phase.phase in ("offseason_draft", "offseason_quiet") or not has_max_pf:
        return 1.0, 0.0, 0.0
    if season_phase.phase == "in_season_early" and (season_phase.week or 0) <= 3:
        return 0.65, 0.25, 0.10
    return 0.35, 0.45, 0.20


def _diagnose_window(win_now_rank: int, n_teams: int, cut: int) -> DiagnosedWindow:
    if n_teams <= 2:
        return "CONTEND" if win_now_rank == 1 else "REBUILD"
    if win_now_rank <= cut:
        return "CONTEND"
    if win_now_rank > n_teams - cut:
        return "REBUILD"
    return "MIDDLE_TRAP"


def _resolve_pivot(
    diagnosed: DiagnosedWindow,
    win_now_rank: int,
    cut: int,
    pick_value: int,
    median_picks: Optional[float],
    starter_pct: float,
) -> Tuple[Optional[PivotLean], Optional[str]]:
    if diagnosed != "MIDDLE_TRAP":
        return None, None
    has_capital = (pick_value >= median_picks) if median_picks is not None else (starter_pct >= 50.0)
    if win_now_rank <= cut + 2 and has_capital:
        basis = "above-median pick capital" if median_picks is not None else "above-median starter quality"
        return (
            "PIVOT_CONTEND",
            f"Rank {win_now_rank} is within striking distance of top-{cut} contenders with {basis}.",
        )
    return (
        "PIVOT_REBUILD",
        f"Rank {win_now_rank} trails top-{cut} contenders without clear buy-in equity; "
        "strip points and sell depreciating vets.",
    )


def _resolve_target(
    diagnosed: DiagnosedWindow,
    is_target: bool,
    window_mode: str,
    mode_override: Optional[str],
) -> Tuple[TargetMode, TargetSource]:
    auto_target = _DIAG_TO_TARGET[diagnosed]
    if not is_target:
        return auto_target, "auto"
    if mode_override == "contend":
        return "contend", "override"
    if mode_override == "rebuild":
        return "rebuild", "override"
    if mode_override == "auto":
        return auto_target, "auto"
    if mode_override is None:
        if window_mode == "contend":
            return "contend", "config"
        if window_mode == "rebuild":
            return "rebuild", "config"
    return auto_target, "auto"


def _asset_flags(
    assets: List[Asset],
    optimal_starter_ids: Set[str],
    taxi_set: Set[str],
    reserve_set: Set[str],
    season_phase: SeasonPhase,
    effective_target: TargetMode,
    pivot_lean: Optional[PivotLean],
    is_dynasty: bool,
) -> List[AssetDurationFlag]:
    if not is_dynasty:
        return []

    is_offseason = season_phase.phase in ("offseason_draft", "offseason_quiet")
    is_in_season = not is_offseason
    flags: List[AssetDurationFlag] = []

    for a in assets:
        if a.is_pick:
            continue
        age = a.age
        pos = a.position
        gap = value_redraft_gap(a, 1000)
        rb_decay_flagged = False

        if pos == "RB" and age is not None and age >= 26 and a.value >= 1500:
            if is_offseason:
                flags.append(
                    AssetDurationFlag(
                        player_id=a.id,
                        name=a.name,
                        position=pos,
                        age=age,
                        value=a.value,
                        kind="RB_OFFSEASON_DECAY",
                        severity="HIGH",
                        reason=f"Age-{age:.0f} RB holds offseason injury/draft replacement risk for zero points.",
                    )
                )
                rb_decay_flagged = True
            elif is_in_season and (
                effective_target == "rebuild"
                or (effective_target == "middle_trap" and pivot_lean == "PIVOT_REBUILD")
            ):
                flags.append(
                    AssetDurationFlag(
                        player_id=a.id,
                        name=a.name,
                        position=pos,
                        age=age,
                        value=a.value,
                        kind="RB_WINDOW_MISMATCH",
                        severity="HIGH",
                        reason=f"Age-{age:.0f} RB produces depreciating points outside your window; sell for picks/WR.",
                    )
                )
                rb_decay_flagged = True

        if (
            pos == "RB"
            and age is not None
            and age >= 28
            and a.value >= 1500
            and is_in_season
            and (
                effective_target == "contend"
                or (effective_target == "middle_trap" and pivot_lean == "PIVOT_CONTEND")
            )
        ):
            flags.append(
                AssetDurationFlag(
                    player_id=a.id,
                    name=a.name,
                    position=pos,
                    age=age,
                    value=a.value,
                    kind="RB_CLIFF_WATCH",
                    severity="MODERATE",
                    reason=f"Age-{age:.0f} RB faces steep cliff risk; monitor exit window or handcuff coverage.",
                )
            )

        if pos == "RB" and a.id not in (taxi_set | reserve_set) and a.depth_chart_order == 2 and a.value < 2000:
            flags.append(
                AssetDurationFlag(
                    player_id=a.id,
                    name=a.name,
                    position=pos,
                    age=age,
                    value=a.value,
                    kind="RB_CALL_OPTION",
                    severity="INFO",
                    reason="Active RB2 contingent call option with asymmetric injury-upside leverage.",
                )
            )

        sell_window = effective_target == "rebuild" or (
            effective_target == "middle_trap" and pivot_lean == "PIVOT_REBUILD"
        )
        if sell_window and pos != "QB" and not rb_decay_flagged:
            gap_sell = gap is not None and gap <= -20.0
            age_sell = age is not None and age >= 28 and (a.redraft_value or 0) >= 1500
            if gap_sell or age_sell:
                sev: FlagSeverity = "HIGH" if a.id in optimal_starter_ids else "MODERATE"
                detail = f"gap {gap:+.0f}%" if gap_sell and gap is not None else f"age {age:.0f} redraft points"
                flags.append(
                    AssetDurationFlag(
                        player_id=a.id,
                        name=a.name,
                        position=pos,
                        age=age,
                        value=a.value,
                        kind="SELL_POINTS",
                        severity=sev,
                        reason=f"Win-now production ({detail}) better liquidated for picks or younger core.",
                    )
                )

        is_ir = a.id in reserve_set or a.status == "Injured Reserve" or a.injury_status == "IR"
        buy_window = effective_target == "contend" or (
            effective_target == "middle_trap" and pivot_lean == "PIVOT_CONTEND"
        )
        if (
            buy_window
            and a.id not in optimal_starter_ids
            and a.value >= 2500
            and ((gap is not None and gap >= 40.0) or is_ir)
        ):
            basis = "IR-stashed blue-chip" if is_ir else f"bench youth (+{gap:.0f}% dynasty premium)"
            flags.append(
                AssetDurationFlag(
                    player_id=a.id,
                    name=a.name,
                    position=pos,
                    age=age,
                    value=a.value,
                    kind="TRADEABLE_LIQUIDITY",
                    severity="INFO",
                    reason=f"High-value non-starter ({basis}) convertible into win-now starter upgrades.",
                )
            )

    flags.sort(key=lambda f: (_SEVERITY_ORDER[f.severity], -f.value, f.name))
    return flags


def analyze_league_windows(
    rosters: List[Roster],
    valuations: List[RosterValuation],
    book: ValueBook,
    roster_positions: List[str],
    *,
    season_phase: SeasonPhase,
    pick_ledger: Optional[List[TeamPicks]] = None,
    players_meta: Optional[Dict[str, Any]] = None,
    is_dynasty: bool = True,
    window_mode: str = "auto",
    mode_override: Optional[str] = None,
    target_roster_id: Optional[int] = None,
) -> List[TeamWindow]:
    """Diagnose every team's competitive window, future equity, and duration flags."""
    if not rosters:
        return []

    meta = players_meta or {}
    val_by_id = {v.roster_id: v for v in valuations}
    picks_by_id = {tp.roster_id: tp.total_value for tp in pick_ledger} if pick_ledger else {}
    has_redraft = any(
        not a.is_pick and a.redraft_value is not None for a in book.assets
    ) or any(
        not a.is_pick and a.redraft_value is not None
        for v in valuations
        for a in v.assets
    )

    team_assets: List[List[Asset]] = []
    starter_values: List[int] = []
    starter_id_sets: List[Set[str]] = []
    dynasty_values: List[int] = []
    pick_values: List[int] = []
    win_pcts: List[float] = []

    for r in rosters:
        val = val_by_id.get(r.roster_id)
        assets = _roster_assets(r, val, book, meta)
        starter_val, starter_ids = _active_starter_win_now(
            r, assets, roster_positions, has_redraft=has_redraft
        )
        dyn_val = val.total_value if val is not None else sum(a.value for a in assets)
        pick_val = picks_by_id.get(r.roster_id, 0)
        games = r.wins + r.losses + r.ties
        win_pct = (r.wins + 0.5 * r.ties) / games if games > 0 else 0.0

        team_assets.append(assets)
        starter_values.append(starter_val)
        starter_id_sets.append(starter_ids)
        dynasty_values.append(dyn_val)
        pick_values.append(pick_val)
        win_pcts.append(win_pct)

    starter_pcts = _percentiles([float(v) for v in starter_values])
    max_pf_pcts = _percentiles([r.max_pf for r in rosters])
    win_pct_ranks = _percentiles(win_pcts)
    future_scores = [
        min(100.0, max(0.0, s))
        for s in _percentiles([float(d + p) for d, p in zip(dynasty_values, pick_values)])
    ]

    has_max_pf = any(r.max_pf > 0 for r in rosters)
    w_start, w_pf, w_win = _win_now_weights(season_phase, has_max_pf)
    win_now_scores = [
        min(100.0, max(0.0, w_start * s + w_pf * m + w_win * w))
        for s, m, w in zip(starter_pcts, max_pf_pcts, win_pct_ranks)
    ]

    n_teams = len(rosters)
    win_order = sorted(
        range(n_teams),
        key=lambda i: (win_now_scores[i], starter_values[i], rosters[i].max_pf, -rosters[i].roster_id),
        reverse=True,
    )
    win_now_ranks = [0] * n_teams
    for rank, idx in enumerate(win_order, start=1):
        win_now_ranks[idx] = rank

    future_order = sorted(
        range(n_teams),
        key=lambda i: (future_scores[i], dynasty_values[i] + pick_values[i], -rosters[i].roster_id),
        reverse=True,
    )
    future_ranks = [0] * n_teams
    for rank, idx in enumerate(future_order, start=1):
        future_ranks[idx] = rank

    cut = max(1, (n_teams + 2) // 4)
    median_picks = float(median(pick_values)) if pick_ledger else None

    windows: List[TeamWindow] = []
    for i, r in enumerate(rosters):
        val = val_by_id.get(r.roster_id)
        team_name = val.team_name if (val and r.team_name == "Unknown" and val.team_name) else r.team_name
        diagnosed = _diagnose_window(win_now_ranks[i], n_teams, cut)
        pivot_lean, pivot_reason = _resolve_pivot(
            diagnosed,
            win_now_ranks[i],
            cut,
            pick_values[i],
            median_picks,
            starter_pcts[i],
        )
        is_target = target_roster_id is None or r.roster_id == target_roster_id
        effective_target, target_source = _resolve_target(
            diagnosed,
            is_target,
            window_mode,
            mode_override,
        )
        flags = _asset_flags(
            team_assets[i],
            starter_id_sets[i],
            set(r.taxi),
            set(r.reserve),
            season_phase,
            effective_target,
            pivot_lean,
            is_dynasty,
        )
        windows.append(
            TeamWindow(
                roster_id=r.roster_id,
                team_name=team_name,
                diagnosed=diagnosed,
                effective_target=effective_target,
                target_source=target_source,
                pivot_lean=pivot_lean,
                pivot_reason=pivot_reason,
                win_now_score=win_now_scores[i],
                win_now_rank=win_now_ranks[i],
                future_score=future_scores[i],
                future_rank=future_ranks[i],
                starter_win_now_value=starter_values[i],
                max_pf=r.max_pf,
                dynasty_player_value=dynasty_values[i],
                pick_value=pick_values[i],
                season_phase=season_phase,
                flags=flags,
            )
        )

    windows.sort(key=lambda w: w.win_now_rank)
    return windows


def _win_now_side(assets: Sequence[Asset]) -> Tuple[int, List[str]]:
    """Sum known redraft values on one side (picks = 0); collect players missing redraft_value."""
    total = 0
    missing: List[str] = []
    for a in assets:
        if a.is_pick:
            continue
        if a.redraft_value is None:
            missing.append(a.name)
            continue
        total += a.redraft_value
    return total, missing


def _future_side(assets: Sequence[Asset]) -> int:
    """Sum future equity across picks, ascending players, and unredrafted rookies/stashes."""
    total = 0
    for a in assets:
        if a.is_pick:
            total += a.value
        elif a.redraft_value is None:
            if a.value >= 1000:
                total += a.value
        else:
            gap = value_redraft_gap(a, 1000)
            if gap is not None and gap > 0:
                total += a.value
    return total


def _duration_filter(
    evaluation: TradeEvaluation,
    team_window: Optional[TeamWindow],
) -> DecisionFilter:
    if team_window is None:
        return DecisionFilter(
            name="Duration",
            signal="N/A",
            summary="No team window available; set config user/team to evaluate window fit.",
        )

    win_a, missing_a = _win_now_side(evaluation.side_a.assets)
    win_b, missing_b = _win_now_side(evaluation.side_b.assets)
    net_win_now = win_a - win_b

    fut_a = _future_side(evaluation.side_a.assets)
    fut_b = _future_side(evaluation.side_b.assets)
    net_future = fut_a - fut_b

    details = [
        f"Net win-now shift: {net_win_now:+,d}",
        f"Net future shift: {net_future:+,d}",
    ]
    missing_names = list(dict.fromkeys([*missing_a, *missing_b]))
    if missing_names:
        details.append(
            f"Excluded from win-now delta (no redraft value): {', '.join(missing_names)}"
        )

    target = team_window.effective_target
    signal: FilterSignal
    summary: str

    if target == "contend":
        if net_win_now >= _MEANINGFUL_SHIFT:
            signal = "ALIGNED"
            summary = f"Contender adds {net_win_now:+,d} win-now redraft value."
        elif net_win_now <= -_MEANINGFUL_SHIFT:
            signal = "MISMATCH"
            if net_future > 0:
                summary = f"Contender gives up {abs(net_win_now):,d} win-now value for future equity."
            else:
                summary = f"Contender loses {abs(net_win_now):,d} win-now redraft value."
        else:
            signal = "NEUTRAL"
            summary = "Minimal net change to immediate contending production."
    elif target == "rebuild":
        if net_future >= _MEANINGFUL_SHIFT and net_win_now <= 0:
            signal = "ALIGNED"
            summary = f"Rebuilder gains {net_future:+,d} future equity without adding win-now bloat."
        elif net_future <= -_MEANINGFUL_SHIFT:
            signal = "MISMATCH"
            if net_win_now >= _MEANINGFUL_SHIFT:
                summary = (
                    f"Rebuilder spends {abs(net_future):,d} future equity for {net_win_now:+,d} win-now points."
                )
            else:
                summary = f"Rebuilder loses {abs(net_future):,d} future equity."
        elif net_win_now >= _MEANINGFUL_SHIFT:
            signal = "CAUTION"
            summary = f"Rebuilder takes on {net_win_now:+,d} win-now value that can inflate Max PF."
        else:
            signal = "NEUTRAL"
            summary = "Minimal net impact on rebuild timeline."
    else:
        adds_win_now = net_win_now >= _MEANINGFUL_SHIFT
        loses_win_now = net_win_now <= -_MEANINGFUL_SHIFT
        adds_future = net_future >= _MEANINGFUL_SHIFT
        loses_future = net_future <= -_MEANINGFUL_SHIFT
        lean = team_window.pivot_lean

        if adds_win_now and adds_future:
            signal = "ALIGNED"
            summary = (
                f"Middle-trap team improves both win-now ({net_win_now:+,d}) "
                f"and future ({net_future:+,d}) equity."
            )
        elif adds_win_now and not adds_future:
            if lean == "PIVOT_REBUILD":
                signal = "MISMATCH"
                summary = (
                    f"Middle-trap team (pivot rebuild) adds {net_win_now:+,d} win-now value "
                    "against its rebuild lean."
                )
            else:
                signal = "CAUTION"
                note = "matches PIVOT_CONTEND lean" if lean == "PIVOT_CONTEND" else "commits toward contend"
                summary = (
                    f"Middle-trap team pushes toward contend ({note}; "
                    f"win-now {net_win_now:+,d}, future {net_future:+,d})."
                )
        elif adds_future and not adds_win_now:
            if lean == "PIVOT_CONTEND":
                signal = "MISMATCH"
                summary = (
                    f"Middle-trap team (pivot contend) sells {abs(net_win_now):,d} win-now value "
                    f"for future equity ({net_future:+,d})."
                )
            else:
                signal = "CAUTION"
                note = "matches PIVOT_REBUILD lean" if lean == "PIVOT_REBUILD" else "commits toward rebuild"
                summary = (
                    f"Middle-trap team pushes toward rebuild ({note}; "
                    f"win-now {net_win_now:+,d}, future {net_future:+,d})."
                )
        elif loses_win_now or loses_future:
            signal = "MISMATCH"
            summary = (
                f"Middle-trap team loses horizon value without offsetting gain "
                f"(win-now {net_win_now:+,d}, future {net_future:+,d})."
            )
        else:
            signal = "NEUTRAL"
            summary = "Small horizon shift leaves middle-trap posture unchanged."

    return DecisionFilter(name="Duration", signal=signal, summary=summary, details=details)


def _is_aging_expensive_rb(a: Asset) -> bool:
    return (
        not a.is_pick
        and a.position == "RB"
        and a.value >= 1500
        and a.age is not None
        and a.age >= 26
    )


def _is_cheap_rb2(a: Asset) -> bool:
    return (
        not a.is_pick
        and a.position == "RB"
        and a.depth_chart_order == 2
        and a.value < 2000
    )


def _format_aging_rbs(rbs: Sequence[Asset]) -> str:
    return ", ".join(
        f"{a.name} (age {a.age:.0f}, val {a.value:,})"
        for a in rbs
        if a.age is not None
    )


def _rb_option_filter(
    evaluation: TradeEvaluation,
    team_window: Optional[TeamWindow],
    season_phase: SeasonPhase,
) -> DecisionFilter:
    acquired_aging = [a for a in evaluation.side_a.assets if _is_aging_expensive_rb(a)]
    sold_aging = [a for a in evaluation.side_b.assets if _is_aging_expensive_rb(a)]
    acquired_rb2 = [a for a in evaluation.side_a.assets if _is_cheap_rb2(a)]

    is_offseason = season_phase.phase in ("offseason_draft", "offseason_quiet")
    target = team_window.effective_target if team_window is not None else None
    effective_lean: Optional[str] = None
    if target == "contend" or (
        target == "middle_trap" and team_window is not None and team_window.pivot_lean == "PIVOT_CONTEND"
    ):
        effective_lean = "contend"
    elif target == "rebuild" or (
        target == "middle_trap" and team_window is not None and team_window.pivot_lean == "PIVOT_REBUILD"
    ):
        effective_lean = "rebuild"

    details: List[str] = []
    if acquired_aging:
        details.append(f"Acquiring aging RB(s): {_format_aging_rbs(acquired_aging)}")
    if sold_aging:
        details.append(f"Selling aging RB(s): {_format_aging_rbs(sold_aging)}")
    if acquired_rb2:
        details.append(
            "Acquiring RB2 backup call option(s): "
            + ", ".join(f"{a.name} (val {a.value:,})" for a in acquired_rb2)
        )

    signal: FilterSignal
    summary: str

    if acquired_aging:
        max_age = max(a.age for a in acquired_aging if a.age is not None)
        if is_offseason or effective_lean == "rebuild":
            signal = "MISMATCH"
            why = "in offseason" if is_offseason else "while rebuilding"
            summary = f"Acquiring age-{max_age:.0f} RB {why} absorbs decay with no title equity."
        elif effective_lean == "contend":
            if max_age >= 28:
                signal = "CAUTION"
                summary = f"Acquiring age-{max_age:.0f} RB carries steep age-cliff risk in-season."
            else:
                signal = "ALIGNED"
                summary = f"In-season age-{max_age:.0f} RB acquisition fits win-now usage."
        else:
            if max_age >= 28:
                signal = "CAUTION"
                summary = f"Acquiring age-{max_age:.0f} RB carries age-cliff risk (team window unknown)."
            else:
                signal = "NEUTRAL"
                summary = f"In-season age-{max_age:.0f} RB option depends on unconfigured team window."
    elif sold_aging and (is_offseason or effective_lean == "rebuild"):
        max_sold_age = max(a.age for a in sold_aging if a.age is not None)
        signal = "TAILWIND"
        why = "during offseason" if is_offseason else "while rebuilding"
        summary = f"Offloading age-{max_sold_age:.0f} RB option {why} avoids uncompensated decay."
    elif acquired_rb2:
        signal = "ALIGNED"
        summary = "Acquiring cheap RB2 backup adds asymmetric contingent call-option upside."
    else:
        signal = "NEUTRAL"
        summary = "No material RB option-decay or backup call-option exposure."

    return DecisionFilter(name="RB Option Risk", signal=signal, summary=summary, details=details)


def _has_status(a: Asset, statuses: FrozenSet[str]) -> bool:
    if a.is_pick:
        return False
    status_l = (a.status or "").strip().lower()
    inj_l = (a.injury_status or "").strip().lower()
    return status_l in statuses or inj_l in statuses


def _side_liquidity(assets: Sequence[Asset]) -> Tuple[int, int, int]:
    picks = sum(a.value for a in assets if a.is_pick)
    injured_stars = sum(
        a.value
        for a in assets
        if not a.is_pick and a.value >= 2500 and _has_status(a, _SERIOUS_INJURY_STATUSES)
    )
    discounted = picks + injured_stars
    vets = 0
    for a in assets:
        if a.is_pick or _has_status(a, _NON_ACTIVE_VET_STATUSES):
            continue
        if a.value >= 2000 and (a.redraft_value or 0) >= 2500:
            gap = value_redraft_gap(a, 1000)
            if (gap if gap is not None else 0.0) <= 10.0:
                vets += a.value
    return picks, discounted, vets


def _seasonal_liquidity_filter(
    evaluation: TradeEvaluation,
    season_phase: SeasonPhase,
) -> DecisionFilter:
    picks_get, discounted_get, vets_get = _side_liquidity(evaluation.side_a.assets)
    picks_give, discounted_give, vets_give = _side_liquidity(evaluation.side_b.assets)

    details = [
        f"Phase: {season_phase.label} ({season_phase.liquidity_bias})",
        f"Picks get/give: {picks_get:,} / {picks_give:,}",
        f"Discounted (picks + injured stars) get/give: {discounted_get:,} / {discounted_give:,}",
        f"Healthy proven vets get/give: {vets_get:,} / {vets_give:,}",
    ]

    signal: FilterSignal
    summary: str

    if season_phase.phase == "in_season_peak":
        if (discounted_get - discounted_give) >= _SEASONAL_SHIFT and (
            vets_give - vets_get
        ) >= _SEASONAL_SHIFT:
            signal = "TAILWIND"
            summary = "Selling peak-priced Oct-Nov points for discounted picks/injured stars."
        elif (discounted_give - discounted_get) >= _SEASONAL_SHIFT and (
            vets_get - vets_give
        ) >= _SEASONAL_SHIFT:
            signal = "CAUTION"
            summary = "Paying peak Oct-Nov contender liquidity premium for immediate vet points."
        else:
            signal = "NEUTRAL"
            summary = f"No major Oct-Nov liquidity imbalance ({season_phase.label})."
    elif season_phase.phase == "offseason_draft":
        if (picks_give - picks_get) >= _SEASONAL_SHIFT and (
            vets_get - vets_give
        ) >= _SEASONAL_SHIFT:
            signal = "TAILWIND"
            summary = "Selling Mar-May rookie-draft hype for discounted proven veterans."
        elif (picks_get - picks_give) >= _SEASONAL_SHIFT and (
            vets_give - vets_get
        ) >= _SEASONAL_SHIFT:
            signal = "HEADWIND"
            summary = "Buying rookie picks at peak offseason draft liquidity premium."
        else:
            signal = "NEUTRAL"
            summary = f"No major Mar-May rookie-pick liquidity imbalance ({season_phase.label})."
    else:
        signal = "NEUTRAL"
        summary = f"Neutral seasonal liquidity timing during {season_phase.label}: {season_phase.summary}"

    return DecisionFilter(
        name="Seasonal Liquidity",
        signal=signal,
        summary=summary,
        details=details,
    )


def evaluate_trade_filters(
    evaluation: TradeEvaluation,
    team_window: Optional[TeamWindow],
    season_phase: SeasonPhase,
) -> List[DecisionFilter]:
    """Evaluate Duration, RB Option Risk, and Seasonal Liquidity filters without mutating the trade."""
    if not evaluation.is_dynasty:
        msg = "Dynasty strategy filters do not apply to redraft leagues."
        return [
            DecisionFilter(name="Duration", signal="N/A", summary=msg),
            DecisionFilter(name="RB Option Risk", signal="N/A", summary=msg),
            DecisionFilter(name="Seasonal Liquidity", signal="N/A", summary=msg),
        ]
    return [
        _duration_filter(evaluation, team_window),
        _rb_option_filter(evaluation, team_window, season_phase),
        _seasonal_liquidity_filter(evaluation, season_phase),
    ]
