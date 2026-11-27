"""Dynasty values from FantasyCalc (free, auth-free) and secondary markets.

FantasyCalc returns one value per asset - players *and* draft picks - and tags
each player with `sleeperId`, so values join straight onto a Sleeper roster.
DynastyProcess (default) and KeepTradeCut (opt-in) provide secondary market
values. This module fetches them for a given `Format` and exposes lookups by
sleeper id, by player name (fuzzy), and by pick label.
"""

from ff.values.client import ValueBook, ValuesClient
from ff.values.dp import DynastyProcessClient
from ff.values.ktc import KtcClient
from ff.values.normalize import normalize_name, normalize_pick
from ff.values.snapshot import SecondarySnapshot

# Backward-compatibility alias
DynastyDealerClient = KtcClient

__all__ = [
    "ValuesClient",
    "ValueBook",
    "DynastyProcessClient",
    "KtcClient",
    "DynastyDealerClient",
    "SecondarySnapshot",
    "normalize_name",
    "normalize_pick",
]


