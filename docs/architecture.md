# Architecture diagrams

How `ff` is put together, from the outside in. These diagrams were derived from the source at the `v0.1.0` release baseline. Node labels use real module and function names, so you can grep them, and a rename should update this file. For the prose version and design decisions, see [`AGENTS.md`](../AGENTS.md) and [`.ai/specs/system-architecture.md`](../.ai/specs/system-architecture.md).

1. [System context](#1-system-context): what `ff` talks to and what it stores
2. [Module dependencies](#2-module-dependencies): the import graph between packages
3. [Command map](#3-command-map): which analysis each command runs and which providers it reads
4. [`ff trade`](#4-ff-trade): fresh prices, site adjustments, the offer rule
5. [Weekly decisions](#5-weekly-decisions): `lineup`, `compare`, `waivers --weekly`
6. [`ff ask`](#6-ff-ask): the local-runner path

## 1. System context

`ff` is a local CLI. Every provider call is an HTTP GET. No command writes to Sleeper: nothing submits claims, changes lineups or executes trades. CLI state is local files under `FF_HOME`. (`scripts/record_fixtures.py` writes to `samples/`, outside it.)

```mermaid
flowchart LR
  user(["You, in a terminal"]) --> ff["ff CLI<br/>ff.cli:app"]
  env[/"environment<br/>FF_HOME, FF_QA"/] --> ff

  subgraph home["FF_HOME (default ./.ff)"]
    cfg[("config.json<br/>league, season, Format, user,<br/>LLM backend, window_mode")]
    cache[("cache/<br/>responses keyed by URL hash, per-endpoint TTL")]
    ktcpool[("ktc_pool.json (optional)<br/>local KTC fallback pool")]
  end

  subgraph free["Free, public, no auth"]
    sapp["api.sleeper.app/v1<br/>state, users, leagues, rosters, matchups,<br/>transactions, drafts, draft picks, traded picks,<br/>players file, trending"]
    scom["api.sleeper.com<br/>projections, schedule,<br/>per-player status and news"]
    fcapi["api.fantasycalc.com<br/>dynasty and redraft values"]
    dp["raw.githubusercontent.com/dynastyprocess/data<br/>values.csv + db_playerids.csv (default secondary)"]
    ktc["keeptradecut.com<br/>trade-calculator HTML (opt-in values),<br/>site.min.js when its version changes (trade drift check)"]
    fcsite["fantasycalc.com<br/>trade-calculator page,<br/>JS bundles when their names change (trade drift check)"]
    espn["site.api.espn.com<br/>NFL scoreboard + player/NFL news"]
    rss["NFL RSS feeds<br/>ESPN RSS + ProFootballTalk RSS"]
  end

  subgraph opt["Optional, for ff ask only"]
    local["LLM CLI via subprocess<br/>agy / gemini / claude call hosted models;<br/>ollama runs locally"]
  end

  ff -->|"read / write: setup, config set-llm,<br/>config set-window, ask setup_league"| cfg
  ff -->|read / write| cache
  ff -.->|fallback read| ktcpool
  ff --> sapp
  ff --> scom
  ff --> fcapi
  ff --> dp
  ff -->|"HTML via get_text,<br/>curl fallback on TLS errors"| ktc
  ff -->|"HTML via get_text,<br/>curl fallback on TLS errors"| fcsite
  ff -->|"weekly + news: kickoff times,<br/>game status, player news"| espn
  ff -->|"news: 14-day review"| rss
  ff -->|"ask: question + tool schemas,<br/>then tool result JSON"| local
```

## 2. Module dependencies

Package-level `import` edges under `src/ff/` and `scripts/`, read from the AST: every edge drawn has a backing import, and every import is drawn. The intended layering is boundary → services → data clients → pure analysis, with `qa` as a checker beside analysis and everything resting on contracts and core. Dashed edges are couplings that cut across that layering:

- `analysis` reaches back into `sleeper` (`player_name`) and `values` (`ValueBook`) for convenience
- `services.weekly` is a data loader, yet it reuses two rules from `analysis.cleanup`: `designation` and `ir_eligible_statuses`
- `news` fetches RSS/JSON feeds and calls `analysis.news.build_news_review`
- `qa` re-runs `analysis.trade.apply_site_adjustments`, reuses lineup, window, and waiver rules (`SLOT_ELIGIBILITY`, `game_locked`, `unavailable`, `waiver_positions`), and reads the `services.llm.tools` allowlist
- `ff/offers.py` imports `cli` helpers (`_pick_window`, `_season_sim`, `_finish_ranks`, `render_news_review`, and `cli.console`)

`values/dealer.py` is a backward-compatibility shim that no command imports.

<!-- edges:begin -->
```mermaid
flowchart TD
  subgraph boundary["Boundary"]
    cli["cli.py<br/>Typer commands, Rich tables"]
    offers["offers.py<br/>ff offers search & CLI"]
    scripts["scripts/record_fixtures.py<br/>(calculator_oracle.mjs is Node)"]
  end
  subgraph services["Services"]
    weekly["services/weekly.py<br/>load_weekly"]
    llm["services/llm/<br/>runner, dispatcher, tools, onboarding"]
  end
  subgraph clients["Data clients"]
    sleeper["sleeper/client.py<br/>SleeperClient, detect_format,<br/>build_rosters"]
    values["values/<br/>ValuesClient, ValueBook, DynastyProcessClient,<br/>KtcClient, SecondarySnapshot, normalize"]
    calclive["values/calculators_live.py<br/>check_calculators"]
    projections["projections/client.py<br/>ProjectionsClient"]
    news["news/<br/>NewsClient, review_players"]
  end
  subgraph pure["Pure analysis, no I/O"]
    analysis["analysis/<br/>roster, trade, picks, draft, fit, lineup,<br/>waivers, weekly_waivers, cleanup, depth,<br/>movers, compare, window, standings, plan, fab, news"]
    calcs["analysis/calculators.py<br/>FC and KTC calculator ports"]
  end
  qa["qa/<br/>engine, validators, models"]

  cli --> weekly & llm & sleeper & values & calclive & projections & news & offers & analysis & qa
  offers -.-> cli
  offers --> sleeper & values & calclive & news & analysis & qa
  scripts --> sleeper

  weekly -.->|designation, ir_eligible_statuses| analysis
  weekly --> sleeper

  llm --> analysis & sleeper & values & news
  news -.->|build_news_review| analysis
  calclive --> calcs

  analysis --> calcs
  analysis -.->|player_name| sleeper
  analysis -.->|ValueBook| values

  qa -.->|apply_site_adjustments, lineup, window and waiver rules| analysis
  qa -.->|ALLOWED_TOOLS| llm
```

Nearly every package also imports `contracts` and `core`. They are drawn separately so the graph above stays readable:

```mermaid
flowchart LR
  contracts["contracts/models.py<br/>pydantic schema"]
  core["core/<br/>http.get_json, get_text, config"]
  cli["cli.py"]
  offers["offers.py"]
  weekly["services/weekly.py"]
  llm["services/llm/"]
  sleeper["sleeper/"]
  values["values/"]
  calclive["values/calculators_live.py"]
  projections["projections/"]
  news["news/"]
  analysis["analysis/"]
  qa["qa/"]
  cli & offers & weekly & llm & sleeper & values & news & analysis & qa & core --> contracts
  cli & offers & weekly & llm & calclive & sleeper & values & projections & news & qa --> core
```
<!-- edges:end -->

## 3. Command map

Which analysis each command calls directly. Dotted edges inside the analysis box are imports between analysis modules, so `waivers` also runs `depth`, `fit` also runs `lineup` and `movers`, and `plan`/`window` share `lineup`/`movers`. `ask` reaches all of it through the dispatcher (section 6), using cached values without `trade`'s drift check or offer rule.

```mermaid
flowchart TD
  subgraph cmds["ff commands"]
    setup["setup"]
    cfgcmd["config set-llm / set-window<br/>version"]
    rpn["roster / power / window"]
    standings_c["standings"]
    plan_c["plan"]
    fab_c["fab"]
    picks_c["picks"]
    values_c["values"]
    trade_c["trade"]
    offers_c["offers"]
    movers_c["movers"]
    waivers_c["waivers"]
    news_c["news"]
    cleanup_c["cleanup"]
    draft_c["draft"]
    lineup_c["lineup"]
    compare_c["compare"]
    waiversw["waivers --weekly"]
    ask["ask"]
    qa_c["qa / doctor (hidden alias)"]
  end

  cfgnote(["config.json only"])
  detect["sleeper.detect_format"]
  top["ValueBook.top"]
  weekly["services.weekly<br/>load_weekly"]
  news_rev["news.review_players"]
  dispatch["services.llm.dispatcher<br/>dispatch_tool"]

  subgraph an["analysis/"]
    a_roster["roster"]
    a_window["window"]
    a_standings["standings"]
    a_plan["plan"]
    a_fab["fab"]
    a_picks["picks"]
    a_trade["trade"]
    a_calcs["calculators"]
    a_movers["movers"]
    a_waivers["waivers"]
    a_ww["weekly_waivers"]
    a_depth["depth"]
    a_cleanup["cleanup"]
    a_lineup["lineup"]
    a_compare["compare"]
    a_draft["draft"]
    a_fit["fit"]
    a_news["news"]
  end

  cfgcmd -.-> cfgnote
  setup --> detect
  values_c --> top
  rpn --> a_roster & a_window & a_picks & a_standings
  standings_c --> a_standings
  plan_c --> a_plan & a_roster & a_standings & a_picks & a_cleanup & weekly & a_lineup & news_rev
  fab_c --> a_fab
  picks_c --> a_roster & a_picks & a_standings
  trade_c --> a_trade & a_window & news_rev
  offers_c --> a_trade & a_picks & a_fit & news_rev
  movers_c --> a_movers
  waivers_c --> a_waivers & news_rev
  news_c --> a_roster & news_rev
  cleanup_c --> a_cleanup & news_rev
  draft_c --> a_draft & a_fit & a_roster & a_window
  lineup_c --> weekly & a_lineup & news_rev
  compare_c --> weekly & a_compare & news_rev
  waiversw --> weekly & a_ww & news_rev
  ask --> dispatch
  qa_c --> a_roster & a_picks & a_cleanup & a_waivers & a_movers & a_window & top

  weekly -.-> a_cleanup
  news_rev -.-> a_news
  a_trade -.-> a_calcs
  a_waivers -.-> a_depth & a_lineup
  a_ww -.-> a_waivers & a_lineup
  a_cleanup -.-> a_depth
  a_compare -.-> a_lineup
  a_fit -.-> a_lineup & a_movers
  a_plan -.-> a_fit & a_movers
  a_window -.-> a_lineup & a_movers
```

What each command reads. `●` always; `◐` only in the noted case; blank means never. Every command except `setup` and `version` loads `config.json` first; `ask` loads it only if it exists. The last column is the `qa.engine.VALIDATOR_MAP` key that checks the result.

| Command | api.sleeper.app | api.sleeper.com | FantasyCalc | Secondary (DP / KTC) | ESPN & RSS | QA check |
|---|---|---|---|---|---|---|
| `setup` | ● state, user, leagues, league | | | | | `setup` |
| `config`, `version` | | | | | | none |
| `roster` | ● rosters, users, players | | ● | | | `roster` |
| `power`, `window` | ● rosters, users, players, league, drafts, traded picks, state | | ● | | | `power` / `window` |
| `standings` | ● league, rosters, users, matchups | | | | | none |
| `plan` | ● state, league, rosters, users, players, matchups, traded picks, drafts | ● projections, schedule, status, news | ● | | ● ESPN scoreboard + news, RSS | `news_review` (+ weekly) |
| `fab` | ● state, league, rosters, users, players, transactions | | | | | none |
| `picks` | ● rosters, users, league, drafts, traded picks, matchups, players | | ● | | | `picks` |
| `values` | | | ● | ◐ DP default (`both`), KTC opt-in | | `values` |
| `trade` | ● players, league, rosters, users, state, drafts, traded picks | ◐ player news | ● fresh | ◐ DP or KTC fresh (unless `fc` / `--fc-only`) | ◐ news review | `trade`, `news_review` |
| `offers` | ● league, rosters, users, players, drafts, traded picks, matchups, trending | ◐ player news | ● fresh | ◐ DP or KTC fresh (unless `--fc-only`) | ◐ news review | `news_review` |
| `movers` | ◐ rosters, users with `--arbitrage` | | ● | ◐ with `--arbitrage` | | `movers` |
| `waivers` | ● league, rosters, users, players, trending | ◐ player news | ● | | ◐ news review | `waivers`, `news_review` |
| `waivers --weekly` | ● fresh state, league, rosters; users, players, matchups | ● projections snapshot, schedule, status, news | | | ● scoreboard, news, RSS | `weekly_waivers`, `news_review` |
| `news` | ● rosters, users, players, trending; ◐ `--player` skips league reads | ◐ `--player` news | ● (unless `--player`) | | ◐ `--player` ESPN + RSS | `news` / `news_review` |
| `cleanup` | ● league, rosters, users, players | ◐ player news | ● | | ◐ news review | `cleanup`, `news_review` |
| `lineup` | ● fresh state, league, rosters; users, players; ◐ matchups | ● projections; ◐ schedule, status, news | | | ◐ scoreboard, news, RSS | `lineup`, `news_review` |
| `compare` | ● fresh state, league, rosters; users, players, matchups | ● projections, schedule, status, news | | | ● scoreboard, news, RSS | `compare`, `news_review` |
| `draft` | ● draft, draft picks, draft traded picks, rosters, users, players, league, state | | ● | | | `draft` |
| `ask` (local runner) | ◐ per tool | ◐ weekly / news tools | ◐ value tools | ◐ DP default | ◐ weekly / news tools | `ask` |
| `qa`, `doctor` | ● rosters, users, players, league, drafts, traded picks, matchups, trending, state | | ● | ● DP | | up to 9 domains |

`trade` and `offers` run the calculator drift check (`check_calculators`): FantasyCalc's trade-calculator page and JS bundles are always checked when judging offers, while KeepTradeCut's `site.min.js` is checked only when KTC is the active secondary market. The local `ask` runner's own network traffic belongs to the external binary and is invisible to `ff`.

## 4. `ff trade`

`ff trade` bypasses the value cache (`fresh=True`): FantasyCalc always, and the active secondary market (DynastyProcess by default, or KeepTradeCut with `--market ktc` / `--ktc-file`) unless `--market fc` or `--fc-only`. It applies each site's own package adjustment before judging an offer, evaluates Strategy Filters against your competitive window and season phase, and runs a 14-day Latest News Review for all players in the trade.

```mermaid
sequenceDiagram
  autonumber
  actor U as You
  participant CLI as cli.trade
  participant VC as values.ValuesClient
  participant SC as sleeper.SleeperClient
  participant TR as analysis.trade
  participant CA as analysis.calculators
  participant CL as values.calculators_live
  participant NW as news.review_players
  participant QA as qa.run_qa

  U->>CLI: ff trade --give ... --get ...
  CLI->>VC: fetch(format, include_secondary, fresh=True, secondary=dp|ktc|none)
  VC-->>CLI: ValueBook (FC values + SecondarySnapshot)
  CLI->>SC: players()
  CLI->>TR: analyze_trade(get, give, book)
  TR->>TR: apply_site_adjustments(evaluation)
  TR->>CA: fc_adjustment (dynasty only)
  TR->>CA: ktc_adjustment (when KTC active & all assets priced)
  TR-->>CLI: TradeEvaluation + unresolved
  CLI->>CLI: render sides, totals, verdict panel
  CLI->>CL: check_calculators(book.secondary_html, check_ktc=...)
  CL-->>CLI: drift problems, if site code changed
  CLI->>TR: offer_verdict(evaluation, problems, fc_only=...)
  TR-->>CLI: OfferVerdict PASS / FAIL / CANNOT_JUDGE
  CLI->>CLI: Strategy Filters (window, duration, RB, seasonal)
  CLI->>NW: review_players(trade_pids, players_meta, "trade")
  NW-->>CLI: NewsReview (Sleeper + ESPN + RSS)
  CLI->>QA: run_qa("news_review") & run_qa("trade")
  QA-->>U: footer per FF_QA
```

## 5. Weekly decisions

Current-week advice is built from fresh reads (league users stay on their 30-minute cache), cross-checked and fail-closed. `ff compare`, `ff waivers --weekly`, `ff plan`, and every weekly `ask` route go through `cli._prepare_weekly`. The `ff lineup` command does its own fresh reads and calls `load_weekly` only for the current season and week. Any other week is a projection-only scenario with no injury or game-lock handling. All current-week decision commands conclude with `review_players` + `run_qa("news_review")`.

```mermaid
flowchart TD
  lineup["ff lineup"]
  compare["ff compare"]
  ww["ff waivers --weekly"]
  askw["ff ask weekly tools"]

  prep["cli._prepare_weekly<br/>fresh state + league,<br/>_current_week = max(1, week, display_week)"]
  gate{"season current and<br/>regular season?"}
  ros["fresh rosters + cached league users<br/>build_rosters, find target team"]
  proj["ProjectionsClient (api.sleeper.com)<br/>snapshot() for waivers, week() otherwise"]
  lw["services.weekly<br/>load_weekly"]
  sched["Sleeper schedule<br/>api.sleeper.com"]
  espnn["ESPN scoreboard<br/>kickoff times, game status"]
  status["fresh SleeperClient.player<br/>for each rostered player;<br/>player_news if questionable/doubtful"]
  match["league matchups<br/>roster and matchup starters must agree"]
  ctx["WeeklyContext<br/>game timing, availability, IR eligibility"]
  fail(["refuse with a one-line error"])

  lineup_own["lineup's own fresh reads<br/>state, league, rosters, ProjectionsClient.week"]
  cur{"current season<br/>and week?"}
  reg{"regular season?"}
  projonly(["projection-only scenario"])

  lu_out["cli.lineup renders Panel + Table,<br/>render_weekly_notes, review_players, run_qa"]
  a_lu["analysis.lineup<br/>optimal_lineup"]
  a_cmp["analysis.compare<br/>compare_players"]
  a_ww["analysis.weekly_waivers<br/>weekly_waivers"]
  jo["cli rendering helpers<br/>render_comparison / render_weekly_waivers<br/>(+ review_players & run_qa)"]

  compare & ww & askw --> prep --> gate
  gate -- no --> fail
  gate -- yes --> ros --> proj --> lw
  lw --> sched & espnn & status & match --> ctx
  lw -- "sources disagree or missing" --> fail

  lineup --> lineup_own --> cur
  cur -- yes --> reg
  reg -- no --> fail
  reg -- yes --> lw
  cur -- no --> projonly --> a_lu

  ctx --> a_lu & a_cmp & a_ww
  a_lu --> lu_out
  a_cmp & a_ww --> jo
```

## 6. `ff ask`

A local model picks one or up to `MAX_ASK_TOOLS = 3` allowlisted tools and their kwargs, then explains the deterministic calculation results in prose. The model never computes. Calculations run in `analysis/` through `dispatch_tool`, which accepts only names in `services.llm.tools.ALLOWED_TOOLS` (17 tools), against lazily loaded data (`cli._analysis_ctx`, with DynastyProcess as the default secondary market).

```mermaid
flowchart TD
  q(["ff ask 'question'<br/>loads config.json if it exists"])
  pick{"backend<br/>--backend, else config.llm_backend, else auto"}

  subgraph localpath["Local runner: auto / agy / gemini / claude / ollama"]
    run1["runner.TerminalRunner.run<br/>print/headless subprocess, 120s timeout"]
    reply{"reply"}
    prose1["print the markdown"]
    onboard["setup_league<br/>onboarding.onboard_user<br/>saves config only if league is unambiguous"]
    unknown["unknown tool:<br/>list ALLOWED_TOOLS"]
    nocfg(["no config yet:<br/>ask for a Sleeper username"])
    ctxl["cli._analysis_ctx<br/>DP default secondary"]
    run2["runner.TerminalRunner.run<br/>second call synthesizes prose over results"]
    qal["run_qa('ask')"]
  end

  rerr(["no runner found or runner failed, exit 1"])
  dispatch["dispatcher.dispatch_tool<br/>ALLOWED_TOOLS only (up to 3 tools)"]
  analysis["analysis/ & news/ functions"]

  q --> pick --> run1
  run1 -- error --> rerr
  run1 --> reply
  reply -- markdown --> prose1 --> qal
  reply -- unknown tool --> unknown --> qal
  reply -- setup_league --> onboard --> qal
  reply -- "JSON tool call, no config" --> nocfg
  reply -- "JSON {tool} or {tools: [...]}" --> ctxl --> dispatch
  dispatch -.-> run2 --> qal
  dispatch -. "all tools errored" .-> qal
  dispatch --> analysis
```
