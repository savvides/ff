# ff

[![CI](https://github.com/savvides/ff/actions/workflows/ci.yml/badge.svg)](https://github.com/savvides/ff/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/savvides/ff)](https://github.com/savvides/ff/releases/latest)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A fast, local command-line tool for managing a Sleeper dynasty fantasy football league — rankings, trade analyzer, offer finder, multi-market arbitrage, competitive window diagnosis, roster valuation, power rankings, lineup optimizer, waiver targets, multi-source player news review, injury tracking, and live draft board.

## Why a CLI

- **Fast** — no page loads, no ads, answers in milliseconds from local disk cache.
- **Scriptable** — pipe it, cron it, wire it into your own tools.
- **Yours** — runs locally, reads only public league data, zero account or tracking.
- **Hackable** — pure Python, small typed contracts between modules, easy to extend.

**Data sources (all free, public, read-only):**
- [Sleeper API](https://docs.sleeper.com/) — league settings, rosters, matchups, transactions, trending adds/drops, injuries, and player news.
- ESPN scoreboard — UTC kickoff times and game status, cross-checked against Sleeper for weekly lineup decisions.
- Sleeper Projections (`api.sleeper.com`) — weekly projected stat lines (RotoWire), scored by your league's own rules for the lineup optimizer.
- [FantasyCalc API](https://fantasycalc.com/) — primary dynasty values for players **and draft picks**, tagged with `sleeperId` so they join straight onto your roster.
- [DynastyProcess](https://github.com/dynastyprocess/data) — **default** secondary-market dynasty values (players and picks), merged onto `Asset` for dual-market trade evaluation and arbitrage.
- [KeepTradeCut](https://keeptradecut.com/) — **opt-in** crowdsourced secondary market (`--market ktc`, `--ktc-file <path>`, or `$FF_HOME/ktc_pool.json` fallback), with TE+/TE++ tier support and calculator parity.
- **Multi-Source Player News** — Sleeper player news, ESPN player/NFL feeds, ESPN RSS, and ProFootballTalk RSS, aggregated into 14-day risk flags and reviews across decision commands.
- **Local LLM Runners** (`agy`, `gemini`, `claude`, `ollama`) — terminal AI agents executing deterministic Python analysis tools for plain-English Q&A (`ff ask`).

**Expert references:** Use [CBS weekly rankings](https://www.cbssports.com/fantasy/football/rankings/) for manual start/sit review and [Heath Cummings's dynasty rankings](https://www.cbssports.com/fantasy/football/news/dynasty-fantasy-football-updated-rankings/) for long-term roster decisions. Check the analyst, ranking period, scoring format, and update date before comparing. These references do not feed the CLI's calculations; see the [reference guide](docs/expert-ranking-sources.md).

## Installation & Quickstart

Requires **Python 3.9+** (and optionally Node.js 18+ only if running `scripts/calculator_oracle.mjs` to check live calculator JS parity).

```bash
make install                 # create .venv + install editable + enable pre-commit hook
# or: uv sync --extra dev
# or: pip install -e .

./.venv/bin/ff setup <your-sleeper-username>
./.venv/bin/ff power
./.venv/bin/ff window
./.venv/bin/ff plan
./.venv/bin/ff trade --give "Jahmyr Gibbs, 2026 2nd" --get "Bijan Robinson, 2027 1st"
./.venv/bin/ff lineup        # optimal start/sit for the upcoming week
```

`setup` reads your league's settings from Sleeper and **auto-detects the format** (superflex/2QB, PPR, team count, TEP), calibrating all valuations automatically. Picks are first-class assets: `2027 1st`, `2026 2nd`, `2026 Pick 1.05`, `2027 early 1st` all resolve automatically.

---

## Command Reference

### 1. League Setup & Configuration

- **`ff setup <username>`** — Discovers your leagues, resolves your team, auto-detects league scoring rules (superflex/2QB, PPR, team count, TEP), and saves configuration to `.ff/config.json`.
  - `--season Y`: Target season year (defaults to active season).
  - `--league-id ID`: Bind directly to a specific Sleeper league ID.
  - `-n, --league-index N`: Select league non-interactively (0-indexed from list).
  ```bash
  ff setup my_sleeper_user
  ```

- **`ff config set-llm <backend>`** — Configures the backend used by `ff ask`.
  - `backend`: `auto`, `agy`, `gemini`, `claude`, or `ollama`. `auto` selects terminal runners only.
  - `-m, --model M`: Model name when using Ollama (default: `llama3.2`).
  ```bash
  ff config set-llm agy
  ```

- **`ff config set-window <mode>`** — Configures your default competitive window target mode across commands (`window`, `power`, `trade`, `draft`).
  - `mode`: `auto`, `contend`, or `rebuild`.
  ```bash
  ff config set-window contend
  ```

### 2. Roster Valuation, Window & Standings

- **`ff roster [team]`** — Prices out an entire roster using live market values. Computes total dynasty value, power rank, starters value, positional breakdown, and top assets with depth roles, injury tags, and 30-day trends.
  - `team`: Optional team name search (defaults to your own roster).
  - `--top N`: Number of top assets to display in detail (default: `15`).
  ```bash
  ff roster "Gridiron Kings" --top 20
  ```

- **`ff power`** — League power rankings by rostered player value, alongside each team's 3-year draft capital (`picks`), combined `total` and `total #`, W-L record, points scored, Max PF, and diagnosed competitive `window`.
  ```bash
  ff power
  ```

- **`ff window [team]`** — Diagnoses a team's competitive window (`CONTEND`, `MIDDLE TRAP` with pivot lean, or `REBUILD`) from starter win-now equity, Max PF, future equity (dynasty players + picks), RB exposure/duration flags, and seasonal liquidity phase.
  - `team`: Optional team name search (defaults to your own roster).
  - `--mode MODE`: Override target window (`auto`, `contend`, or `rebuild`).
  ```bash
  ff window --mode auto
  ```

- **`ff plan`** — Your team on one page: record, simulated playoff odds and projected draft slot, a trade stance (`seller`, `buyer`, or `hold`), this week's lineup and roster-lock checks, IR/taxi room checks, waiver budget left, trade deadline, which of your players to shop and which players on opposite-stance rosters to target (each with a reason), and a Latest News Review.
  ```bash
  ff plan
  ```

- **`ff standings`** — Standings with expected wins, playoff odds, and projected rookie-draft slot, from 4,000 seeded simulations of the remaining schedule. Division winners seed first; an extra weekly game against the league median is honored when the league uses it.
  ```bash
  ff standings
  ```

- **`ff picks [team]`** — Reconciles whole-team draft capital ownership across all trades, pricing FantasyCalc tiers (Early, Mid, Late) by the original team's projected finish from `ff standings` (or power rank before the first game).
  - `team`: Team name search (omit to view full league draft capital grid).
  - `--years N`: Number of future draft classes to show (default: `2`).
  - `--rounds N`: Rookie rounds per draft (overrides auto-detected league setting).
  ```bash
  ff picks
  ff picks "My Team" --years 3
  ```

- **`ff values`** — Dynasty rankings calibrated to your league's exact settings, supporting dual-market views (FantasyCalc + DynastyProcess by default, or KeepTradeCut opt-in) and positional filters.
  - `-p, --position POS`: Filter by `QB`, `RB`, `WR`, or `TE` (omit for overall).
  - `-m, --market MARKET`: Market source: `both` (default: FC + DynastyProcess), `fc`, `dp`, or `ktc` (alias `dealer`).
  - `--ktc-file PATH`: Load KeepTradeCut values from a local `ktc_pool.json` file.
  - `--limit N`: Number of assets to show (default: `40`).
  ```bash
  ff values -p WR --market both --limit 25
  ```

### 3. Trading & Market Arbitrage

- **`ff trade --give <assets> --get <assets>`** — Multi-market trade analyzer supporting players and draft picks. Prices each side as FantasyCalc and the active secondary market (`dp` by default, or `ktc` opt-in) would — including FantasyCalc's dynasty package adjustment and KTC's `calcAdjustPackageNew` adjustment — on fresh values. Shows the offer rule (under 10% gap in active markets, plus KTC's own Fair Trade verdict when KTC is active, or FC-only with `--fc-only`), Strategy Filters (window alignment, duration, RB exposure, seasonal liquidity), positional swings, market arbitrage, generic pick tier hints, and a Latest News Review. If either site's calculator JS has drifted since `ff`'s port was verified, the offer rule reports `cannot judge` instead of guessing.
  - `--give ASSETS`: Comma-separated assets you send (e.g. `--give "Jahmyr Gibbs, 2026 2nd"`).
  - `--get ASSETS`: Comma-separated assets you receive (e.g. `--get "Bijan Robinson, 2027 1st"`).
  - `-m, --market MARKET`: Valuation model: `dp` (default), `ktc`, `both`, or `fc`.
  - `--ktc-file PATH`: Load KeepTradeCut values from a local `ktc_pool.json` file.
  - `--fc-only`: Evaluate the offer rule using FantasyCalc only.
  - `--mode MODE`: Override window target for strategy filters (`auto`, `contend`, or `rebuild`).
  ```bash
  ff trade --give "Jahmyr Gibbs, 2026 2nd" --get "Bijan Robinson, 2027 1st"
  ff trade --give "2027 1st" --get "Breece Hall" --market ktc
  ```

- **`ff offers --sell <asset>`** — Searches other managers' rosters and tiered picks for packages that pass the offer rule for what you sell, ranked by roster fit: young value that starts for you or fills a below-median position first. Each incoming piece shows its role and warning flags (injury, 30-day drop of 300+, heavily dropped on Sleeper), followed by a Latest News Review across offered and balancer players.
  - `--sell ASSET`: What you sell (repeatable).
  - `--to NAME`: A manager's Sleeper username or team name (repeatable; default: every other team).
  - `--with ASSET`: An asset of yours allowed as a balancer (repeatable; default: vets 27+ and non-1st picks).
  - `--max-age N`, `--limit N`: Oldest player you would take back (default: `26`); packages per manager (default: `5`).
  - `-m, --market MARKET`: Secondary market: `dp` (default) or `ktc`.
  - `--ktc-file PATH`: Load KeepTradeCut values from a local `ktc_pool.json` file.
  - `--fc-only`: Evaluate using FantasyCalc only.
  - Also runnable as `python -m ff.offers --years N` (pick horizon defaults to `3` years).
  ```bash
  ff offers --sell "Tee Higgins" --to "Team Name"
  ```

- **`ff movers`** — Identifies high-leverage trade targets: buy-low / sell-high candidates (dynasty vs redraft value gaps) and cross-market arbitrage opportunities (FantasyCalc vs DynastyProcess or KeepTradeCut, compared at equivalent rank).
  - `--buy`: Show buy-low candidates (dynasty > redraft, or Secondary > FC for arbitrage).
  - `--sell`: Show sell-high candidates (redraft > dynasty, or FC > Secondary for arbitrage).
  - `-a, --arbitrage`: Scan for pricing inefficiencies between FantasyCalc and the active secondary market across league rosters.
  - `-m, --market MARKET`: Market for arbitrage: `dp` (default), `ktc`, `both`, or `fc`.
  - `--ktc-file PATH`: Load KeepTradeCut values from a local `ktc_pool.json` file.
  - `--min-value N`: Floor on both values; filters out deep stashes (default: `1000`).
  - `--limit N`: Max results to display (default: `20`).
  ```bash
  ff movers --arbitrage
  ff movers --buy --min-value 2000
  ```

### 4. Roster Management & Gameday

- **`ff lineup [team]`** — Lineup optimizer scoring weekly stat projections against your league's exact rules (including TEP), using an optimal laminar greedy assignment algorithm, and showing START/SIT deltas vs your current Sleeper starters. Current-week advice refreshes league rules, starters, injuries, and game status, preserves locked slots, separates actual points from remaining projections, gives conditional alternatives for questionable starters, and runs a Latest News Review on active players.
  - `team`: Team name search (defaults to your team).
  - `--week N`: Target NFL week (defaults to active/upcoming week).
  - `--season Y`: Target season year.
  ```bash
  ff lineup
  ff lineup --week 8  # another week is a projection-only scenario, clearly labeled
  ```

- **`ff compare "<player_a>" "<player_b>"`** — Compare two rostered players for current-week start/sit. Shows the best whole lineup with each choice, injury conditions, game-lock constraints, and a Latest News Review. Add `--team "Team Name"` for another roster. Full names, unique names/initials, or Sleeper IDs resolve locally; ambiguity asks for clarification. It can recommend starting both when both fit.
  ```bash
  ff compare "Nico Collins" "Cooper Kupp"
  ```

- **`ff cleanup [team]`** — Roster auditor computing active, taxi, and IR capacity, ranking drop candidates (lowest value non-starters first, flagging whether dropping frees an active slot), highlighting zero-loss IR moves and taxi stashes to open active roster spots, and running a Latest News Review.
  - `team`: Team name search (defaults to your team).
  - `--drops N`: How many drop candidates to list (default: `8`).
  ```bash
  ff cleanup
  ```

- **`ff fab`** — Every team's waiver budget left, this league's winning bids (median, 75th percentile, and max; overall, contested only, and by position), and recent contested claims with the best losing bid, so a bid is anchored to what this league actually pays.
  - `--limit N`: How many recent contested claims to list (default: `12`).
  ```bash
  ff fab --limit 15
  ```

- **`ff news [team]`** — Tracks player health, injury designations, depth-chart roles, and Sleeper 24-hour trending adds/drops across your league or for a specific team, or pulls a full multi-source news briefing for one player.
  - `team`: Filter injuries to a specific team (omit for league-wide).
  - `-p, --player NAME`: Show full merged 14-day news briefing (Sleeper, ESPN, ESPN RSS, ProFootballTalk RSS) with descriptions, links, flags, and feed health for one player.
  - `--limit N`: Number of trending adds/drops to display (default: `15`).
  ```bash
  ff news
  ff news --player "Puka Nacua"
  ```

- **`ff waivers`** — Ranks unrostered active NFL players and market-listed prospects by dynasty opportunity (restricted to positions your league can start), followed by a Latest News Review. Trending adds annotate the results instead of limiting the candidate pool.
  - `--limit N`: Number of waiver targets to show (default: `20`).
  - `--all`: Include currently rostered players (default: unrostered only).
  - `-p, --position POS`: Filter candidates by position before applying the limit.
  - `--trending`: Restrict candidates to the sampled Sleeper trending adds.
  - `--weekly`: Rank the full projected unrostered pool by improvement to your current-week lineup, applying the same locks, availability rules, and Latest News Review. Shows displaced starters, kickoff times, and conditional availability. Zero gain means depth only.
  - Unrostered does not mean immediately claimable. Check waiver claim status in Sleeper.
  ```bash
  ff waivers --limit 20
  ff waivers --weekly --position RB --limit 5
  ```

### 5. Draft Board & AI Assistant

- **`ff draft`** — Live draft board scored specifically for YOUR team: tracks draft order (linear, snake, 3RR), owned picks, and on-the-clock status, positional standings vs league median, and ranks best available players by `FitScore` (market value adjusted for your roster need and competitive horizon).
  - `-p, --position POS`: Filter board to `QB`, `RB`, `WR`, or `TE`.
  - `-r, --rookies`: Show available rookies only.
  - `--mode MODE`: Competitive horizon: `auto` (live window diagnosis, ignoring saved config), `contend`, or `rebuild`.
  - `--draft-id ID`: Manually specify or override draft ID.
  - `--limit N`: Number of available players to display (default: `30`).
  ```bash
  ff draft -r --mode contend
  ```

- **`ff ask "<query>"`** — Natural language Q&A using a terminal AI runner (`agy`, `gemini`, `claude`, or `ollama`) that dispatches up to 3 allowlisted deterministic analysis tools (across 17 tools including `get_team_window`, `get_player_news`, `evaluate_trade`, `get_lineup`, `get_trade_plan`, `get_standings`, and `setup_league`) and synthesizes the results in Markdown.
  - `query`: Natural language question.
  - `--backend BACKEND`: Override backend: `auto`, `agy`, `gemini`, `claude`, or `ollama`.
  ```bash
  ff ask "Should I trade Jahmyr Gibbs and a 2026 2nd for Bijan Robinson?"
  ff ask "Who should I start at FLEX this week?"
  ```

### 6. Diagnostics & Utilities

- **`ff qa`** (hidden alias: **`ff doctor`**) — Runs full-system diagnostic invariant audits across up to 9 league domains (`setup`, `power`, `roster`, `picks`, `values`, `cleanup`, `waivers`, `movers`, `window`).
  - `-v, --verbose`: Show granular check-by-check inspection tables for every audited domain.
  ```bash
  ff qa --verbose
  ```

- **`ff version`** — Prints the installed version of `ff`.
  ```bash
  ff version
  ```

---

## Configuration & Environment Variables

Local state lives under `FF_HOME` (default `./.ff`, gitignored): `config.json`, `cache/`, and optional `ktc_pool.json`.

| Variable | Values | Purpose |
|---|---|---|
| `FF_HOME` | Path (default `./.ff`) | Root directory for `config.json`, `cache/`, and optional `ktc_pool.json`. |
| `FF_QA` | `off` (default), `summary`, `verbose`, `strict` | Controls post-command QA invariant reporting (see below). |
| `FF_LIVE_LEAGUE_ID` | Sleeper league ID | Optional league ID for `make test-live` traded-picks and draft-shape checks. |

## Post-Command QA & Invariant System

`ff` features a built-in automated QA validation engine (`ff.qa`) that executes domain-specific mathematical and logical invariant checks after every command run.

| Mode | `FF_QA` Values | Behavior |
|---|---|---|
| **Silent** (default) | `0`, `off`, unset | Runs checks silently; surfaces a warning only if invariant violations occur. |
| **Summary** | `1`, `summary`, `true`, `on` | Prints a concise 1-line verification footer (e.g. `✔ QA: 5 checks passed (0.4ms)`). |
| **Verbose** | `verbose`, `detail` | Renders a detailed Rich inspection table displaying each individual check and status. |
| **Strict** | `strict` | Raises `QAInvariantError` and immediately halts execution if an invariant fails. |

---

## Architecture & Development

Data flows unidirectionally across clear module boundaries:

$$\text{CLI } (cli.py) \longrightarrow \text{Services & Clients } (services/, sleeper/, values/, projections/, news/) \longrightarrow \text{Contracts } (contracts/) \longrightarrow \text{Pure Analysis } (analysis/) \longrightarrow \text{Rich Output}$$

- [Architecture diagrams](docs/architecture.md)
- [Changelog](CHANGELOG.md)
- [Contributing guide](CONTRIBUTING.md)
- [Agent & developer guide](AGENTS.md)
- [Expert ranking references](docs/expert-ranking-sources.md)

Every analysis module is pure (no I/O; deterministic inputs to outputs). Roster math, trade math, window diagnosis, and draft valuations stay testable without network access.

### Testing

```bash
make check         # full gate: lint (ruff), typecheck (mypy), offline tests, package build
make test          # offline deterministic gate suite (< 2s, run by pre-commit hook)
make test-live     # live contract checks against real APIs (set FF_LIVE_LEAGUE_ID for draft checks)
./.venv/bin/pytest tests/test_trade.py::test_trade_with_players_and_picks   # run single test
node scripts/calculator_oracle.mjs --check tests/fixtures/calculator_vectors.json  # calculator JS parity
```

---

## Limits (by design)

- **`roster` values rostered players only**; `power` ranks by player value and shows draft capital and the combined total in separate columns, so who wins now and who owns the future stay legible.
- **`standings` simulates scores, not rosters.** Each team scores around its points per game, regressed toward the league average; injuries and trades are not modeled. Draft slot assumes reverse order of standings with playoff teams last, so leagues that order the draft by max points or a lottery will differ.
- **`fab` reports history, not a price.** Sleeper exposes a losing bid only when another team won the player.
- **Lineup projections are single-source** (RotoWire, via Sleeper) and exclude K/DEF unless your league starts them. TEP is applied here because `lineup` scores raw projected stats with your league's rules. For dynasty values, FantasyCalc (`te+`/`te++`) and KeepTradeCut (`TE+`/`TE++`) adjust for TE premium; DynastyProcess does not adjust for TE premium (and prints a note when TEP > 0).
- **Weekly advice depends on undocumented public feeds.** Unknown game timing freezes existing assignments and excludes affected bench/waiver candidates. Conflicting or unavailable feeds can stop advice; they never fall back to stale injury tags as if fresh. AutoSub leagues, best-ball, and unsupported lineup slots refuse actionable advice. Invalid IR eligibility or roster capacity must be resolved in Sleeper. News headlines retain their dates and sources; they do not produce invented injury odds or projection discounts. Actual points for in-progress games exclude the unplayed remainder.
- **No tiers/VORP.** Rankings are raw values without tier breaks or league-wide replacement level.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for developer environment setup, test lanes, and PR expectations.

## License

MIT — see [`LICENSE`](LICENSE).
