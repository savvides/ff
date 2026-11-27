# Changelog

All notable changes to `ff` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-11-27

Initial public release of `ff`, a local command-line tool for managing Sleeper dynasty fantasy football leagues using free, auth-free, read-only data sources.

### Added
- **League Setup & Auto-Detection (`ff setup`, `ff config`)**:
  - Automatic league discovery and format detection from Sleeper settings (Superflex/2QB, PPR, team count, and TE premium tiers).
  - `ff config set-llm` to configure `ff ask` terminal backends (`auto`, `agy`, `gemini`, `claude`, `ollama`).
  - `ff config set-window` to persist competitive window target mode (`auto`, `contend`, `rebuild`).
- **Roster Valuation, Standings & Competitive Window**:
  - `ff roster`: Full roster valuation, power rank, positional breakdown, depth roles, injury tags, and 30-day trends.
  - `ff power`: League power rankings combining rostered player values, 3-year draft capital, combined totals, record, points for, Max PF, and diagnosed window.
  - `ff window`: Competitive window diagnosis (`CONTEND`, `MIDDLE TRAP` with pivot lean, `REBUILD`), Max PF, win-now vs future equity, RB/duration exposure flags, and seasonal liquidity phase.
  - `ff standings`: 4,000-run seeded Monte Carlo regular-season simulation for expected wins, playoff odds (with division winners and median game support), and projected rookie-draft slot.
  - `ff picks`: Future draft capital ledger reconciling endowment with traded picks, tier-priced (`early`/`mid`/`late`) by each original team's projected finish.
  - `ff plan`: Single-page team plan combining standings outlook, trade stance (`seller`/`buyer`/`hold`), weekly lineup/IR/taxi/FAB checks, and shop/target recommendations.
- **Pluggable Multi-Market Trade & Arbitrage Engine**:
  - FantasyCalc primary valuations joined directly via `sleeperId`, plus pluggable secondary markets: DynastyProcess (`dp`, default) and KeepTradeCut (`ktc`, opt-in via `--market ktc`, `--ktc-file`, or `$FF_HOME/ktc_pool.json` fallback), plus `--fc-only`.
  - `ff trade`: Multi-market trade evaluator porting FantasyCalc's dynasty waiver adjustment and KeepTradeCut's `calcAdjustPackageNew` math (verified against live site JS via `scripts/calculator_oracle.mjs`), offer rule (<10% gap + KTC Fair verdict), Strategy Filters, generic pick tier hints, and live calculator drift detection.
  - `ff offers`: Read-only trade package search across league managers and tiered future picks, ranked by roster fit and lineup gain.
  - `ff values` and `ff movers`: Format-calibrated dynasty rankings, dynasty-vs-redraft buy-low/sell-high movers, and rank-restated cross-market arbitrage (`--arbitrage`).
- **Weekly Lineup, Start/Sit, Waivers, Cleanup & FAB**:
  - `ff lineup`: Weekly lineup optimizer scoring raw Sleeper projections with exact league scoring rules (including TEP), laminar greedy slot assignment, ESPN + Sleeper schedule/lock cross-checks, actual vs remaining points, and conditional questionable-player alternatives.
  - `ff compare`: Head-to-head current-week start/sit comparison with game-lock and whole-lineup context.
  - `ff waivers`: Dynasty opportunity waiver rankings and `--weekly` whole-lineup gain rankings over the unrostered pool.
  - `ff cleanup`: Active/taxi/IR capacity audit, drop candidates, zero-loss IR moves, and taxi stash recommendations.
  - `ff fab`: League FAB budget tracking and historical winning/contested bid statistics.
- **Multi-Source Player News Review (`ff news`)**:
  - Aggregates Sleeper player news, ESPN player/NFL news, ESPN RSS, and ProFootballTalk RSS into 14-day risk flags and feed-health warnings across `news`, `trade`, `offers`, `plan`, `lineup`, `compare`, `waivers`, and `cleanup`.
- **Team-Relative Live Draft Board (`ff draft`)**:
  - Live draft tracker (linear, snake, 3RR) with owned picks, on-the-clock status, positional standings vs league median, and `FitScore` rankings tailored to roster need and competitive horizon.
- **Local AI Q&A (`ff ask`)**:
  - Dispatches up to 3 allowlisted deterministic analysis tools per query across 17 tools using local terminal runners (`agy`, `gemini`, `claude`, `ollama`).
- **Post-Command QA Invariant Engine (`ff qa` / `ff doctor` / `FF_QA`)**:
  - Automated invariant verification across 9 league domains with `off`, `summary`, `verbose`, and `strict` telemetry modes.
- **Tooling & CI**:
  - Offline deterministic `pytest` gate suite, `ruff` linting, `mypy` type checking, `uv build` packaging, pre-commit hook, and GitHub Actions CI matrix across Python 3.9–3.12.

[Unreleased]: https://github.com/savvides/ff/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/savvides/ff/releases/tag/v0.1.0
