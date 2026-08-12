# ff

[![CI](https://github.com/savvides/ff/actions/workflows/ci.yml/badge.svg)](https://github.com/savvides/ff/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A command-line tool for managing a Sleeper dynasty fantasy football league -
rankings, trade analyzer, roster valuation, power rankings, lineup optimizer,
waiver targets, live draft board.

## Why a CLI

- **Fast** - no page loads, no ads, answers in milliseconds from cache.
- **Scriptable** - pipe it, cron it, wire it into your own tools.
- **Yours** - runs locally, reads only public league data, no account or
  tracking.
- **Hackable** - pure Python, small, typed contracts between modules, easy to
  extend for your own league's quirks.

**Data sources (all free, no account, read-only):**
- [Sleeper API](https://docs.sleeper.com/) - your league, rosters, matchups,
  transactions, trending adds.
- Sleeper projections (`api.sleeper.com`) - weekly projected stat lines
  (RotoWire), scored by your league's own rules for the lineup optimizer.
- [FantasyCalc API](https://fantasycalc.com/) - dynasty values for players **and
  draft picks**, tagged with `sleeperId` so they join straight onto your roster.

## Quickstart

```bash
make install                 # venv + deps + pre-commit hook
./.venv/bin/ff setup <your-sleeper-username>
./.venv/bin/ff power
./.venv/bin/ff roster
./.venv/bin/ff values -p WR
./.venv/bin/ff lineup                 # optimal start/sit for the current week
./.venv/bin/ff trade --give "Jahmyr Gibbs, 2026 2nd" --get "Bijan Robinson, 2027 1st"
./.venv/bin/ff waivers
./.venv/bin/ff ask "Should I trade Jahmyr Gibbs and a 2026 2nd for Bijan Robinson?"
```

`setup` reads your league's settings from Sleeper and **auto-detects the format**
(superflex/1QB, PPR, team count), so the values are always right for your league -
you never configure that by hand. Picks are first-class: `2027 1st`, `2026 2nd`,
`2026 Pick 1.05` all resolve to a value in `trade`.

## Commands

- `ff ask "<query>" [--backend B]` - ask questions in natural language (e.g., `"Should I trade Gibbs for Bijan?"`, `"Who should I start at FLEX?"`, `"Connect Sleeper account <username>"`). Uses your terminal's active AI subscription runner (`agy`, `gemini`, `claude`, `ollama`) with zero API keys, executing deterministic Python tools under the hood and synthesizing plain-English explanations.
- `ff config set-llm <backend> [--model M]` - set preferred LLM backend (`auto`, `agy`, `gemini`, `claude`, `ollama`) and optional model (e.g. `--model llama3.2`).
- `ff setup <username> [--season Y] [--league-id ID] [-n INDEX]` - pick a
  league (or `-n` to pick the Nth from the printed list non-interactively),
  detect format, save it to `.ff/config.json`.
- `ff roster [team] [--top N]` - price a roster: total value, power rank,
  positional breakdown, top assets.
- `ff power` - league power rankings by dynasty value, next to W-L record.
- `ff picks [team] [--years N] [--rounds N]` - future draft capital by team:
  every pick's current owner (reconciled through traded picks), tier-valued
  like `trade`. The half of team value `power` leaves out.
- `ff values [-p QB|RB|WR|TE] [--limit N]` - dynasty rankings for your format.
- `ff trade --give "A, B" --get "C, D"` - value both baskets and call it
  fair / win / lose, with a positional swing. Picks count; ambiguous names get
  a "did you mean" hint.
- `ff waivers [--limit N] [--all]` - trending adds still on waivers in your
  league, ranked by dynasty value (or, with `--all`, including rostered
  players too).
- `ff cleanup [team] [--drops N]` - roster capacity vs. fill: drop candidates
  (worst value first, flagged if the drop frees an active slot) and
  taxi-stash suggestions that free active room without dropping anyone.
- `ff movers [--buy] [--limit N] [--min-value N]` - sell-high (win-now >
  dynasty) or, with `--buy`, buy-low (dynasty > win-now) candidates by value
  gap; `--min-value` (default 1000) floors both values so deep stashes don't
  dominate.
- `ff lineup [team] [--week N] [--season Y]` - optimal start/sit for a week,
  scored by your league's exact rules (TEP included), with the start/sit moves
  vs your current lineup. Defaults to the current/upcoming week.
- `ff draft [-p QB|RB|WR|TE] [--limit N] [-r] [--mode contend|rebuild|auto]
  [--draft-id ID]` - live draft board scored FOR your team: your picks, where
  you stand vs the league, and best available ranked by fit (roster need +
  win-now/rebuild horizon), not raw market value alone.
- `ff version` - print the ff version.

## Development

```bash
make test          # gate suite - offline, deterministic, < 2s
make test-live     # contract checks against the real APIs
FF_LIVE_LEAGUE_ID=<a completed league id> make test-live   # also runs the traded-picks + draft-shape canaries
./.venv/bin/pytest tests/test_trade.py::test_trade_with_players_and_picks   # one test
```

See `CLAUDE.md` for architecture and the design decisions behind it.

## Limits (by design)

- **`roster` and `power` value rostered players only**, not draft picks.
  Whole-team pick ownership is reconciled from `traded_picks` and tier-valued
  by `ff picks` - kept out of roster/power totals on purpose, so player value
  and draft capital stay separately legible.
- **Lineup projections are single-source** (RotoWire, via Sleeper) and exclude
  K/DEF unless your league starts them. TEP *is* applied here, because `lineup`
  scores the raw projected stats with your league's settings - only the
  FantasyCalc *dynasty values* (`values`/`roster`/`trade`) are not TEP-adjusted.
- **No trade *finder* and no tiers/VORP yet.** `trade` evaluates a deal you
  specify; it does not scan the league to propose one. Rankings are raw value,
  without tier breaks or value-over-replacement.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, the test lanes, and PR
expectations.

## License

MIT - see [LICENSE](LICENSE).
