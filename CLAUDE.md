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

- `contracts/models.py` is the only thing that crosses module boundaries (pydantic models: `Format`, `Asset`, `Roster`, `RosterValuation`, `RosterSlot`, `RosterAudit`, `TradeSide`, `TradeEvaluation`, `WaiverTarget`). `Asset` deliberately covers both players and picks, because a dynasty trade is a basket of both. `Roster` also carries `taxi` and `reserve` (IR): subsets of `player_ids` that do not occupy an active slot, which is what `RosterAudit` needs to tell active room from taxi/IR room. Changing a model here is a contract change; update both sides.
- `core/` is cross-cutting infra with no football logic: `http.py` (disk-cached, retrying JSON GET) and `config.py` (`.ff/` state plus the saved `Config`).
- `sleeper/client.py` wraps the API and, more importantly, holds `detect_format()` and `build_rosters()`, pure helpers that translate Sleeper's settings into the contract.
- `values/client.py` fetches FantasyCalc and builds a `ValueBook` with three lookups: by sleeper id (exact, for rosters), by name (fuzzy, for typed trade input), and by pick label.
- `projections/client.py` fetches Sleeper's weekly projections (the `api.sleeper.com` host, not `api.sleeper.app`) and returns `{player_id: stat_line}`. It keeps the raw stats, not Sleeper's precomputed points, so the lineup optimizer can score them with the league's own settings.
- `analysis/` (`roster.py`, `trade.py`, `waivers.py`, `movers.py`, `lineup.py`, `fit.py`, `cleanup.py`) is pure: same input, same output, no I/O. `movers.py` ranks buy-low/sell-high from the dynasty-vs-redraft value gap (with a `min_value` floor; the gap formula is shared via `value_redraft_gap`). `lineup.py` scores projected stat lines with the league's `scoring_settings` (TEP applied for TEs) and assigns players to starting slots; the greedy "most-restrictive slot first" assignment is optimal because standard slot eligibility (QB/RB/WR/TE/FLEX/SUPER_FLEX) is laminar. That assignment is factored into a score-agnostic `_assign(positions, scores, starting)` primitive plus `starting_slots`/`starting_slot_counts`, so `fit.py` reuses it scored by dynasty value. `fit.py` is the team-relative draft scorer: it keeps FantasyCalc value as the anchor and layers bounded, status-weighted tilts for roster fit (starter-upgrade over *your own* lineup) and win-now/rebuild horizon (the shared redraft gap). It never reads format-scarcity (`superflex`/`num_qbs`) or age, both already inside the value, so it does not double-count.
- `cli.py` wires the commands: `setup`, `roster`, `power`, `picks`, `values`, `lineup`, `trade`, `movers`, `waivers`, `cleanup`, `draft`. The `@_guard` decorator turns the two expected real-world failures (unreachable API, corrupt config) into clean one-line errors while preserving each command's Typer signature.
- `analysis/cleanup.py` powers `cleanup` (roster capacity + drop/taxi suggestions). `audit_roster()` categorizes each player as START/BENCH/TAXI/IR, computes active vs taxi vs IR capacity, and ranks two levers: drop candidates (non-starters, worst value first, each flagged whether the drop frees an *active* slot) and taxi candidates (taxi-eligible bench players best-first, capped at open taxi slots, that free active room without dropping anyone). The key distinction it encodes: dropping a taxi/IR player frees a taxi/IR slot but no active room, so only a bench drop or a taxi stash opens a waiver slot. `taxi_eligible()` follows Sleeper's rule (`taxi_allow_vets` lets anyone stash; otherwise experience must be within the `taxi_years` rookie window). Reads `taxi_slots`/`reserve_slots`/`taxi_allow_vets`/`taxi_years` from the league `settings`.
- `analysis/picks.py` powers `picks` (future draft capital by team). Sleeper has no per-team pick endpoint, so `pick_ledger()` derives ownership: every team owns its own pick per (season, round) unless a `traded_picks` row reassigns it, and a re-traded pick's LAST row is current (all rows keep `roster_id` = the original team). Valuation is tier-aware via `price_pick()`: FantasyCalc prices near-season rounds as Early/Mid/Late, and `pick_tier()` picks the tier from the ORIGINAL team's power rank (thirds: top = late, bottom = early — a bad team's own 1st is an early one), falling back to the flat round value, then 0 (never guessed). The CLI scopes "future" to seasons after the latest draft's season (the current year's board belongs to `draft`). Round count comes from the league's `draft_rounds` setting first, the latest draft's `settings.rounds` only as a fallback (in a first-year league that draft is the 20+-round startup, which would fabricate future picks), with `--rounds` as the explicit override; independently, `pick_ledger()` extends the round range to cover any traded pick's round so owned capital is never silently dropped.
- `analysis/draft.py` powers `draft` (live draft board): `pick_number()` handles linear/snake/3rd-round-reversal ordering, `my_picks()` resolves owned picks through `slot_to_roster_id` + `traded_picks`, and `available()` ranks the undrafted/unrostered pool via `ValueBook.top(exclude=...)`. The `draft` command then runs that pool through `fit.rank_fits` so the board is scored FOR your team: it loads your roster and competitive status first (auto-detected from power rank, overridable with `--mode contend|rebuild|auto`), shows a "where you stand" table (your startable value per position vs the league median), and ranks "best available — FOR YOU" by FitScore with the raw market rank alongside. TEs carry a `*` flag because FantasyCalc has no TEP param (honest annotation, never a value bump). The draft endpoints in `sleeper/client.py` use `ttl=0` (the board moves pick to pick); the command must read the single `draft/{id}` endpoint, not the `drafts` list, because only the former returns `slot_to_roster_id`.

### Why modules, not HTTP services

The global services-first rule is satisfied here by module boundaries plus a shared schema package, which that rule explicitly allows. This is a local CLI that joins two read-only APIs; standing up running HTTP microservices would violate the same rulebook's "simplest vanilla wins." Each module is parallel-session-safe because it depends only on `contracts`, never on another module's internals. If this grows a long-running component, that is the point to revisit.

### The keystone: format auto-detection

`detect_format()` in `sleeper/client.py` derives superflex/1QB, PPR, and team count from the league's own Sleeper settings (`roster_positions`, `scoring_settings.rec`, `total_rosters`, `settings.type`). FantasyCalc returns different values per format, so this is what keeps values correct for the user's league. Never ask the user for format; Sleeper already knows it.

### Picks

FantasyCalc returns draft picks as assets with `position == "PICK"` and names like `2026 Pick 1.05`, `2026 1st`, `2027 1st`, and tiered `2027 1st (Early)/(Mid)/(Late)`. `normalize_pick()` in `values/client.py` canonicalizes user input to match, keeping the tier as a key suffix (`2027 1 early`) — without it the three tiers collapse onto one key and the last one loaded silently overwrites the rest (a real bug that undervalued every early 1st). `ValueBook.resolve()` falls back from a slot pick (`2026 1.07`) to the round-level value, from a tiered ask to the flat round value when no tiered entry exists, and from a flat ask to Mid when only tiered entries exist.

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

- Pick value in `roster`/`power`: those total rostered players only. Whole-team pick ownership IS now reconciled (`analysis/picks.py` consumes `traded_picks`) and shown by `ff picks`, but it is deliberately kept out of the `roster`/`power` totals so player value and draft capital stay separately legible; each command's footer points at the other. Do not fold picks into roster/power without a decision to change that.
- TEP (tight-end premium): `lineup` honors it, because it scores raw projected stats with the league's `scoring_settings`. FantasyCalc *dynasty values* still do not: FantasyCalc's public endpoint has no TEP parameter (verified: passing one is a no-op), so `values`/`roster`/`trade` are not TEP-adjusted. Do not add a dead param; `Format.tep` is detected and shown in the label so the gap is visible.
- Trade finder and tiers/league-VORP: `trade` evaluates a specified deal, it does not propose one; `values`/`roster`/`power` rankings are raw value with no tier breaks. Note `draft` *does* now apply a roster-relative starter-upgrade in `fit.py` (value over *your own* lineup), which is deliberately distinct from a format-VORP that would re-price the league scarcity FantasyCalc already bakes in; that format-VORP is intentionally NOT added (it would double-count). Tiers and a trade finder are still reasonable next features.
- First latent feature (e.g. a natural-language "should I make this trade" explanation) is where `services/llm/` (shelling out to local Claude Code) and an eval suite get added. Until then everything is deterministic and gate-tested only.
