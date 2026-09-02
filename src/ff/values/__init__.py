"""Dynasty values from FantasyCalc (free, auth-free) and Dynasty Dealer.

FantasyCalc returns one value per asset - players *and* draft picks - and tags
each player with `sleeperId`, so values join straight onto a Sleeper roster.
Dynasty Dealer provides secondary crowdsourced market values.
This module fetches them for a given `Format` and exposes lookups by sleeper id,
by player name (fuzzy), and by pick label.
"""

from ff.values.client import ValueBook, ValuesClient
from ff.values.dealer import DynastyDealerClient
from ff.values.normalize import normalize_name, normalize_pick

# Backward-compatibility alias
KtcClient = DynastyDealerClient

__all__ = ["ValuesClient", "ValueBook", "DynastyDealerClient", "KtcClient", "normalize_name", "normalize_pick"]


