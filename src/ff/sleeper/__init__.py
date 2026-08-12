"""Sleeper API client + league-shape helpers.

Free, auth-free, read-only. Turns Sleeper's raw JSON into the shared contract
(`Format`, `Roster`) so the rest of the app never touches Sleeper's wire format.
"""

from ff.sleeper.client import (
    SleeperClient,
    build_rosters,
    detect_format,
    player_name,
    team_names,
)

__all__ = ["SleeperClient", "detect_format", "build_rosters", "player_name", "team_names"]
