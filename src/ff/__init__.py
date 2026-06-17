"""ff - manage a Sleeper dynasty league with free data.

A FantasyPros replacement built on two free, auth-free sources:
  * Sleeper API      - your league, rosters, matchups, transactions, trending.
  * FantasyCalc API  - dynasty trade values (players + draft picks), keyed by
                       sleeper_id so they join straight onto your roster.

The package is split into directory-per-concern modules that share one
contract (`ff.contracts`). See CLAUDE.md for why this is in-process modules
rather than HTTP services.
"""

__version__ = "0.1.0"

# macOS system Python links LibreSSL, which makes urllib3 v2 emit a noisy
# NotOpenSSLWarning when it is first imported. Filter by message here (before
# anything imports urllib3) so we do not trigger the warning while suppressing
# it. Harmless for our public HTTPS calls; this just keeps CLI output clean.
import warnings as _warnings  # noqa: E402

_warnings.filterwarnings("ignore", message=r"urllib3 v2 only supports OpenSSL.*")
