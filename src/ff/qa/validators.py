"""Domain-specific invariant validators for ff commands."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from ff.contracts import (
    ArbitrageMover,
    Asset,
    DraftFit,
    DraftPickInfo,
    Lineup,
    NewsItem,
    Roster,
    RosterAudit,
    RosterValuation,
    TeamPicks,
    TradeEvaluation,
    WaiverTarget,
)
from ff.core.config import Config
from ff.services.llm.tools import ALLOWED_TOOLS
from ff.qa.models import QACheck


def validate_setup(config: Config) -> List[QACheck]:
    """Validate league configuration invariants."""
    checks: List[QACheck] = []

    has_league = bool(config.league_id and config.league_id.strip())
    checks.append(QACheck(
        name="Setup League ID Valid",
        passed=has_league,
        message="" if has_league else "League ID is empty or invalid",
    ))

    season_str = str(config.season).strip() if config.season is not None else ""
    has_season = bool(season_str.isdigit() and len(season_str) == 4)
    checks.append(QACheck(
        name="Setup Season Valid",
        passed=has_season,
        message="" if has_season else f"Season '{config.season}' is not a valid 4-digit year",
    ))

    has_user = bool(config.username and config.user_id)
    checks.append(QACheck(
        name="Setup User Identity Valid",
        passed=has_user,
        message="" if has_user else "Username or user_id missing from config",
    ))

    fmt = config.format
    teams_valid = fmt.num_teams >= 2
    checks.append(QACheck(
        name="Setup Team Count Valid",
        passed=teams_valid,
        message="" if teams_valid else f"Team count {fmt.num_teams} must be at least 2",
    ))

    ppr_valid = fmt.ppr >= 0.0
    checks.append(QACheck(
        name="Setup PPR Valid",
        passed=ppr_valid,
        message="" if ppr_valid else f"PPR value {fmt.ppr} cannot be negative",
    ))

    tep_valid = fmt.tep >= 0.0
    checks.append(QACheck(
        name="Setup TEP Valid",
        passed=tep_valid,
        message="" if tep_valid else f"TEP value {fmt.tep} cannot be negative",
    ))

    return checks


def validate_roster(valuation: RosterValuation, target_roster: Optional[Roster] = None) -> List[QACheck]:
    """Validate roster pricing and asset calculation invariants."""
    checks: List[QACheck] = []

    sum_assets = sum(a.value for a in valuation.assets)
    total_match = valuation.total_value == sum_assets
    checks.append(QACheck(
        name="Roster Total Math Match",
        passed=total_match,
        message="" if total_match else f"total_value ({valuation.total_value}) != sum of asset values ({sum_assets})",
    ))

    starters_bound = valuation.starters_value <= valuation.total_value
    checks.append(QACheck(
        name="Roster Starters Value Bound",
        passed=starters_bound,
        message="" if starters_bound else f"starters_value ({valuation.starters_value}) > total_value ({valuation.total_value})",
    ))

    pos_sum = sum(valuation.by_position.values())
    pos_assets = sum(a.value for a in valuation.assets if a.position)
    pos_match = pos_sum == pos_assets
    checks.append(QACheck(
        name="Roster Positional Sum Match",
        passed=pos_match,
        message="" if pos_match else f"by_position sum ({pos_sum}) != asset positions sum ({pos_assets})",
    ))

    rank_valid = valuation.power_rank is None or valuation.power_rank >= 1
    checks.append(QACheck(
        name="Roster Power Rank Valid",
        passed=rank_valid,
        message="" if rank_valid else f"power_rank ({valuation.power_rank}) must be >= 1",
    ))

    assets_valid = all(bool(a.id) and bool(a.name) and a.value >= 0 for a in valuation.assets)
    checks.append(QACheck(
        name="Roster Assets Integrity",
        passed=assets_valid,
        message="" if assets_valid else "One or more assets contain empty ID/name or negative value",
    ))

    if target_roster is not None:
        count_match = (len(valuation.assets) + len(valuation.unvalued)) == len(target_roster.player_ids)
        checks.append(QACheck(
            name="Roster Player Count Match",
            passed=count_match,
            message="" if count_match else f"Valued assets ({len(valuation.assets)}) + unvalued ({len(valuation.unvalued)}) != Sleeper roster count ({len(target_roster.player_ids)})",
        ))

    return checks


def validate_power(valuations: List[RosterValuation], rosters: List[Roster]) -> List[QACheck]:
    """Validate league power rankings invariants."""
    checks: List[QACheck] = []

    count_match = len(valuations) == len(rosters)
    checks.append(QACheck(
        name="Power Rankings Team Count Match",
        passed=count_match,
        message="" if count_match else f"Valuations count ({len(valuations)}) != rosters count ({len(rosters)})",
    ))

    ranks = [v.power_rank for v in valuations if v.power_rank is not None]
    expected_ranks = list(range(1, len(valuations) + 1))
    ranks_correct = sorted(ranks) == expected_ranks
    checks.append(QACheck(
        name="Power Ranks Sequence Valid",
        passed=ranks_correct,
        message="" if ranks_correct else f"Power ranks {ranks} do not form exact sequence 1..{len(valuations)}",
    ))

    # Check monotonicity of valuation total_value descending
    values = [v.total_value for v in valuations]
    sorted_values = sorted(values, reverse=True)
    mono_desc = values == sorted_values
    checks.append(QACheck(
        name="Power Total Value Monotonic Descending",
        passed=mono_desc,
        message="" if mono_desc else "Power rankings are not sorted strictly descending by total_value",
    ))

    roster_ids = {r.roster_id for r in rosters}
    ids_valid = all(v.roster_id in roster_ids for v in valuations)
    checks.append(QACheck(
        name="Power Roster IDs Valid",
        passed=ids_valid,
        message="" if ids_valid else "Valuation references unknown roster_id",
    ))

    records_valid = all(r.wins >= 0 and r.losses >= 0 and r.ties >= 0 and r.points_for >= 0.0 for r in rosters)
    checks.append(QACheck(
        name="Power Records Non-Negative",
        passed=records_valid,
        message="" if records_valid else "One or more teams have negative record statistics",
    ))

    return checks


def validate_picks(ledger: List[TeamPicks], rosters: List[Roster], traded_picks: Optional[List[dict]] = None) -> List[QACheck]:
    """Validate future draft capital ledger invariants."""
    checks: List[QACheck] = []

    count_match = len(ledger) == len(rosters)
    checks.append(QACheck(
        name="Picks Ledger Team Count Match",
        passed=count_match,
        message="" if count_match else f"Picks ledger count ({len(ledger)}) != rosters count ({len(rosters)})",
    ))

    math_valid = all(tp.total_value == sum(p.value for p in tp.picks) for tp in ledger)
    checks.append(QACheck(
        name="Picks Ledger Total Math Match",
        passed=math_valid,
        message="" if math_valid else "TeamPicks total_value does not match sum of individual pick values",
    ))

    values_valid = all(p.value >= 0 for tp in ledger for p in tp.picks)
    checks.append(QACheck(
        name="Pick Values Non-Negative",
        passed=values_valid,
        message="" if values_valid else "One or more draft picks have negative value",
    ))

    valid_tiers = {"early", "mid", "late", "Early", "Mid", "Late", None}
    tiers_valid = all(p.tier in valid_tiers for tp in ledger for p in tp.picks)
    checks.append(QACheck(
        name="Pick Tiers Valid",
        passed=tiers_valid,
        message="" if tiers_valid else "One or more draft picks have invalid tier designation",
    ))

    return checks


def validate_values(assets: List[Asset], position: Optional[str] = None, market: str = "both") -> List[QACheck]:
    """Validate dynasty rankings assets invariants."""
    checks: List[QACheck] = []

    assets_valid = all(bool(a.id) and bool(a.name) and a.value >= 0 for a in assets)
    checks.append(QACheck(
        name="Values Assets Integrity",
        passed=assets_valid,
        message="" if assets_valid else "Ranked assets contain empty ID/name or negative value",
    ))

    if position:
        pos_upper = position.upper()
        pos_match = all(a.position == pos_upper for a in assets if a.position)
        checks.append(QACheck(
            name=f"Values Position Filter '{pos_upper}'",
            passed=pos_match,
            message="" if pos_match else f"One or more assets do not match filtered position '{pos_upper}'",
        ))

    if market == "ktc":
        ktc_valid = all(a.ktc_value is not None and a.ktc_value >= 0 for a in assets)
        checks.append(QACheck(
            name="Values KTC Prices Present",
            passed=ktc_valid,
            message="" if ktc_valid else "One or more assets missing KTC value in KTC-only view",
        ))
    elif market == "both":
        ktc_valid = all(a.ktc_value is None or a.ktc_value >= 0 for a in assets)
        checks.append(QACheck(
            name="Values Dual Market Integrity",
            passed=ktc_valid,
            message="" if ktc_valid else "KTC value is negative on one or more assets",
        ))

    return checks


def validate_trade(
    evaluation: TradeEvaluation,
    give_tokens: Optional[List[str]] = None,
    get_tokens: Optional[List[str]] = None,
) -> List[QACheck]:
    """Validate trade analyzer mathematical and arbitrage invariants."""
    checks: List[QACheck] = []

    sum_a = sum(a.value for a in evaluation.side_a.assets)
    sum_b = sum(a.value for a in evaluation.side_b.assets)
    side_a_match = evaluation.value_a == sum_a
    side_b_match = evaluation.value_b == sum_b
    checks.append(QACheck(
        name="Trade Side A & B Math Match",
        passed=side_a_match and side_b_match,
        message="" if (side_a_match and side_b_match) else f"Side values ({evaluation.value_a}, {evaluation.value_b}) != sums ({sum_a}, {sum_b})",
    ))

    delta_match = evaluation.delta == (evaluation.value_a - evaluation.value_b)
    checks.append(QACheck(
        name="Trade Delta Calculation",
        passed=delta_match,
        message="" if delta_match else f"delta ({evaluation.delta}) != value_a ({evaluation.value_a}) - value_b ({evaluation.value_b})",
    ))

    pct_diff_valid = evaluation.pct_diff >= 0.0
    checks.append(QACheck(
        name="Trade Pct Diff Non-Negative",
        passed=pct_diff_valid,
        message="" if pct_diff_valid else f"pct_diff ({evaluation.pct_diff}) cannot be negative",
    ))

    fairness_match = evaluation.is_fair() == (evaluation.pct_diff <= 5.0)
    checks.append(QACheck(
        name="Trade Fairness Threshold Check",
        passed=fairness_match,
        message="" if fairness_match else f"is_fair() inconsistent with pct_diff ({evaluation.pct_diff})",
    ))

    if evaluation.ktc_value_a is not None and evaluation.ktc_value_b is not None:
        ktc_delta_match = evaluation.ktc_delta == (evaluation.ktc_value_a - evaluation.ktc_value_b)
        checks.append(QACheck(
            name="Trade KTC Delta Calculation",
            passed=ktc_delta_match,
            message="" if ktc_delta_match else f"ktc_delta ({evaluation.ktc_delta}) != ktc_a ({evaluation.ktc_value_a}) - ktc_b ({evaluation.ktc_value_b})",
        ))

    return checks


def validate_movers(movers: Any, mode: str = "gap") -> List[QACheck]:
    """Validate movers and arbitrage detection invariants."""
    checks: List[QACheck] = []

    if mode == "arbitrage":
        arb_items: List[ArbitrageMover] = movers
        diffs_valid = all(m.diff == (m.ktc_value - m.fc_value) for m in arb_items)
        checks.append(QACheck(
            name="Arbitrage Diff Calculation",
            passed=diffs_valid,
            message="" if diffs_valid else "One or more arbitrage movers have incorrect diff",
        ))

        pcts_valid = all(m.pct_diff >= 0.0 for m in arb_items)
        checks.append(QACheck(
            name="Arbitrage Pct Diff Non-Negative",
            passed=pcts_valid,
            message="" if pcts_valid else "Arbitrage pct_diff cannot be negative",
        ))

        biases_valid = all(m.market_bias in {"KTC", "FC", "EVEN"} for m in arb_items)
        checks.append(QACheck(
            name="Arbitrage Market Bias Valid",
            passed=biases_valid,
            message="" if biases_valid else "Invalid market bias label",
        ))
    else:
        gap_items: List[Tuple[Asset, float]] = movers
        assets_valid = all(a.value >= 0 and a.redraft_value >= 0 for a, _ in gap_items)
        checks.append(QACheck(
            name="Movers Asset Values Non-Negative",
            passed=assets_valid,
            message="" if assets_valid else "One or more movers have negative dynasty or redraft value",
        ))

    return checks


def validate_lineup(
    lineup: Lineup,
    target_roster: Optional[Roster] = None,
    scoring: Optional[dict] = None,
) -> List[QACheck]:
    """Validate optimal lineup solver invariants."""
    checks: List[QACheck] = []

    slots_sum = round(sum(s.points for s in lineup.slots), 2)
    total_match = abs(lineup.total - slots_sum) <= 0.05
    checks.append(QACheck(
        name="Lineup Total Points Math Match",
        passed=total_match,
        message="" if total_match else f"lineup.total ({lineup.total}) != sum of slot points ({slots_sum})",
    ))

    starter_pids = [s.player_id for s in lineup.slots if s.player_id]
    no_dupes = len(starter_pids) == len(set(starter_pids))
    checks.append(QACheck(
        name="Lineup Unique Starters",
        passed=no_dupes,
        message="" if no_dupes else "Duplicate player placed in multiple starting slots",
    ))

    if target_roster is not None:
        taxi_set = set(str(p) for p in (target_roster.taxi or []))
        reserve_set = set(str(p) for p in (target_roster.reserve or []))
        taxi_in_starters = any(str(pid) in taxi_set for pid in starter_pids)
        reserve_in_starters = any(str(pid) in reserve_set for pid in starter_pids)

        checks.append(QACheck(
            name="Lineup No Taxi Starters",
            passed=not taxi_in_starters,
            message="" if not taxi_in_starters else "Taxi squad player illegally placed in starting lineup",
        ))

        checks.append(QACheck(
            name="Lineup No IR Starters",
            passed=not reserve_in_starters,
            message="" if not reserve_in_starters else "IR/reserve player placed in starting lineup",
        ))

        roster_pids = set(str(p) for p in target_roster.player_ids)
        all_owned = all(str(pid) in roster_pids for pid in starter_pids)
        checks.append(QACheck(
            name="Lineup All Starters Owned",
            passed=all_owned,
            message="" if all_owned else "Starter not present in team roster",
        ))

    return checks


def validate_cleanup(audit: RosterAudit) -> List[QACheck]:
    """Validate roster capacity audit invariants."""
    checks: List[QACheck] = []

    active_match = audit.active_count == (len(audit.starters) + len(audit.bench))
    checks.append(QACheck(
        name="Cleanup Active Count Match",
        passed=active_match,
        message="" if active_match else f"active_count ({audit.active_count}) != starters ({len(audit.starters)}) + bench ({len(audit.bench)})",
    ))

    active_open_match = audit.active_open == (audit.active_cap - audit.active_count)
    checks.append(QACheck(
        name="Cleanup Active Open Math Match",
        passed=active_open_match,
        message="" if active_open_match else f"active_open ({audit.active_open}) != cap ({audit.active_cap}) - count ({audit.active_count})",
    ))

    starter_pids = {s.player_id for s in audit.starters}
    no_starters_in_drops = not any(d.player_id in starter_pids for d in audit.drop_candidates)
    checks.append(QACheck(
        name="Cleanup No Starters In Drops",
        passed=no_starters_in_drops,
        message="" if no_starters_in_drops else "Starting player proposed as drop candidate",
    ))

    bench_pids = {s.player_id for s in audit.bench}
    active_drops_are_bench = all(d.player_id in bench_pids for d in audit.drop_candidates if d.is_active)
    checks.append(QACheck(
        name="Cleanup Active Drops Are Bench",
        passed=active_drops_are_bench,
        message="" if active_drops_are_bench else "Active drop candidate is not from bench",
    ))

    taxi_are_bench = all(t.is_active and t.player_id in bench_pids for t in audit.taxi_candidates)
    checks.append(QACheck(
        name="Cleanup Taxi Candidates Are Bench",
        passed=taxi_are_bench,
        message="" if taxi_are_bench else "Taxi stash candidate is not an active bench player",
    ))

    return checks


def validate_news(
    player_news: Optional[List[NewsItem]] = None,
    injured_assets: Optional[List[Tuple[str, Asset]]] = None,
    trending: Optional[List[dict]] = None,
) -> List[QACheck]:
    """Validate news and injury tracking invariants."""
    checks: List[QACheck] = []

    if player_news is not None:
        items_valid = all(bool(n.title) and bool(n.source) and bool(n.published_date) for n in player_news)
        checks.append(QACheck(
            name="Player News Headlines Integrity",
            passed=items_valid,
            message="" if items_valid else "News item missing title, source, or published date",
        ))

    if injured_assets is not None:
        inj_valid = all(bool(tname) and bool(a.name) and a.value >= 0 for tname, a in injured_assets)
        checks.append(QACheck(
            name="Injured Assets Integrity",
            passed=inj_valid,
            message="" if inj_valid else "Injured assets list contains invalid team or asset",
        ))

    if trending is not None:
        trend_valid = all(bool(item.get("player_id")) and int(item.get("count", 0)) >= 0 for item in trending)
        checks.append(QACheck(
            name="Trending Adds/Drops Integrity",
            passed=trend_valid,
            message="" if trend_valid else "Trending item missing player_id or negative count",
        ))

    return checks


def validate_waivers(targets: List[WaiverTarget], rosters: Optional[List[Roster]] = None) -> List[QACheck]:
    """Validate waiver wire targets invariants."""
    checks: List[QACheck] = []

    targets_valid = all(t.add_count >= 0 and bool(t.asset.id) and bool(t.asset.name) and t.asset.value >= 0 for t in targets)
    checks.append(QACheck(
        name="Waivers Targets Integrity",
        passed=targets_valid,
        message="" if targets_valid else "One or more waiver targets have negative count or invalid asset",
    ))

    if rosters is not None:
        all_rostered_pids = {str(pid) for r in rosters for pid in r.player_ids}
        fa_unowned = all((str(t.asset.id) not in all_rostered_pids) for t in targets if not t.is_rostered)
        checks.append(QACheck(
            name="Waivers Free Agent Ownership Integrity",
            passed=fa_unowned,
            message="" if fa_unowned else "Player marked as free agent is currently on a league roster",
        ))

    return checks


def validate_draft(
    my_picks: List[DraftPickInfo],
    taken: Set[str],
    fits: List[DraftFit],
    team_val: Optional[RosterValuation] = None,
) -> List[QACheck]:
    """Validate live draft board and team-relative fit scoring invariants."""
    checks: List[QACheck] = []

    picks_valid = all(p.pick_no >= 1 and p.round >= 1 for p in my_picks)
    checks.append(QACheck(
        name="Draft Picks Range Valid",
        passed=picks_valid,
        message="" if picks_valid else "Pick number or round < 1",
    ))

    fits_valid = all(f.fit_score >= 0.0 and bool(f.asset.id) and bool(f.asset.name) and f.market_rank >= 1 for f in fits)
    checks.append(QACheck(
        name="Draft Fit Scores Valid",
        passed=fits_valid,
        message="" if fits_valid else "Draft fit entry has negative FitScore or invalid asset",
    ))

    taken_strs = {str(t) for t in taken}
    none_taken = not any(str(f.asset.id) in taken_strs for f in fits)
    checks.append(QACheck(
        name="Draft Available Pool Disjoint From Taken",
        passed=none_taken,
        message="" if none_taken else "Taken/rostered player appeared on available draft board",
    ))

    # Fits should be sorted descending by fit_score
    scores = [f.fit_score for f in fits]
    sorted_scores = sorted(scores, reverse=True)
    scores_desc = scores == sorted_scores
    checks.append(QACheck(
        name="Draft FitScores Sorted Descending",
        passed=scores_desc,
        message="" if scores_desc else "Available players not sorted descending by FitScore",
    ))

    return checks


def validate_ask(tool_name: Optional[str], result: Any, query: str) -> List[QACheck]:
    """Validate natural language query tool execution invariants."""
    checks: List[QACheck] = []

    has_query = bool(query and query.strip())
    checks.append(QACheck(
        name="Ask Query Non-Empty",
        passed=has_query,
        message="" if has_query else "Ask query string is empty",
    ))

    if tool_name is not None:
        tool_allowed = tool_name in ALLOWED_TOOLS or tool_name == "setup_league"
        checks.append(QACheck(
            name=f"Ask Tool '{tool_name}' in ALLOWED_TOOLS",
            passed=tool_allowed,
            message="" if tool_allowed else f"Tool '{tool_name}' not permitted in ALLOWED_TOOLS",
        ))

        result_valid = result is not None
        checks.append(QACheck(
            name="Ask Tool Execution Result Present",
            passed=result_valid,
            message="" if result_valid else "Tool execution returned None",
        ))

    return checks
