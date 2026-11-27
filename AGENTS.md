# AGENTS.md

This file provides guidance to AI coding agents (Antigravity, Codex, etc.) when working with code in this repository.

## What this is

ff is a CLI to manage a Sleeper dynasty fantasy football league using free, auth-free, read-only APIs:

- Sleeper (`docs.sleeper.com`): league, rosters, users, matchups, transactions, trending adds, players file.
- ESPN scoreboard (`site.api.espn.com`): kickoff times and game status cross-checked against Sleeper for weekly lineup decisions.
- FantasyCalc (`api.fantasycalc.com`): dynasty trade values for players and draft picks.
- DynastyProcess (`github.com/dynastyprocess/data`): default secondary-market dynasty values (merged onto `Asset` as `secondary_value`). KeepTradeCut (`keeptradecut.com`) is opt-in (`--market ktc` or `--ktc-file`, with `ktc_value` and `dealer_value` aliases).
- Sleeper projections (`api.sleeper.com`): weekly stat lines for the lineup optimizer.

The linchpin: every FantasyCalc player carries a `sleeperId`, so values join directly onto a Sleeper roster with no scraping or manual ID mapping.

## Commands

venv-based, Python 3.9.

- Install: `make install` (venv, editable install, enables pre-commit hook). Manual: `python3 -m venv .venv && ./.venv/bin/python -m pip install -e ".[dev]"`.
- Full check: `make check` (runs lint, typecheck, test, and build).
- Lint & typecheck: `make lint` (`./.venv/bin/ruff check`) and `make typecheck` (`./.venv/bin/mypy src`).
- Gate tests (offline, deterministic, under 2s, run by pre-commit hook): `make test`, `uv run pytest -q`, or `./.venv/bin/pytest -q`.
- One test: `./.venv/bin/pytest tests/test_trade.py::test_trade_with_players_and_picks`.
- Live API checks (real network, excluded from gate; set `FF_LIVE_LEAGUE_ID` for the draft-shape check): `make test-live` or `./.venv/bin/pytest -m live`.
- Run CLI: `./.venv/bin/ff <command>` (entry point `ff = ff.cli:app`).
- Snapshot a real league for inspection: `./.venv/bin/python scripts/record_fixtures.py <league_id>` (writes to `samples/`, leaves gate fixtures untouched).
- Calculator oracle (Node 18+, no npm; prints only): `node scripts/calculator_oracle.mjs --check tests/fixtures/calculator_vectors.json` runs FantasyCalc's and KTC's live calculator JS against fixture vectors; `--generate > tests/fixtures/calculator_vectors.json` rebuilds them (after site changes, update `FINGERPRINTS`); `--eval` prices JSON trades like the sites.
- Find passing offers: `./.venv/bin/ff offers --sell "<asset>" [--to <sleeper username or team name>] [--market dp|ktc] [--ktc-file <path>] [--fc-only]` (repeatable flags; defaults: all other teams, `--market dp`; `src/ff/offers.py` / `python -m ff.offers --years <n>` defaults to 3). Ranks passing packages by roster fit (young starter/need value, excluding surplus/flagged pieces, then lineup gain) and prints incoming roles and injury/drop flags.

## Architecture

Directory-per-concern modules under `src/ff/`, sharing one contract. Data flows one direction:

`cli.py` -> `services/` + `sleeper/` + `values/` + `projections/` + `news/` -> `analysis/` (pure functions) -> rich tables.

- `contracts/models.py`: shared Pydantic schema (`Format`, `Asset`, `DraftPickInfo`, `FuturePick`, `TeamPicks`, `Roster`, `StandingProjection`, `FabClaim`, `RosterValuation`, `RosterSlot`, `RosterAudit`, `TradeSide`, `TradeEvaluation`, `OfferVerdict`, `ArbitrageMover`, `WaiverTarget`, `LineupSlot`, `Lineup`, `PositionStanding`, `TeamContext`, `DraftFit`; weekly: `WeeklyPlayer`, `WeeklyContext`, `WeeklyWaiverTarget`, `WeeklyWaivers`, `ComparisonOption`, `PlayerComparison`; news: `NewsItem`, `NewsFlag`, `FeedStatus`, `PlayerNewsBrief`, `NewsReview`; window: `SeasonPhase`, `AssetDurationFlag`, `DecisionFilter`, `TeamWindow`). `Asset` covers players and picks with optional `secondary_value` (`dealer_value`/`ktc_value` aliases). `Roster` `taxi`/`reserve` (IR) are subsets of `player_ids` not occupying active slots. Changing a model is a contract change; update both sides. Analysis imports `ff.sleeper.player_name` and `ff.values.ValueBook` for convenience; add no other cross-imports.
- `core/`: cross-cutting infra with no football logic: `http.py` (disk-cached, retrying JSON GET) and `config.py` (`.ff/` state and `Config`).
- `sleeper/client.py`: API wrapper plus `detect_format()` and `build_rosters()`, pure helpers translating Sleeper settings into the contract.
- `values/client.py`: fetches FantasyCalc and builds `ValueBook` (lookups by sleeper id, fuzzy name, pick label), merged with a pluggable secondary market (`values/snapshot.py` `SecondarySnapshot`). `values/dp.py` (`DynastyProcessClient`) is default; `values/ktc.py` (`KtcClient`) is opt-in (`--market ktc`, `--ktc-file <path>`, or `$FF_HOME/ktc_pool.json` fallback), reading format + TEP tier and recording top value, HTML, and fetch time. `ValuesClient.fetch(..., fresh=True, secondary="dp"|"ktc"|"none", ktc_file=...)` bypasses caches (`ff trade` uses it with `--market`/`--ktc-file`/`--fc-only`). `values/calculators_live.py` checks site bundle names (KTC only when active, fetching `/trade-calculator` if `ktc_html` is empty) and normalized function hashes against `analysis.calculators.FINGERPRINTS`. `values/normalize.py` holds `normalize_name`/`normalize_pick` so client, dp, and ktc stay decoupled.
- `projections/client.py`: fetches Sleeper weekly projections (`api.sleeper.com`, not `api.sleeper.app`) as raw `{player_id: stat_line}` so `lineup.py` scores them with the league's own settings.
- `news/` (`client.py`, `review.py`): fetches Sleeper, ESPN (player feed or NFL-wide fallback), and NFL RSS feeds with `retries=False`; `review_players()` returns `NewsReview`.
- `services/weekly.py`: fetches fresh weekly schedule (`api.sleeper.com`), ESPN scoreboard, and player status; fails closed on unknown kickoff timing; reuses `designation`/`ir_eligible_statuses` from `analysis/cleanup.py`.
- `analysis/` (`roster.py`, `trade.py`, `calculators.py`, `waivers.py`, `weekly_waivers.py`, `depth.py`, `compare.py`, `movers.py`, `lineup.py`, `fit.py`, `cleanup.py`, `picks.py`, `draft.py`, `standings.py`, `plan.py`, `fab.py`, `news.py`, `window.py`) is pure (same input, same output, no I/O):
  - `window.py`: diagnoses competitive window (`CONTEND`/`MIDDLE_TRAP`/`REBUILD`), Max PF, middle-trap pivot lean, RB/duration flags, and seasonal liquidity filters (`detect_season_phase`).
  - `news.py`: deduplicates headlines, derives 14-day `NewsFlag`s, surfaces matched keywords in warnings, and emits the `News feed(s) degraded or unreachable: <providers>.` warning prefix checked strictly by `qa/validators.py` (`validate_news_review`).
  - `calculators.py`: verbatim ports of FantasyCalc (dynasty waiver adjustment) and KTC (`calcAdjustPackageNew`) math with JS numeric semantics; `TradeEvaluation.secondary_is_fair` is pinned to oracle vectors.
  - `trade.py`: applies calculators in `analyze_trade` (totals match site displays; `raw_*` are plain sums). `offer_verdict()` checks <10% of the larger side in both active markets (plus KTC Fair when KTC is active, or FC-only with `--fc-only`), returning PASS/FAIL/CANNOT_JUDGE.
  - `depth.py`: depth chart opportunity multipliers for handcuffs and backups.
  - `compare.py`: head-to-head start/sit comparisons with lineup context and game lock checks.
  - `movers.py`: ranks buy-low/sell-high via dynasty-vs-redraft gap (`min_value` floor) and FC-vs-secondary arbitrage via `find_arbitrage_movers` (restates secondary values as FC values at the same rank before diffing).
  - `lineup.py`: scores stats with `scoring_settings` (TEP for TEs) and assigns **active** players (never taxi/IR) via `_assign()` + `starting_slots` (greedy most-restrictive-first is optimal for laminar slot eligibility).
  - `fit.py`: team-relative draft scorer; anchors on FC value and layers bounded tilts for starter-upgrade over *your own* lineup and shared redraft horizon. Never reads format scarcity or age to avoid double-counting.
  - `standings.py`: seeded Monte Carlo of remaining schedule (`simulate_season`) for expected wins, playoff odds (division winners seed first, optional median game), and expected rookie-draft slot. `cli._season_sim` feeds Sleeper matchups; `cli._finish_ranks` turns draft slots into ranks for `pick_ledger`, falling back to power rank before week 1.
  - `plan.py`: `trade_stance` (seller/buyer/hold from playoff odds, else roster rank), `sell_candidates` (near decline age or win-now premium for sellers), `buy_candidates` (young future value for sellers; underpriced production for buyers).
  - `fab.py`: `winning_bids` joins winning claims to losing bids in the same run (only "claimed by another owner" failures count); `bid_summary` gives median/75th/max.
  - `waivers.py` & `weekly_waivers.py`: unrostered pool by dynasty opportunity or immediate weekly lineup gain.
  - `cleanup.py`: `audit_roster()` categorizes START/BENCH/TAXI/IR and ranks drops (flagging whether it frees an *active* slot—dropping taxi/IR frees no active room), IR moves (active players matching `ir_eligible_statuses()`, skipping healthy scratches Out/"Coach's Decision", capped at open IR slots), and taxi stashes (`taxi_eligible()` via `taxi_allow_vets`/`taxi_years`, excluding IR picks). Shares `ir_eligible_statuses()` and `designation()` with `services/weekly.py`.
  - `picks.py`: `pick_ledger()` derives ownership from endowment + `traded_picks` (LAST row wins; `roster_id` = original team) and extends rounds to cover any traded pick. `price_pick()` tiers via `pick_tier()` from the ORIGINAL team's projected finish (`standings.py`) else power rank (thirds: top=late, bottom=early), falling back to flat round value then 0. CLI scopes future seasons after latest draft and reads `draft_rounds` before draft `settings.rounds` (avoiding startup-draft round inflation), overridable with `--rounds`.
  - `draft.py`: `pick_number()` (linear/snake/3RR), `my_picks()` (`slot_to_roster_id` + `traded_picks`), and `available()` via `ValueBook.top(exclude=...)`, ranked by `fit.rank_fits` (`--mode contend|rebuild|auto`). `*` TE flag appears only when league TEP < +0.5 (annotation only). Draft endpoints use `ttl=0` and MUST read single `draft/{id}` (not `drafts` list) for `slot_to_roster_id`.
- `cli.py`: wires `setup`, `plan`, `standings`, `roster`, `power`, `window`, `picks`, `fab`, `offers`, `values`, `lineup`, `compare`, `news`, `trade`, `movers`, `waivers`, `cleanup`, `draft`, `ask`, `qa` (hidden alias `doctor`), `version`, `config` (`set-llm`, `set-window`). `@_guard` turns unreachable-API/corrupt-config errors into one-line messages while preserving Typer signatures.
- `services/llm/`: `TerminalRunner` shells out to `agy`/`gemini`/`claude`/`ollama` in print/headless mode (no permission-bypass flags, 120s timeout). The model may return one or more JSON tool calls (`_parse_ask_calls`); `dispatch_tool` runs only `ALLOWED_TOOLS` against `_analysis_ctx`. `onboard_user` writes config only when the league is unambiguous; otherwise it tells the user to run `ff setup`.
- `qa/` (`models.py`, `validators.py`, `engine.py`): post-command invariant checks (totals = sum of components, starters <= totals, deltas match differences, no taxi starters, unvalued counts, valid IDs, tool allowlist) and `ff qa` audits. Controlled by `FF_QA` (`off`, `summary`, `verbose`, `strict`).

### Why modules, not HTTP services

Module boundaries plus a shared `contracts` schema satisfy the services-first rule without standing up HTTP microservices for a local read-only CLI. Each module is parallel-session-safe because it depends only on `contracts`, never on another module's internals.

### The keystone: format auto-detection

`detect_format()` in `sleeper/client.py` derives superflex/1QB, PPR, and team count from Sleeper settings (`roster_positions`, `scoring_settings.rec`, `total_rosters`, `settings.type`). Never ask the user for format; Sleeper already knows it.

### Picks

FantasyCalc returns picks (`position == "PICK"`) like `2026 Pick 1.05`, `2026 1st`, `2027 1st`, and tiered `2027 1st (Early)/(Mid)/(Late)`. `normalize_pick()` in `values/normalize.py` canonicalizes rounds 1–9 (ordinals, words, tiers) and keeps the tier suffix (`2027 1 early`)—without it, all three tiers collide on one key and overwrite each other. `ValueBook.resolve()` falls back from slot pick -> round-level, tiered -> flat, and flat -> Mid when only tiered entries exist.

## Testing model

- Gate tests (`tests/test_*.py`, default `pytest` run): offline and deterministic, using curated fixtures in `tests/fixtures/`. The `ff_home` autouse fixture in `conftest.py` redirects `FF_HOME` to a tmp dir; HTTP is mocked with `responses`.
- Live tests (`tests/test_live.py`, marked `live`, excluded by default): hit real APIs for payload-shape drift and calculator parity (drift check, oracle `--check`, and end-to-end `analyze_trade` parity).
- Calculator vectors (`tests/fixtures/calculator_vectors.json`): generated by the JS oracle, never hand-computed; `tests/test_calculators.py` pins Python ports to every vector and requires >=5 vectors per reachable KTC branch.
- Rich console width in CLI tests: `cli.py` instantiates a module-level `Console()`, and `offers.py` reuses `cli.console` dynamically (do not instantiate a fresh `Console()`). CLI tests without `fake_clients` should monkeypatch `ff.cli.console` to `Console(width=200)` so 80-column CI runners do not wrap table cells.

### Why there are no evals

Roster math and trade math are deterministic and gate-tested; `ff ask` only selects tools and wraps Python results in prose. Add evals only if the model starts generating unstructured analysis as the product.

## Gotchas & Conventions

- Target Python 3.9 (`from __future__ import annotations`).
- Local state lives under `FF_HOME` (default `./.ff`, gitignored): `config.json` and `cache/`. Clear with `make clean`.
- Sleeper rate limits are handled in `core/http.py` (players file ~15MB cached 24h; per-endpoint TTLs + urllib3 retry/backoff).
- Config persistence: `save_config()` in `core/config.py` is atomic (PID temp file + `os.replace`, UTF-8).
- `values/dealer.py` is a deprecated legacy compatibility shim pointing to `KtcClient`; add no new code there.
- Mypy targets Python 3.10 in `pyproject.toml` (silencing deprecation warnings) while code preserves Python >=3.9 compatibility.
- DynastyProcess CSVs come from R: filter literal `"NA"` (case-insensitive) sentinels in ID columns, use `max()` on duplicate normalized player names, and isolate `db_playerids.csv` fetch errors from `values.csv`.
- ESPN news quirks: `site.api.espn.com/.../news/players?playerId=...` tags multi-player roundup articles to a player's `espn_id` without naming them in headline/description (assert `any(...)`, not `all(...)`, in live tests), and article fields can be non-strings—guard parsing with `_str_field` and `try`/`except` inside worker pools.
- Sleeper active-player disambiguation: `resolve_player()` prefers `active: True` (else `active is not False`) on duplicate names in the full players file; use boolean `active`, not `status == "Active"` (IR/PUP players remain `active: True`).
- Pydantic test models: `Format` uses `num_teams` (not `teams`) and `Config.season` is `int`; unknown kwargs are silently dropped.
- Worktrees & PR merges: inside `.worktrees/*`, run checks with `uv run` (verify `ff.__file__` resolves inside the worktree, not parent `.venv`). This repo enforces squash-only merges with remote branch auto-delete; run `gh pr merge <pr> --squash` without `--delete-branch` from a worktree.

## Out of scope (and why)

- Pick value in `roster`: totals rostered players only. `power` ranks by player value and keeps pick capital and combined total in separate columns so both stay legible.
- TEP: `lineup` scores raw stats with `scoring_settings`. FantasyCalc takes `tep=te+`/`te++` (numeric values 404), mapped via `Format.fantasycalc_tep()`, and KTC uses the same cut points. Leagues below +0.5 have no FC tier and keep the draft `*` note.
- Tiers/league-VORP: `trade`/`offers` evaluate deals and `values`/`roster`/`power` show raw value without tier breaks. `draft` (`fit.py`) uses starter-upgrade over *your own* lineup, not format-VORP (which would double-count scarcity already in FC values). Tiers remain a future feature.
- `ff ask` lives under `services/llm/`. Keep calculations in `analysis/`; the runner is print-mode only—never pass `--dangerously-skip-permissions` or equivalent.
