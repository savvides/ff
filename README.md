# ff - manage a Sleeper dynasty league without paying FantasyPros

`ff` pulls your Sleeper dynasty league and overlays free dynasty trade values so
you get the things you were paying FantasyPros for - rankings, a trade analyzer,
roster valuation, power rankings, and waiver targets - from the command line.

## Why this exists

FantasyPros' dynasty tools sit behind the MVP/HOF tiers (~$72-108/yr). Almost
everything they give a dynasty manager is available free:

| What you used FantasyPros for | Free replacement here |
| --- | --- |
| Dynasty rankings | `ff values` - FantasyCalc values for *your* format |
| Trade Analyzer (players + picks) | `ff trade --give … --get …` |
| Start/sit & lineup optimizer | `ff lineup` - best lineup by your exact scoring (incl TEP) |
| Roster / team value | `ff roster` (rostered players; picks are valued in `trade`) |
| League power rankings | `ff power` |
| Buy-low / sell-high | `ff movers [--buy]` - dynasty vs win-now value gap |
| Waiver suggestions | `ff waivers` - trending adds joined to value |

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
```

`setup` reads your league's settings from Sleeper and **auto-detects the format**
(superflex/1QB, PPR, team count), so the values are always right for your league -
you never configure that by hand. Picks are first-class: `2027 1st`, `2026 2nd`,
`2026 Pick 1.05` all resolve to a value in `trade`.

## Commands

- `ff setup <username> [--season Y] [--league-id ID]` - pick a league, detect
  format, save it to `.ff/config.json`.
- `ff roster [team] [--top N]` - price a roster: total value, power rank,
  positional breakdown, top assets.
- `ff power` - league power rankings by dynasty value, next to W-L record.
- `ff values [-p QB|RB|WR|TE] [--limit N]` - dynasty rankings for your format.
- `ff lineup [team] [--week N] [--season Y]` - optimal start/sit for a week,
  scored by your league's exact rules (TEP included), with the start/sit moves
  vs your current lineup. Defaults to the current/upcoming week.
- `ff trade --give "A, B" --get "C, D"` - value both baskets and call it
  fair / win / lose, with a positional swing. Picks count; ambiguous names get
  a "did you mean" hint.
- `ff movers [--buy] [--limit N]` - sell-high (win-now > dynasty) or, with
  `--buy`, buy-low (dynasty > win-now) candidates by value gap.
- `ff waivers [--limit N] [--all]` - trending adds that are still free agents in
  your league, ranked by dynasty value.

## Development

```bash
make test          # gate suite - offline, deterministic, < 2s
make test-live     # contract checks against the real APIs
./.venv/bin/pytest tests/test_trade.py::test_trade_with_players_and_picks   # one test
```

See `CLAUDE.md` for architecture and the design decisions behind it.

## Limits (by design)

- **`roster` and `power` value rostered players only**, not draft picks. Picks
  are valued where you name them (`trade`); whole-team pick ownership from
  `traded_picks` is not yet computed, so it is not in roster/power totals.
- **Lineup projections are single-source** (RotoWire, via Sleeper) and exclude
  K/DEF unless your league starts them. TEP *is* applied here, because `lineup`
  scores the raw projected stats with your league's settings - only the
  FantasyCalc *dynasty values* (`values`/`roster`/`trade`) are not TEP-adjusted.
- **No trade *finder* and no tiers/VORP yet.** `trade` evaluates a deal you
  specify; it does not scan the league to propose one. Rankings are raw value,
  without tier breaks or value-over-replacement.
