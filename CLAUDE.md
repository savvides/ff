# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

ff is a command-line tool to manage a Sleeper dynasty fantasy football league using only free data, as a replacement for a paid FantasyPros subscription. It joins two free, auth-free, read-only APIs:

- Sleeper (docs.sleeper.com): league, rosters, users, matchups, transactions, trending adds, the players file.
- FantasyCalc (api.fantasycalc.com): dynasty trade values for players and draft picks.

The linchpin: every FantasyCalc player carries a `sleeperId`, so values join directly onto a Sleeper roster with no scraping and no manual ID mapping.

## Commands

venv-based, Python 3.9.

- Install: `make install` (venv, editable install, enables the pre-commit hook). Manual: `python3 -m venv .venv && ./.venv/bin/python -m pip install -e ".[dev]"`.
- Gate tests (offline, deterministic, under 2s, run by the pre-commit hook): `make test` or `./.venv/bin/pytest -q`.
- One test: `./.venv/bin/pytest tests/test_trade.py::test_trade_with_players_and_picks`.
- Live API checks (real network, excluded from the gate): `make test-live` or `./.venv/bin/pytest -m live`.
- Run the CLI: `./.venv/bin/ff <command>` (entry point `ff = ff.cli:app`).
- Snapshot a real league for inspection: `./.venv/bin/python scripts/record_fixtures.py <league_id>` (writes to `samples/`, does not touch gate fixtures).

## Architecture

Directory-per-concern modules under `src/ff/`, all sharing one contract. Data flows one direction:

`cli.py` -> `sleeper/` (league + format) + `values/` (FantasyCalc book) -> `analysis/` (pure functions) -> rich tables.

- `contracts/models.py` is the only thing that crosses module boundaries (pydantic models: `Format`, `Asset`, `Roster`, `RosterValuation`, `TradeSide`, `TradeEvaluation`, `WaiverTarget`). `Asset` deliberately covers both players and picks, because a dynasty trade is a basket of both. Changing a model here is a contract change; update both sides.
- `core/` is cross-cutting infra with no football logic: `http.py` (disk-cached, retrying JSON GET) and `config.py` (`.ff/` state plus the saved `Config`).
- `sleeper/client.py` wraps the API and, more importantly, holds `detect_format()` and `build_rosters()`, pure helpers that translate Sleeper's settings into the contract.
- `values/client.py` fetches FantasyCalc and builds a `ValueBook` with three lookups: by sleeper id (exact, for rosters), by name (fuzzy, for typed trade input), and by pick label.
- `projections/client.py` fetches Sleeper's weekly projections (the `api.sleeper.com` host, not `api.sleeper.app`) and returns `{player_id: stat_line}`. It keeps the raw stats, not Sleeper's precomputed points, so the lineup optimizer can score them with the league's own settings.
- `analysis/` (`roster.py`, `trade.py`, `waivers.py`, `movers.py`, `lineup.py`) is pure: same input, same output, no I/O. `movers.py` ranks buy-low/sell-high from the dynasty-vs-redraft value gap (with a `min_value` floor). `lineup.py` scores projected stat lines with the league's `scoring_settings` (TEP applied for TEs) and assigns players to starting slots; the greedy "most-restrictive slot first" assignment is optimal because standard slot eligibility (QB/RB/WR/TE/FLEX/SUPER_FLEX) is laminar.
- `cli.py` wires the commands: `setup`, `roster`, `power`, `values`, `lineup`, `trade`, `movers`, `waivers`, `draft`. The `@_guard` decorator turns the two expected real-world failures (unreachable API, corrupt config) into clean one-line errors while preserving each command's Typer signature.
- `analysis/draft.py` powers `draft` (live draft board): `pick_number()` handles linear/snake/3rd-round-reversal ordering, `my_picks()` resolves owned picks through `slot_to_roster_id` + `traded_picks`, and `available()` ranks the undrafted/unrostered pool via `ValueBook.top(exclude=...)`. The draft endpoints in `sleeper/client.py` use `ttl=0` (the board moves pick to pick); the command must read the single `draft/{id}` endpoint, not the `drafts` list, because only the former returns `slot_to_roster_id`.

### Why modules, not HTTP services

The global services-first rule is satisfied here by module boundaries plus a shared schema package, which that rule explicitly allows. This is a local CLI that joins two read-only APIs; standing up running HTTP microservices would violate the same rulebook's "simplest vanilla wins." Each module is parallel-session-safe because it depends only on `contracts`, never on another module's internals. If this grows a long-running component, that is the point to revisit.

### The keystone: format auto-detection

`detect_format()` in `sleeper/client.py` derives superflex/1QB, PPR, and team count from the league's own Sleeper settings (`roster_positions`, `scoring_settings.rec`, `total_rosters`, `settings.type`). FantasyCalc returns different values per format, so this is what keeps values correct for the user's league. Never ask the user for format; Sleeper already knows it.

### Picks

FantasyCalc returns draft picks as assets with `position == "PICK"` and names like `2026 Pick 1.05`, `2026 1st`, `2027 1st`. `normalize_pick()` in `values/client.py` canonicalizes user input to match, and `ValueBook.resolve()` falls back from a slot pick (`2026 1.07`) to the round-level value (`2026 1st`) when the exact slot is not valued.

## Testing model

Two lanes, per the repo's gate-vs-periodic split:

- Gate tests (`tests/test_*.py`, the default `pytest` run): offline and deterministic. They use small curated fixtures in `tests/fixtures/`, not full recorded payloads (which would be large and would drift). The `ff_home` autouse fixture in `conftest.py` redirects `FF_HOME` to a tmp dir so tests never read or write the real config or cache. HTTP is mocked with `responses`.
- Live tests (`tests/test_live.py`, marked `live`, excluded by default): hit the real APIs to catch upstream payload-shape drift. Run before shipping.

### Why there are no evals

The MVP is fully deterministic: roster math and trade math are same-input-same-output, which the deterministic-space rule puts in code, not in an LLM. There is no latent component to evaluate, so there are gate tests and no eval suite, and no `services/llm/`. Add both only when a genuinely latent feature is built, for example a plain-English "should I make this trade" explanation. Do not invent evals for deterministic logic.

## Conventions

- Target Python 3.9. Use `from __future__ import annotations` for modern type-hint syntax.
- All local state lives under `FF_HOME` (default `./.ff`, gitignored): `config.json` and `cache/`. Clear with `make clean`.
- Sleeper's limits are handled in `core/http.py`: the players file (~15MB) is cached 24h; everything stays well under 1000 req/min via per-endpoint TTLs and urllib3 retry/backoff.

## Out of scope (and why)

- Pick value in `roster`/`power`: those total rostered players only. Picks are valued where the user names them (`trade`). Adding them to roster/power needs whole-team pick ownership, which means reconciling each team's default pick endowment with `traded_picks` (fetched by `SleeperClient.traded_picks` but not yet consumed). Until then, do not claim roster/power include picks.
- TEP (tight-end premium): `lineup` honors it, because it scores raw projected stats with the league's `scoring_settings`. FantasyCalc *dynasty values* still do not: FantasyCalc's public endpoint has no TEP parameter (verified: passing one is a no-op), so `values`/`roster`/`trade` are not TEP-adjusted. Do not add a dead param; `Format.tep` is detected and shown in the label so the gap is visible.
- Trade finder and tiers/VORP: `trade` evaluates a specified deal, it does not propose one; rankings are raw value with no tier breaks or value-over-replacement. Both are reasonable next features.
- First latent feature (e.g. a natural-language "should I make this trade" explanation) is where `services/llm/` (shelling out to local Claude Code) and an eval suite get added. Until then everything is deterministic and gate-tested only.
