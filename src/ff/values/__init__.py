"""Dynasty values from FantasyCalc (free, auth-free).

FantasyCalc returns one value per asset - players *and* draft picks - and tags
each player with `sleeperId`, so values join straight onto a Sleeper roster.
This module fetches them for a given `Format` and exposes lookups by sleeper id,
by player name (fuzzy), and by pick label.
"""

from ff.values.client import ValueBook, ValuesClient
from ff.values.ktc import KtcClient
from ff.values.normalize import normalize_name, normalize_pick

__all__ = ["ValuesClient", "ValueBook", "KtcClient", "normalize_name", "normalize_pick"]

