"""The analysis layer - pure functions over the contract + a ValueBook.

No I/O here. Everything is same-input-same-output, which is exactly why the test
suite is deterministic gate tests (see CLAUDE.md): roster math and trade math are
deterministic-space work, not latent-space work.
"""

from ff.analysis.cleanup import audit_roster, taxi_eligible
from ff.analysis.draft import available, my_picks, pick_number
from ff.analysis.fit import detect_status, positional_standing, rank_fits
from ff.analysis.lineup import (
    optimal_lineup,
    project_points,
    projected_points,
    starting_slots,
)
from ff.analysis.movers import find_arbitrage_movers, top_movers, value_redraft_gap
from ff.analysis.picks import pick_ledger, pick_tier, price_pick
from ff.analysis.roster import value_all_rosters, value_roster
from ff.analysis.trade import (
    analyze_trade,
    evaluate_trade,
    ktc_position_deltas,
    position_deltas,
)
from ff.analysis.waivers import waiver_targets
from ff.contracts import ArbitrageMover

__all__ = [
    "value_roster",
    "value_all_rosters",
    "analyze_trade",
    "evaluate_trade",
    "position_deltas",
    "ktc_position_deltas",
    "waiver_targets",
    "top_movers",
    "value_redraft_gap",
    "find_arbitrage_movers",
    "ArbitrageMover",
    "optimal_lineup",
    "project_points",
    "projected_points",
    "starting_slots",
    "pick_number",
    "my_picks",
    "available",
    "pick_ledger",
    "pick_tier",
    "price_pick",
    "rank_fits",
    "detect_status",
    "positional_standing",
    "audit_roster",
    "taxi_eligible",
]

