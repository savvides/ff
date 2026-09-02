# ff

[![CI](https://github.com/savvides/ff/actions/workflows/ci.yml/badge.svg)](https://github.com/savvides/ff/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A command-line tool for managing a Sleeper dynasty fantasy football league —
rankings, trade analyzer, multi-market arbitrage, roster valuation, power rankings,
lineup optimizer, waiver targets, injury tracking, and live draft board.

## Why a CLI

- **Fast** — no page loads, no ads, answers in milliseconds from local disk cache.
- **Scriptable** — pipe it, cron it, wire it into your own tools.
- **Yours** — runs locally, reads only public league data, zero account or tracking.
- **Hackable** — pure Python, small typed contracts between modules, easy to extend.

**Data sources (all free, no account, read-only):**
- [Sleeper API](https://docs.sleeper.com/) — league settings, rosters, matchups, transactions, trending adds, injuries, and player news.
- Sleeper projections (`api.sleeper.com`) — weekly projected stat lines (RotoWire), scored by your league's own rules for the lineup optimizer.
- [FantasyCalc API](https://fantasycalc.com/) — dynasty values for players **and draft picks**, tagged with `sleeperId` so they join straight onto your roster.
- [KeepTradeCut API](https://keeptradecut.com/) via [Dynasty Daddy](https://dynasty-daddy.com/) — crowdsourced secondary market values, joined against FantasyCalc to identify arbitrage opportunities.
- Local LLM Runners (`agy`, `gemini`, `claude`, `ollama`) — terminal AI agents executing deterministic Python tools for plain-English Q&A.

## Architecture

Data flows unidirectionally across clear module boundaries:

```mermaid
flowchart TD
    subgraph DataSources["Free & Public Data Sources"]
        Sleeper["Sleeper API\n(League, Rosters, Picks, News, Trends)"]
        SleeperProj["Sleeper Projections API\n(Weekly Stat Lines)"]
        FantasyCalc["FantasyCalc API\n(Dynasty & Redraft Trade Values)"]
        KTC["KeepTradeCut via Dynasty Daddy\n(Crowdsourced Secondary Market)"]
        LLM["Local LLM CLI\n(agy / gemini / claude / ollama)"]
    end

    subgraph CoreEngine["ff Core & Caching Layer"]
        Http["core/http.py\n(Disk-cached & retrying JSON client)"]
        Config["core/config.py\n(.ff/config.json)"]
        SleeperClient["sleeper/client.py\n(Format detection & roster builder)"]
        ValuesClient["values/client.py & ktc.py\n(ValueBook with ID/Name/Pick lookup)"]
        ProjClient["projections/client.py\n(Raw weekly stat lines)"]
        LLMRunner["services/llm/\n(TerminalRunner & Tool Dispatcher)"]
    end

    subgraph PureAnalysis["Pure Analysis Engine (No I/O)"]
        RosterAnalysis["analysis/roster.py\n(value_all_rosters)"]
        PicksAnalysis["analysis/picks.py\n(pick_ledger & price_pick)"]
        TradeAnalysis["analysis/trade.py\n(analyze_trade & arbitrage)"]
        MoversAnalysis["analysis/movers.py\n(top_movers & find_arbitrage)"]
        LineupAnalysis["analysis/lineup.py\n(optimal_lineup - greedy laminar)"]
        CleanupAnalysis["analysis/cleanup.py\n(audit_roster & taxi eligibility)"]
        FitAnalysis["analysis/fit.py & draft.py\n(FitScore & team-relative draft)"]
        WaiversAnalysis["analysis/waivers.py\n(waiver_targets)"]
    end

    subgraph CLI["Rich Terminal Interface (cli.py)"]
        OutputSetup["ff setup / config"]
        OutputValuation["ff roster / power / picks / values"]
        OutputTrading["ff trade / movers / waivers"]
        OutputManagement["ff lineup / cleanup / news"]
        OutputDraft["ff draft / ask"]
    end

    DataSources --> CoreEngine
    CoreEngine --> PureAnalysis
    PureAnalysis --> CLI
```

## Quickstart

```bash
make install                 # venv + deps + pre-commit hook
./.venv/bin/ff setup <your-sleeper-username>
./.venv/bin/ff power
./.venv/bin/ff roster
./.venv/bin/ff values -p WR --market ktc
./.venv/bin/ff lineup                 # optimal start/sit for the current week
./.venv/bin/ff trade --give "Jahmyr Gibbs, 2026 2nd" --get "Bijan Robinson, 2027 1st" --market both
./.venv/bin/ff movers --arbitrage
./.venv/bin/ff news --player "Christian McCaffrey"
./.venv/bin/ff cleanup
./.venv/bin/ff waivers
./.venv/bin/ff ask "Should I trade Jahmyr Gibbs and a 2026 2nd for Bijan Robinson?"
```

`setup` reads your league's settings from Sleeper and **auto-detects the format**
(superflex/1QB, PPR, team count, TEP), so values are always calibrated for your league.
Picks are first-class assets: `2027 1st`, `2026 2nd`, `2026 Pick 1.05`, `2027 early 1st` all resolve automatically.

---

## Command Reference & Workflows

### 1. League Setup & Configuration

#### `ff setup <username>`
Discovers your leagues, resolves your team, auto-detects league scoring format (superflex, PPR, team count, tight-end premium), and saves `.ff/config.json`.

```mermaid
flowchart TD
    Start(["ff setup <username>"]) --> ResolveUser["Resolve Sleeper user_id\n(sc.user)"]
    ResolveUser --> CheckExplicit{"--league-id\ngiven?"}
    CheckExplicit -- "Yes" --> FetchLeague["Fetch League Settings\n(sc.league)"]
    CheckExplicit -- "No" --> FetchLeagues["Fetch User Leagues for Season\n(sc.user_leagues)"]
    FetchLeagues --> LeagueCount{"League count"}
    LeagueCount -- "1" --> FetchLeague
    LeagueCount -- "> 1" --> CheckIndex{"-n / --league-index\ngiven?"}
    CheckIndex -- "Yes" --> FetchLeague
    CheckIndex -- "No" --> PromptUser["Interactive prompt:\npick from list"]
    PromptUser --> FetchLeague
    FetchLeague --> Detect["sleeper.detect_format()\n• Superflex vs 1QB\n• PPR scoring (0.0 / 0.5 / 1.0)\n• Team count\n• Tight-End Premium (TEP)"]
    Detect --> Save["Save Config to .ff/config.json"]
    Save --> Done(["Render confirmation panel"])
```

**Options:**
- `--season Y`: Target season year (defaults to active/current season).
- `--league-id ID`: Skip interactive selection and bind directly to a specific Sleeper league.
- `-n, --league-index N`: Pick the Nth league non-interactively (0-indexed).

---

#### `ff config set-llm <backend>`
Configures the local LLM runner used by `ff ask`.

```mermaid
flowchart TD
    Start(["ff config set-llm <backend>"]) --> Validate{"Backend valid?\n(auto/agy/gemini/claude/ollama)"}
    Validate -- "No" --> Error(["Exit with error"])
    Validate -- "Yes" --> Update["Update Config.llm_backend\n& optional Config.ollama_model"]
    Update --> Save["Save .ff/config.json"]
    Save --> Done(["Render updated configuration panel"])
```

**Options:**
- `backend`: Runner backend (`auto`, `agy`, `gemini`, `claude`, `ollama`).
- `-m, --model M`: Model name when using Ollama (defaults to `llama3.2`).

---

### 2. Roster Valuation & League Standings

#### `ff roster [team]`
Prices out an entire roster using live market values. Computes total dynasty value, power rank, starters value, positional breakdown, and top individual assets with injury tags and 30-day value trends.

```mermaid
flowchart TD
    Start(["ff roster [team]"]) --> LoadConfig["Load .ff/config.json"]
    LoadConfig --> FetchData["Fetch Sleeper rosters & users\nFetch players metadata (injuries/depth)\nFetch FantasyCalc ValueBook"]
    FetchData --> Target["_pick_roster(team name or user_id)"]
    Target --> ValueRosters["analysis.value_all_rosters()\n• Price every player via exact sleeperId\n• Compute starters value & position sums\n• Calculate power rank in league"]
    ValueRosters --> Render["Render:\n• Summary Panel (Value, Rank, Starters)\n• Positional breakdown table\n• Top assets table (Injury/Depth/30d trend)"]
    Render --> Done(["Done"])
```

**Options:**
- `team`: Optional team name search (defaults to your own roster).
- `--top N`: Number of top assets to display in detail (default: 15).

---

#### `ff power`
Generates league-wide power rankings by total dynasty player value, paired with current W-L records and total points scored.

```mermaid
flowchart TD
    Start(["ff power"]) --> Load["Load Config & Fetch Data\n(Rosters, Metadata, ValueBook)"]
    Load --> ValueAll["analysis.value_all_rosters()\nSort rosters by total dynasty player value"]
    ValueAll --> MergeRecord["Join Sleeper W-L-T record & Points For"]
    MergeRecord --> Table["Render Power Rankings Table:\nRank | Team | Dynasty Value | Record | Points For"]
    Table --> Done(["Done"])
```

---

#### `ff picks [team]`
Reconciles whole-team draft capital ownership across all trades, applying power-ranked tier valuation (Early, Mid, Late) to 1st and 2nd round picks.

```mermaid
flowchart TD
    Start(["ff picks [team]"]) --> SetupRange["Determine future draft seasons\n& rookie round count"]
    SetupRange --> FetchTraded["Fetch sc.traded_picks(league_id)"]
    FetchTraded --> PowerRanks["Compute power rank of all teams\n(analysis.value_all_rosters)"]
    PowerRanks --> Ledger["analysis.pick_ledger()\n• Assign baseline pick endowment\n• Reconcile traded_picks chain (last trade holds)\n• Mark acquired picks with *"]
    Ledger --> Price["analysis.price_pick()\n• 1sts/2nds tiered: Early/Mid/Late\n  using ORIGINAL team's power rank\n• 3rds+: flat round value\n• Join FantasyCalc pick values"]
    Price --> ScopeCheck{"Target team specified?"}
    ScopeCheck -- "No" --> LeagueGrid["Render League Draft Capital Grid\n(Team vs Seasons Pick Matrix)"]
    ScopeCheck -- "Yes" --> TeamTable["Render Team Pick Breakdown Table\n(Pick | Origin | Tier | Value)"]
    LeagueGrid & TeamTable --> Done(["Done"])
```

**Options:**
- `team`: Team name (omit to view full league grid).
- `--years N`: Number of future draft classes to show (default: 2).
- `--rounds N`: Rookie rounds per draft (overrides league setting).

---

### 3. Market Analysis & Trade Engine

#### `ff values`
Dynasty rankings calibrated to your league's exact settings, supporting dual-market views (FantasyCalc + KeepTradeCut) and positional filters.

```mermaid
flowchart TD
    Start(["ff values [-p POS] [--market both|fc|ktc]"]) --> Fetch["Fetch FantasyCalc values\nOptional: Fetch KTC secondary market"]
    Fetch --> Merge["Merge KTC values onto Assets by sleeperId"]
    Merge --> Filter["Filter by position (QB/RB/WR/TE)\n& slice top N"]
    Filter --> Table["Render Dynasty Rankings Table:\nRank | Player | Pos | PosRk | Team | Age | FC | KTC | 30d"]
    Table --> Done(["Done"])
```

**Options:**
- `-p, --position`: Filter by `QB`, `RB`, `WR`, or `TE`.
- `-m, --market`: Market source: `fc` (FantasyCalc), `ktc` (KeepTradeCut), or `both` (default: `both`).
- `--limit N`: How many assets to show (default: 40).

---

#### `ff trade --give --get`
Multi-market trade analyzer supporting players and draft picks. Evaluates net values, fairness thresholds, positional balance swings, and market arbitrage opportunities.

```mermaid
flowchart TD
    Start(["ff trade --give 'A, B' --get 'C, D'"]) --> Parse["Tokenize comma-separated strings\n(Players and draft picks)"]
    Parse --> Resolve["ValueBook.resolve()\n• Exact sleeperId match\n• Fuzzy name match (with did-you-mean)\n• Pick normalization (e.g. '2027 1st', '2026 early 2nd')"]
    Resolve --> Analyze["analysis.analyze_trade()\n• Sum Side A (Get) & Side B (Give)\n• Compute net value delta & % difference\n• Check fairness (<= 5% difference = Fair)"]
    Analyze --> DualMarket{"--market both\n& KTC available?"}
    DualMarket -- "Yes" --> Arb["Compute KTC deltas & detect arbitrage:\n• Consensus Win / Loss\n• FC Arbitrage Win / Loss\n• KTC Arbitrage Win / Loss"]
    DualMarket -- "No" --> SingleVerdict["Compute single-market verdict"]
    Arb & SingleVerdict --> Swings["analysis.position_deltas()\nCalculate net value gain/loss per position"]
    Swings --> Output["Render:\n• Asset comparison table (FC & KTC)\n• Verdict banner + Arbitrage label\n• Positional swing summary"]
    Output --> Done(["Done"])
```

**Options:**
- `--give`: Comma-separated assets you send (e.g. `--give "Jahmyr Gibbs, 2026 2nd"`).
- `--get`: Comma-separated assets you receive (e.g. `--get "Bijan Robinson, 2027 1st"`).
- `-m, --market`: Valuation model: `both` (default), `fc`, or `ktc`.

---

#### `ff movers`
Identifies high-leverage trade targets: buy-low / sell-high candidates (dynasty vs win-now redraft value gaps) and cross-market arbitrage opportunities (FantasyCalc vs KeepTradeCut discrepancies).

```mermaid
flowchart TD
    Start(["ff movers [--buy] [--sell] [--arbitrage]"]) --> CheckMode{"Mode"}
    CheckMode -- "--arbitrage" --> ArbEngine["analysis.find_arbitrage_movers()\nCompare FC trade values vs KTC hype\nacross all rostered players in league"]
    ArbEngine --> ArbTable["Render Arbitrage Table:\nPlayer | Owner | FC | KTC | Diff | Gap% | Market Bias"]
    
    CheckMode -- "Redraft Gap" --> GapEngine["analysis.top_movers()\nCompare Dynasty Value vs Redraft Value\nApply --min-value floor"]
    GapEngine --> GapTable["Render Movers Table:\n• Buy-Low: Dynasty > Redraft (for Contenders)\n• Sell-High: Redraft > Dynasty (for Rebuilders)"]
    ArbTable & GapTable --> Done(["Done"])
```

**Options:**
- `--buy`: Show buy-low candidates (dynasty value > redraft value; or KTC > FC for arbitrage).
- `--sell`: Show sell-high candidates (redraft value > dynasty value; or FC > KTC for arbitrage).
- `-a, --arbitrage`: Scan for pricing inefficiencies between FantasyCalc and KeepTradeCut.
- `--min-value N`: Value floor filtering out deep stashes (default: 1000).
- `--limit N`: Max results to display (default: 20).

---

### 4. In-Season Management & Optimization

#### `ff lineup [team]`
Lineup optimizer scoring weekly stat projections against your league's exact rules (including TEP), using an optimal laminar greedy assignment algorithm, and providing actionable START/SIT deltas vs your current Sleeper starters.

```mermaid
flowchart TD
    Start(["ff lineup [team] [--week N]"]) --> Fetch["Fetch weekly raw stat lines (Sleeper Projections)\nFetch league scoring settings & roster slots"]
    Fetch --> Score["Score stats with league's exact rules\n(PPR, yardage bonuses, TEP for TEs)"]
    Score --> Assign["analysis.optimal_lineup()\nGreedy laminar assignment on active players:\nFill most-restrictive slots first\n(QB/RB/WR/TE -> FLEX -> SUPER_FLEX)"]
    Assign --> Compare["Compare optimal lineup vs target.starters on Sleeper"]
    Compare --> Render["Render:\n• Optimal lineup slots with projected points\n• Total projected points panel\n• START / SIT moves (+ projected gain)"]
    Render --> Done(["Done"])
```

**Options:**
- `team`: Team name search (defaults to your team).
- `--week N`: Target NFL week (defaults to active/upcoming week).
- `--season Y`: Target season year.

---

#### `ff cleanup [team]`
Roster auditor that computes active, taxi, and IR capacity, ranking drop candidates (lowest value first) and highlighting zero-loss taxi stashes to open waiver room.

```mermaid
flowchart TD
    Start(["ff cleanup [team]"]) --> ReadRules["Read league settings:\ntaxi_slots, reserve_slots, taxi_years, taxi_allow_vets"]
    ReadRules --> Audit["analysis.audit_roster()\nClassify players: START, BENCH, TAXI, IR"]
    Audit --> CalcCap["Compute Capacity:\n• Active open = Cap - (Start + Bench)\n• Taxi open = Cap - Taxi count\n• IR open = Cap - IR count"]
    CalcCap --> Drops["Rank Drop Candidates:\nWorst value non-starters first\nFlag if drop frees ACTIVE slot vs TAXI/IR only"]
    CalcCap --> Taxi["Rank Taxi Candidates:\nBest value taxi-eligible bench players\nFrees active room without dropping player"]
    Drops & Taxi --> Render["Render:\n• Capacity summary panel\n• 'Make room' actionable advice line\n• Drop candidates table & Taxi stash table"]
    Render --> Done(["Done"])
```

**Options:**
- `team`: Team name search (defaults to your team).
- `--drops N`: How many drop candidates to list (default: 8).

---

#### `ff news [team]`
Tracks player health, injury designations, depth-chart roles, and Sleeper 24-hour trending adds/drops across your league or for a specific team.

```mermaid
flowchart TD
    Start(["ff news [team] [--limit N]"]) --> LoadConfig["Load .ff/config.json"]
    LoadConfig --> FetchData["Fetch Sleeper rosters & players metadata\nFetch FantasyCalc ValueBook"]
    FetchData --> FilterTeam{"Team argument\nspecified?"}
    FilterTeam -- "Yes" --> PickTeam["Filter valuations to target team"]
    FilterTeam -- "No" --> AllTeams["Evaluate all league rosters"]
    PickTeam & AllTeams --> ScanInjuries["Scan assets for injury tags & reserve status\n(injury_status != 'Active')"]
    ScanInjuries --> FetchTrending["Fetch Sleeper 24h trending adds & drops\n(sc.trending)"]
    FetchTrending --> Render["Render:\n• Injured players table (sorted by dynasty value)\n• Sleeper 24h trending adds & drops table"]
    Render --> Done(["Done"])
```

**Options:**
- `team`: Filter injuries to a specific team (defaults to league-wide).
- `--limit N`: Number of trending adds and drops to display (default: 15).

---

#### `ff waivers`
Identifies trending free-agent adds across Sleeper, joins them with FantasyCalc dynasty values, and flags their availability in your league.

```mermaid
flowchart TD
    Start(["ff waivers [--limit N] [--all]"]) --> FetchTrend["Fetch trending adds across Sleeper\n(sc.trending)"]
    FetchTrend --> JoinValues["Join trending player IDs to FantasyCalc values"]
    JoinValues --> CheckRosters["Check league rosters:\nFlag as Free Agent or Rostered"]
    CheckRosters --> Filter["analysis.waiver_targets()\nFilter to free agents (unless --all)\nSort by dynasty value"]
    Filter --> Table["Render Waiver Targets Table:\nPlayer | Pos | Value | Add Count | Status"]
    Table --> Done(["Done"])
```

**Options:**
- `--limit N`: How many waiver targets to show (default: 20).
- `--all`: Include currently rostered players.

---

### 5. Live Draft Board & Natural Language AI

#### `ff draft`
Live draft board scored specifically for YOUR team: tracks draft order (snake, linear, 3RR), owned picks and on-the-clock status, positional standings vs league median, and ranks best available players by `FitScore` (market value adjusted for your roster need and competitive horizon).

```mermaid
flowchart TD
    Start(["ff draft [-p POS] [-r] [--mode contend|rebuild|auto]"]) --> FetchDraft["Fetch active/recent draft\n(sc.draft: slots, order, traded picks)"]
    FetchDraft --> PickStatus["Resolve owned picks via my_picks()\nShow on-clock status and pick gaps"]
    PickStatus --> Unavailable["Build taken pool:\nLeague rosters + drafted picks"]
    Unavailable --> TeamEval["Evaluate Team Context:\n• Value merged roster (current + drafted today)\n• Detect status: Contend / Rebuild / Balanced\n• Compute 'where you stand' vs league median"]
    TeamEval --> FitEngine["analysis.rank_fits()\n• Anchor on FantasyCalc dynasty value\n• Layer status-weighted positional upgrade tilt\n• Layer win-now vs rebuild horizon tilt\n• Calculate FitScore"]
    FitEngine --> Render["Render:\n• Live draft status banner\n• Your picks schedule\n• Where you stand table (thin hole flags)\n• Best Available FOR YOU (FitScore vs Market Rank)"]
    Render --> Done(["Done"])
```

**Options:**
- `-p, --position`: Filter available board to `QB`, `RB`, `WR`, or `TE`.
- `-r, --rookies`: Show available rookies only.
- `--mode`: Competitive horizon: `auto` (reads power rank), `contend`, or `rebuild`.
- `--draft-id ID`: Manually specify draft ID.
- `--limit N`: Number of available players to display (default: 30).

---

#### `ff ask "<query>"`
Natural language Q&A interface using your terminal's local AI runner (`agy`, `gemini`, `claude`, `ollama`) to execute deterministic Python analysis tools and synthesize plain-English explanations.

```mermaid
flowchart TD
    Start(["ff ask '<query>' [--backend B]"]) --> InitRunner["Initialize services.llm.TerminalRunner\n(Headless local CLI subprocess)"]
    InitRunner --> PromptLLM["Pass prompt + TOOL_SCHEMAS to LLM"]
    PromptLLM --> ParseTool{"LLM returned JSON tool call?"}
    ParseTool -- "No" --> PlainMarkdown["Render plain markdown response"]
    ParseTool -- "Yes" --> CheckTool{"Tool in ALLOWED_TOOLS?"}
    CheckTool -- "setup_league" --> Onboard["services.llm.onboard_user()"]
    CheckTool -- "analysis tool" --> Dispatch["services.llm.dispatch_tool(tool, kwargs, ctx)\nExecute deterministic Python analysis:\n• analyze_trade\n• optimal_lineup\n• waiver_targets\n• draft_fit\n• get_roster"]
    Dispatch --> SynthLLM["Feed exact calculation result back into LLM\nfor plain-English synthesis"]
    SynthLLM --> FinalOutput["Render formatted markdown explanation in terminal"]
    PlainMarkdown & Onboard & FinalOutput --> Done(["Done"])
```

**Options:**
- `query`: Natural language question (e.g. `"Should I trade Gibbs for Bijan?"`, `"Who should I start at FLEX?"`).
- `--backend`: Override LLM runner: `auto`, `agy`, `gemini`, `claude`, or `ollama`.

---

#### `ff version`
Prints the installed version of `ff`.

```mermaid
flowchart TD
    Start(["ff version"]) --> ReadVersion["Read __version__"]
    ReadVersion --> Render["Print version string\n(e.g. 'ff 0.1.0')"]
    Render --> Done(["Done"])
```

---

## Development

```bash
make test          # gate suite — offline, deterministic, < 2s
make test-live     # contract checks against the real APIs
FF_LIVE_LEAGUE_ID=<a completed league id> make test-live   # also runs traded-picks + draft-shape canaries
./.venv/bin/pytest tests/test_trade.py::test_trade_with_players_and_picks   # run single test
```

See [`CLAUDE.md`](CLAUDE.md) for architecture details and module contracts.

## Limits (by design)

- **`roster` and `power` value rostered players only**, not draft picks. Whole-team pick ownership is reconciled from `traded_picks` and tier-valued by `ff picks` — kept out of roster/power totals on purpose so player value and draft capital stay separately legible.
- **Lineup projections are single-source** (RotoWire, via Sleeper) and exclude K/DEF unless your league starts them. TEP *is* applied here because `lineup` scores raw projected stats with your league's settings — only FantasyCalc *dynasty values* (`values`/`roster`/`trade`) are not TEP-adjusted.
- **No trade *finder* and no tiers/VORP yet.** `trade` evaluates a deal you specify; it does not scan the league to propose one. Rankings are raw value without tier breaks or league-wide replacement level.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for developer environment setup, test lanes, and PR expectations.

## License

MIT — see [`LICENSE`](LICENSE).

