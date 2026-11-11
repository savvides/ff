# ff

[![CI](https://github.com/savvides/ff/actions/workflows/ci.yml/badge.svg)](https://github.com/savvides/ff/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A fast, local command-line tool for managing a Sleeper dynasty fantasy football league — rankings, trade analyzer, multi-market arbitrage, roster valuation, power rankings, lineup optimizer, waiver targets, injury tracking, and live draft board.

## Why a CLI

- **Fast** — no page loads, no ads, answers in milliseconds from local disk cache.
- **Scriptable** — pipe it, cron it, wire it into your own tools.
- **Yours** — runs locally, reads only public league data, zero account or tracking.
- **Hackable** — pure Python, small typed contracts between modules, easy to extend.

**Data sources (all free, public, read-only):**
- [Sleeper API](https://docs.sleeper.com/) — league settings, rosters, matchups, transactions, trending adds, injuries, and player news.
- ESPN scoreboard supplies UTC kickoff times, cross-checked against Sleeper game status.
- Sleeper Projections (`api.sleeper.com`) — weekly projected stat lines (RotoWire), scored by your league's own rules for the lineup optimizer.
- [FantasyCalc API](https://fantasycalc.com/) — dynasty values for players **and draft picks**, tagged with `sleeperId` so they join straight onto your roster.
- [KeepTradeCut](https://keeptradecut.com/) — crowdsourced secondary market values, joined against FantasyCalc to identify arbitrage opportunities.
- Local LLM Runners (`agy`, `gemini`, `claude`, `ollama`) — terminal AI agents executing deterministic Python analysis tools for plain-English Q&A.

**Expert references:** Use [CBS weekly rankings](https://www.cbssports.com/fantasy/football/rankings/) for manual start/sit review and [Heath Cummings's dynasty rankings](https://www.cbssports.com/fantasy/football/news/dynasty-fantasy-football-updated-rankings/) for long-term roster decisions. Check the analyst, ranking period, scoring format, and update date before comparing. These references do not feed the CLI's calculations; see the [reference guide](docs/expert-ranking-sources.md).

## Quickstart

```bash
make install                 # create venv + install dependencies + enable pre-commit hook
./.venv/bin/ff setup <your-sleeper-username>
./.venv/bin/ff power
./.venv/bin/ff roster
./.venv/bin/ff trade --give "Jahmyr Gibbs, 2026 2nd" --get "Bijan Robinson, 2027 1st" --market both
./.venv/bin/ff lineup        # optimal start/sit for the upcoming week
```

`setup` reads your league's settings from Sleeper and **auto-detects the format** (superflex/1QB, PPR, team count, TEP), calibrating all valuations automatically. Picks are first-class assets: `2027 1st`, `2026 2nd`, `2026 Pick 1.05`, `2027 early 1st` all resolve automatically.

---

## Command Reference

### 1. League Setup & Configuration

- **`ff setup <username>`** — Discovers your leagues, resolves your team, auto-detects league scoring rules (superflex, PPR, team count, TEP), and saves configuration to `.ff/config.json`.
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

### 2. Roster Valuation & Standings

- **`ff roster [team]`** — Prices out an entire roster using live market values. Computes total dynasty value, power rank, starters value, positional breakdown, and top assets with injury tags and 30-day trends.
  - `team`: Optional team name search (defaults to your own roster).
  - `--top N`: Number of top assets to display in detail (default: 15).
  ```bash
  ff roster "Gridiron Kings" --top 20
  ```

- **`ff power`** — Generates league-wide power rankings by total dynasty player value, paired with current W-L records and total points scored.
  ```bash
  ff power
  ```

- **`ff picks [team]`** — Reconciles whole-team draft capital ownership across all trades, applying power-ranked tier valuation (Early, Mid, Late) to 1st and 2nd round picks.
  - `team`: Team name search (omit to view full league draft capital grid).
  - `--years N`: Number of future draft classes to show (default: 2).
  - `--rounds N`: Rookie rounds per draft (overrides auto-detected league setting).
  ```bash
  ff picks
  ff picks "My Team" --years 3
  ```

- **`ff values`** — Dynasty rankings calibrated to your league's exact settings, supporting dual-market views (FantasyCalc + KeepTradeCut) and positional filters.
  - `-p, --position POS`: Filter by `QB`, `RB`, `WR`, or `TE` (omit for overall).
  - `-m, --market MARKET`: Market source: `both` (default), `fc` (FantasyCalc), or `ktc` (KeepTradeCut; alias `dealer`).
  - `--limit N`: Number of assets to show (default: 40).
  ```bash
  ff values -p WR --market both --limit 25
  ```

### 3. Trading & Market Arbitrage

- **`ff trade --give <assets> --get <assets>`** — Multi-market trade analyzer supporting players and draft picks. Prices each side exactly as fantasycalc.com and keeptradecut.com would, including both sites' package adjustments for uneven deals (and KTC's for 1-for-1s), on live values, and shows the offer rule (under 10% gap in both markets, and KTC's own verdict Fair), fairness, positional swings, market arbitrage, and where the numbers came from. If either site has changed its calculator code since ff's port was verified, the rule says "cannot judge" instead of guessing.
  - `--give ASSETS`: Comma-separated assets you send (e.g. `--give "Jahmyr Gibbs, 2026 2nd"`).
  - `--get ASSETS`: Comma-separated assets you receive (e.g. `--get "Bijan Robinson, 2027 1st"`).
  - `-m, --market MARKET`: Valuation model: `both` (default), `fc`, or `ktc`.
  ```bash
  ff trade --give "Jahmyr Gibbs, 2026 2nd" --get "Bijan Robinson, 2027 1st" --market both
  ```

- **`ff movers`** — Identifies high-leverage trade targets: buy-low / sell-high candidates (dynasty vs redraft value gaps) and cross-market arbitrage opportunities (FantasyCalc vs KeepTradeCut discrepancies).
  - `--buy`: Show buy-low candidates (dynasty > redraft, or KTC > FC for arbitrage).
  - `--sell`: Show sell-high candidates (redraft > dynasty, or FC > KTC for arbitrage).
  - `-a, --arbitrage`: Scan for pricing inefficiencies between FantasyCalc and KeepTradeCut across league rosters.
  - `--min-value N`: Floor on both values; filters out deep stashes (default: 1000).
  - `--limit N`: Max results to display (default: 20).
  ```bash
  ff movers --arbitrage
  ff movers --buy --min-value 2000
  ```

### 4. Roster Management & Gameday

- **`ff lineup [team]`** — Lineup optimizer scoring weekly stat projections against your league's exact rules (including TEP), using an optimal laminar greedy assignment algorithm, and showing START/SIT deltas vs your current Sleeper starters. Current-week advice refreshes league rules, starters, injuries and game status, preserves locked slots, and separates actual points from remaining projections. Questionable starters get conditional alternatives and decision deadlines.
  - `team`: Team name search (defaults to your team).
  - `--week N`: Target NFL week (defaults to active/upcoming week).
  - `--season Y`: Target season year.
  ```bash
  ff lineup
  ff lineup --week 8  # another week is a projection-only scenario, clearly labeled
  ```

- **`ff compare "Nico Collins" "Cooper Kupp"`** — Compare two players on your roster for current-week start/sit. Shows the best whole lineup with each choice, injury conditions and lock constraints. Add `--team "Team Name"` for another roster. Full names, unique names/initials, or Sleeper IDs resolve locally; ambiguity asks for clarification. It can recommend starting both when both fit.

- **`ff cleanup [team]`** — Roster auditor computing active, taxi, and IR capacity, ranking drop candidates (lowest value non-starters first) and highlighting zero-loss IR moves (players whose designation your league allows on IR) and taxi stashes to open active roster spots for waiver adds.
  - `team`: Team name search (defaults to your team).
  - `--drops N`: How many drop candidates to list (default: 8).
  ```bash
  ff cleanup
  ```

- **`ff news [team]`** — Tracks player health, injury designations, depth-chart roles, and Sleeper 24-hour trending adds/drops across your league or for a specific team.
  - `team`: Filter injuries to a specific team (omit for league-wide).
  - `--limit N`: Number of trending adds/drops to display (default: 15).
  ```bash
  ff news
  ```

- **`ff waivers`** — Ranks unrostered active NFL players and market-listed prospects by dynasty opportunity, restricted to positions your league can start. Trending adds annotate the results instead of limiting the candidate pool.
  - `--limit N`: Number of waiver targets to show (default: 20).
  - `--all`: Include currently rostered players (default: unrostered only).
  - `--position RB`: Filter candidates by position before applying the limit.
  - `--trending`: Restrict candidates to the sampled Sleeper trending adds.
  - `--weekly`: Rank the full projected unrostered pool by improvement to your current-week lineup, applying the same locks and availability rules. Shows displaced starters, kickoff times and conditional availability. Zero gain means depth only. Gains assume acquisition before kickoff and roster room; no drop is selected.
  - Unrostered does not mean immediately claimable. Check waiver claim status in Sleeper. Without `--weekly`, rankings use dynasty value and depth-chart opportunity.
  ```bash
  ff waivers --limit 20
  ff waivers --weekly --position RB --limit 5
  ```

### 5. Draft Board & AI Assistant

- **`ff draft`** — Live draft board scored specifically for YOUR team: tracks draft order (snake, linear, 3RR), owned picks, and on-the-clock status, positional standings vs league median, and ranks best available players by `FitScore` (market value adjusted for your roster need and competitive horizon).
  - `-p, --position POS`: Filter board to `QB`, `RB`, `WR`, or `TE`.
  - `-r, --rookies`: Show available rookies only.
  - `--mode MODE`: Competitive horizon: `auto` (reads power rank), `contend`, or `rebuild` (default: `auto`).
  - `--draft-id ID`: Manually specify or override draft ID.
  - `--limit N`: Number of available players to display (default: 30).
  ```bash
  ff draft -r --mode contend
  ```

- **`ff ask "<query>"`** — Natural language Q&A using a terminal AI runner for explanations.
  - `query`: Natural language question.
  - `--backend BACKEND`: Override backend: `auto`, `agy`, `gemini`, `claude`, or `ollama`.
  ```bash
  ff ask "Should I trade Jahmyr Gibbs and a 2026 2nd for Bijan Robinson?"
  ff ask "Who should I start at FLEX this week?"
  ```

### 6. Diagnostics & Utilities

- **`ff qa`** — Runs full-system diagnostic invariant audits across all league domains (setup configuration, roster valuations, power rankings, future draft pick ledger, market value books, roster cleanup capacity, trending waivers, and market arbitrage).
  - `-v, --verbose`: Show granular check-by-check inspection tables for every audited domain.
  ```bash
  ff qa --verbose
  ```

- **`ff version`** — Prints installed version of `ff`.
  ```bash
  ff version
  ```

---

## Post-Command QA & Invariant System

`ff` features a built-in automated QA validation engine (`ff.qa`) that executes domain-specific mathematical and logical invariant checks after every command run.

### Telemetry Modes (`FF_QA`)

Control post-command QA telemetry output via the `FF_QA` environment variable:

| Mode | Values | Behavior |
|---|---|---|
| **Silent** (default) | `FF_QA=0`, `off`, unset | Runs checks silently; surfaces a warning only if invariant violations occur. |
| **Summary** | `FF_QA=1`, `summary`, `true`, `on` | Prints a concise 1-line verification footer (e.g. `✔ QA: 5 checks passed (0.4ms)`). |
| **Verbose** | `FF_QA=verbose`, `detail` | Renders a detailed Rich inspection table displaying each individual check and status. |
| **Strict** | `FF_QA=strict` | Raises `QAInvariantError` and immediately halts execution if an invariant fails. |

---

## Architecture & Development

Data flows unidirectionally across clear module boundaries:

$$\text{CLI } (cli.py) \longrightarrow \text{Clients } (sleeper/, values/, projections/) \longrightarrow \text{Contracts } (contracts/) \longrightarrow \text{Pure Analysis } (analysis/) \longrightarrow \text{Rich Output}$$

> Diagrams: [docs/architecture.md](docs/architecture.md)

Every analysis module is pure (no I/O; deterministic inputs to outputs). Roster math, trade math, and draft valuations stay testable without network access.

> For in-depth architecture notes, domain models, and developer guidelines, see [**`CLAUDE.md`**](CLAUDE.md).

### Testing

```bash
make test          # gate suite — offline, deterministic, < 2s (run by pre-commit hook)
make test-live     # contract checks against the real Sleeper & FantasyCalc APIs
pytest tests/test_trade.py::test_trade_with_players_and_picks   # run single test
```

---

## Limits (by design)

- **`roster` and `power` value rostered players only**, not draft picks. Whole-team pick ownership is derived from `traded_picks` and tiered by `ff picks` — kept out of roster/power totals so player value and draft capital remain separately legible.
- **Lineup projections are single-source** (RotoWire, via Sleeper) and exclude K/DEF unless your league starts them. TEP is applied here because `lineup` scores raw projected stats with your league's rules; dynasty values are TEP-adjusted in both markets too (FantasyCalc `te+`/`te++`, KTC TE+/TE++).
- **Weekly advice depends on undocumented public feeds.** Unknown game timing freezes existing assignments and excludes affected bench/waiver candidates. Conflicting or unavailable feeds can stop advice; they never fall back to stale injury tags as if fresh. AutoSub leagues, best-ball and unsupported lineup slots refuse actionable advice. Invalid IR eligibility or roster capacity must be resolved in Sleeper. News headlines retain their dates and sources; they do not produce invented injury odds or projection discounts. Actual points for in-progress games exclude the unplayed remainder.
- **No trade *finder* command and no tiers/VORP yet.** `trade` evaluates a deal you specify; `scripts/find_offers.py` is a developer script that searches a manager's roster for packages passing the offer rule, ranked by roster fit (young pieces that start for you or fill a need first), with a reason and warning flags for each incoming piece. Rankings are raw values without tier breaks or league-wide replacement level.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for developer environment setup, test lanes, and PR expectations.

## License

MIT — see [`LICENSE`](LICENSE).
