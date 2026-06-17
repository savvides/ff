"""The analysis layer - pure functions over the contract + a ValueBook.

No I/O here. Everything is same-input-same-output, which is exactly why the test
suite is deterministic gate tests (see CLAUDE.md): roster math and trade math are
deterministic-space work, not latent-space work.
"""

from ff.analysis.movers import top_movers
from ff.analysis.roster import value_all_rosters, value_roster
from ff.analysis.trade import analyze_trade, position_deltas
from ff.analysis.waivers import waiver_targets

__all__ = [
    "value_roster",
    "value_all_rosters",
    "analyze_trade",
    "position_deltas",
    "waiver_targets",
    "top_movers",
]
