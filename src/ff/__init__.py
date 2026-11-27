"""ff - manage a Sleeper dynasty league with free data.

Built on free, auth-free, read-only sources:
  * Sleeper API         - your league, rosters, matchups, transactions, trending.
  * FantasyCalc API     - primary dynasty trade values (players + draft picks),
                          keyed by sleeperId so they join onto your roster.
  * DynastyProcess      - default secondary-market dynasty values (opt-in KTC).
  * ESPN & NFL RSS      - kickoff times, game status, and 14-day player news.

The package is split into directory-per-concern modules that share one
contract (`ff.contracts`). See AGENTS.md for why this is in-process modules
rather than HTTP services.
"""

__version__ = "0.1.0"

# macOS system Python links LibreSSL, which makes urllib3 v2 emit a noisy
# NotOpenSSLWarning when it is first imported. Filter by message here (before
# anything imports urllib3) so we do not trigger the warning while suppressing
# it. Harmless for our public HTTPS calls; this just keeps CLI output clean.
import warnings as _warnings  # noqa: E402

_warnings.filterwarnings("ignore", message=r"urllib3 v2 only supports OpenSSL.*")
