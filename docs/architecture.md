# Architecture diagrams

How `ff` is put together, from the outside in. These diagrams were derived from the source at commit `ba6e5b8`. Node labels use real module and function names, so you can grep them, and a rename should update this file. For the prose version and design decisions, see [`AGENTS.md`](../AGENTS.md) and [`.ai/specs/system-architecture.md`](../.ai/specs/system-architecture.md).

1. [System context](#1-system-context): what `ff` talks to and what it stores
2. [Module dependencies](#2-module-dependencies): the import graph between packages
3. [Command map](#3-command-map): which analysis each command runs and which providers it reads
4. [`ff trade`](#4-ff-trade): fresh prices, site adjustments, the offer rule
5. [Weekly decisions](#5-weekly-decisions): `lineup`, `compare`, `waivers --weekly`
6. [`ff ask`](#6-ff-ask): the local-runner and Jev paths

## 1. System context

`ff` is a local CLI. Every provider call is an HTTP GET; the only exception is the optional Jev POST. No command writes to Sleeper: nothing submits claims, changes lineups or executes trades. CLI state is local files under `FF_HOME`. (`scripts/record_fixtures.py` writes to `samples/`, outside it.)

```mermaid
flowchart LR
  user(["You, in a terminal"]) --> ff["ff CLI<br/>ff.cli:app"]
  env[/"environment<br/>FF_HOME, FF_QA,<br/>TYPESAFE_API_KEY, TYPESAFE_MODEL"/] --> ff

  subgraph home["FF_HOME (default ./.ff)"]
    cfg[("config.json<br/>league, season, Format, user, LLM backend")]
    cache[("cache/<br/>responses keyed by URL hash, per-endpoint TTL")]
    key[("typesafe_api_key<br/>mode 0600, optional;<br/>TYPESAFE_API_KEY wins")]
  end

  subgraph free["Free, public, no auth"]
    sapp["api.sleeper.app/v1<br/>state, users, leagues, rosters, matchups,<br/>drafts, draft picks, traded picks,<br/>players file, trending"]
    scom["api.sleeper.com<br/>projections, schedule,<br/>per-player status and news"]
    fcapi["api.fantasycalc.com<br/>dynasty and redraft values"]
    ktc["keeptradecut.com<br/>trade-calculator HTML (values),<br/>site.min.js when its version changes (trade drift check)"]
    fcsite["fantasycalc.com<br/>trade-calculator page,<br/>JS bundles when their names change (trade drift check)"]
    espn["site.api.espn.com<br/>NFL scoreboard"]
  end

  subgraph opt["Optional, for ff ask only"]
    tsafe["api.typesafe.ai<br/>Jev classifier, paid, Bearer key"]
    local["LLM CLI via subprocess<br/>agy / gemini / claude call hosted models;<br/>ollama runs locally"]
  end

  ff -->|"read / write: setup, config set-llm,<br/>ask setup_league"| cfg
  ff -->|read / write| cache
  ff -->|"read; written by config set-jev-key"| key
  ff --> sapp
  ff --> scom
  ff --> fcapi
  ff -->|"HTML via get_text,<br/>curl fallback on TLS errors"| ktc
  ff -->|"HTML via get_text,<br/>curl fallback on TLS errors"| fcsite
  ff -->|"weekly: kickoff times, game status,<br/>schedule cross-check"| espn
  ff -->|"ask, backend jev (flag or config):<br/>question text only"| tsafe
  ff -->|"ask, other backends: question + tool schemas,<br/>then the tool result JSON"| local
```

## 2. Module dependencies

Package-level `import` edges under `src/ff/` and `scripts/`, read from the AST: every edge drawn has a backing import, and every import is drawn. The intended layering is boundary → services → data clients → pure analysis, with `qa` as a checker beside analysis and everything resting on contracts and core. Dashed edges are couplings that cut across that layering:

- analysis reaches back into `sleeper` (`player_name`) and `values` (`ValueBook`) for convenience
- `services.weekly` is a data loader, yet it reuses two rules from `analysis.cleanup`: `designation` and `ir_eligible_statuses`
- `qa` re-runs `analysis.trade.apply_site_adjustments`, reuses lineup and waiver rules (`SLOT_ELIGIBILITY`, `game_locked`, `unavailable`, `waiver_positions`), and reads the `services.llm.tools` allowlist
- `services.llm.jev_output` renders tables and runs QA, including for `compare` and `waivers --weekly`
- `scripts/find_offers.py` imports `ff.cli._pick_window`

`values/dealer.py` is a backward-compatibility shim that no command imports.

<!-- edges:begin -->
```mermaid
flowchart TD
  subgraph boundary["Boundary"]
    cli["cli.py<br/>Typer commands, Rich tables"]
    scripts["scripts/<br/>find_offers, record_fixtures, eval_jev<br/>(calculator_oracle.mjs is Node, no ff imports)"]
  end
  subgraph services["Services"]
    weekly["services/weekly.py<br/>load_weekly"]
    llm["services/llm/<br/>runner, jev, dispatcher, tools,<br/>onboarding, jev_output"]
  end
  subgraph clients["Data clients"]
    sleeper["sleeper/client.py<br/>SleeperClient, detect_format,<br/>build_rosters"]
    values["values/<br/>ValuesClient, ValueBook,<br/>KtcClient, normalize"]
    calclive["values/calculators_live.py<br/>check_calculators"]
    projections["projections/client.py<br/>ProjectionsClient"]
  end
  subgraph pure["Pure analysis, no I/O"]
    analysis["analysis/<br/>roster, trade, picks, draft, fit,<br/>lineup, waivers, weekly_waivers,<br/>cleanup, depth, movers, compare"]
    calcs["analysis/calculators.py<br/>FC and KTC calculator ports"]
  end
  qa["qa/<br/>engine, validators, models"]

  cli --> weekly
  cli --> llm
  cli --> sleeper
  cli --> values
  cli --> calclive
  cli --> projections
  cli --> analysis
  cli --> qa

  scripts -.->|_pick_window| cli
  scripts --> llm
  scripts --> sleeper
  scripts --> values
  scripts --> calclive
  scripts --> analysis

  weekly -.->|designation, ir_eligible_statuses| analysis
  weekly --> sleeper

  llm --> analysis
  llm --> sleeper
  llm -.->|run_qa| qa

  calclive --> calcs

  analysis --> calcs
  analysis -.->|player_name| sleeper
  analysis -.->|ValueBook| values

  qa -.->|apply_site_adjustments, lineup and waiver rules| analysis
  qa -.->|ALLOWED_TOOLS| llm
```

Nearly every package also imports the two shared ones. They are drawn separately so the graph above stays readable:

```mermaid
flowchart LR
  contracts["contracts/models.py<br/>pydantic schema"]
  core["core/<br/>http.get_json, get_text, config"]
  cli["cli.py"]
  scripts["scripts/"]
  weekly["services/weekly.py"]
  llm["services/llm/"]
  sleeper["sleeper/"]
  values["values/"]
  calclive["values/calculators_live.py"]
  projections["projections/"]
  analysis["analysis/"]
  qa["qa/"]
  cli & scripts & weekly & llm & sleeper & values & analysis & qa & core --> contracts
  cli & scripts & weekly & llm & calclive & sleeper & values & projections & qa --> core
```
<!-- edges:end -->

## 3. Command map

Which analysis each command calls directly. Dotted edges inside the analysis box are imports between analysis modules, so `waivers` also runs `depth` and `fit` also runs `lineup`. `ask` reaches all of it through the dispatcher (section 6), but with cached values and without `trade`'s drift check or offer rule.

```mermaid
flowchart TD
  subgraph cmds["ff commands"]
    setup["setup"]
    cfgcmd["config set-llm<br/>config set-jev-key<br/>version"]
    rpn["roster<br/>power<br/>news"]
    picks_c["picks"]
    values_c["values"]
    trade_c["trade"]
    movers_c["movers"]
    waivers_c["waivers"]
    cleanup_c["cleanup"]
    draft_c["draft"]
    lineup_c["lineup"]
    compare_c["compare"]
    waiversw["waivers --weekly"]
    ask["ask"]
    qa_c["qa<br/>doctor (hidden alias)"]
  end

  cfgnote(["config.json /<br/>typesafe_api_key only"])
  detect["sleeper.detect_format"]
  top["ValueBook.top"]
  weekly["services.weekly<br/>load_weekly"]
  dispatch["services.llm.dispatcher<br/>dispatch_tool"]

  subgraph an["analysis/"]
    a_roster["roster"]
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
  end

  cfgcmd -.-> cfgnote
  setup --> detect
  values_c --> top
  rpn --> a_roster
  picks_c --> a_roster
  picks_c --> a_picks
  trade_c --> a_trade
  movers_c --> a_movers
  waivers_c --> a_waivers
  cleanup_c --> a_cleanup
  draft_c --> a_draft
  draft_c --> a_fit
  draft_c --> a_roster
  lineup_c --> weekly
  lineup_c --> a_lineup
  compare_c --> weekly
  compare_c --> a_compare
  waiversw --> weekly
  waiversw --> a_ww
  ask --> dispatch
  qa_c --> a_roster
  qa_c --> a_picks
  qa_c --> a_cleanup
  qa_c --> a_waivers
  qa_c --> a_movers
  qa_c --> top

  weekly -.-> a_cleanup
  a_trade -.-> a_calcs
  a_waivers -.-> a_depth
  a_waivers -.-> a_lineup
  a_ww -.-> a_waivers
  a_ww -.-> a_lineup
  a_cleanup -.-> a_depth
  a_compare -.-> a_lineup
  a_fit -.-> a_lineup
  a_fit -.-> a_movers
```

What each command reads. `●` always; `◐` only in the noted case; blank means never. Every command except `setup`, `config set-jev-key` and `version` loads `config.json` first; `ask` loads it only if it exists. The last column is the `qa.engine.VALIDATOR_MAP` key that checks the result.

| Command | api.sleeper.app | api.sleeper.com | FantasyCalc | KTC | ESPN | TypeSafe | QA check |
|---|---|---|---|---|---|---|---|
| `setup` | ● state, user, leagues, league | | | | | | `setup` |
| `config set-llm`, `config set-jev-key`, `version` | | | | | | | none |
| `roster`, `power` | ● rosters, users, players | | ● | | | | `roster` / `power` |
| `picks` | ● rosters, users, league, drafts, traded picks, players | | ● | | | | `picks` |
| `values` | | | ● | ◐ unless `--market fc` (default `both`) | | | `values` |
| `trade` | ● players | | ● fresh | ◐ fresh, unless `--market fc` | | | `trade` |
| `movers` | ◐ rosters, users with `--arbitrage` | | ● | ◐ `--arbitrage` | | | `movers` |
| `waivers` | ● league, rosters, users, players, trending | | ● | | | | `waivers` |
| `waivers --weekly` | ● fresh state, league, rosters; users, players, matchups; ◐ trending with `--trending` | ● projections snapshot, schedule, rostered players' status; ◐ news for questionable/doubtful | | | ● | | `weekly_waivers` |
| `news` | ● rosters, users, players, trending adds and drops | | ● | | | | `news` |
| `cleanup` | ● league, rosters, users, players | | ● | | | | `cleanup` |
| `lineup` | ● fresh state, league, rosters; users, players; ◐ matchups, current week only | ● projections; ◐ schedule, rostered players' status and news, current week only | | | ◐ current week only | | `lineup` |
| `compare` | ● fresh state, league, rosters; users, players, matchups | ● projections, schedule, rostered players' status; ◐ news for questionable/doubtful | | | ● | | `compare` |
| `draft` | ● draft, draft picks, draft traded picks, rosters, users, players, league; ◐ drafts list unless `--draft-id` | | ● | | | | `draft` |
| `ask` (local runner) | ◐ per tool | ◐ weekly tools | ◐ value tools | ◐ value tools | ◐ weekly tools | | `ask` |
| `ask --backend jev` | ◐ per tool | ◐ weekly tools | ◐ value tools | | ◐ weekly tools | ● | per-tool domain check |
| `qa`, `doctor` | ● rosters, users, players, league, drafts, traded picks, trending | | ● | ● | | | up to 8 (`roster`, `cleanup` need your roster) |

`trade` with `--market both` also runs the calculator drift check: it fetches the `fantasycalc.com` trade-calculator page every run (plus its JS bundles when their names change), reuses the KTC page it already has, and downloads `keeptradecut.com/js/site.min.js` only when that version changes. The local `ask` runner's own network traffic belongs to the external binary and is invisible to `ff`.

## 4. `ff trade`

The one command that bypasses the cache for values (`fresh=True`): FantasyCalc always, KTC unless `--market fc`. It applies each site's own package adjustment before judging an offer. If the KTC fetch fails, the book simply has no KTC values; the error is swallowed, not raised.

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
  participant QA as qa.run_qa

  U->>CLI: ff trade --give ... --get ...
  CLI->>VC: fetch(format, include_secondary, fresh=True)
  VC-->>CLI: ValueBook (FC values, KTC values + page HTML if fetched)
  CLI->>CLI: ValueBook.resolve each token
  CLI->>SC: players()
  CLI->>TR: analyze_trade(get, give, book), side_a = what you receive
  TR->>TR: apply_site_adjustments(evaluation)
  TR->>CA: fc_adjustment (dynasty only)
  TR->>CA: ktc_adjustment (only if every asset has a KTC value)
  TR-->>CLI: TradeEvaluation (raw and site-adjusted totals) + unresolved
  CLI->>CLI: render sides, totals, verdict panel
  alt --market both (default)
    CLI->>CL: check_calculators(book.secondary_html)
    CL-->>CLI: drift problems, if site code changed
    CLI->>TR: offer_verdict(evaluation, problems)
    TR-->>CLI: OfferVerdict PASS / FAIL / CANNOT_JUDGE
  else --market fc / ktc / dealer
    CLI-->>U: "offer rule: needs both markets"
  end
  CLI->>CLI: provenance, positional swing, unmatched tokens
  CLI->>QA: run_qa("trade", evaluation)
  Note over QA: validate_trade re-runs apply_site_adjustments on a copy
  QA-->>U: footer per FF_QA (off prints only failures, strict raises)
```

## 5. Weekly decisions

Current-week advice is built from fresh reads (league users stay on their 30-minute cache), cross-checked and fail-closed. `ff compare`, `ff waivers --weekly` and every weekly `ask` route (lineup included) go through `cli._prepare_weekly`. The `ff lineup` command does its own fresh reads and calls `load_weekly` only for the current season and week. Any other week is a projection-only scenario with no injury or game-lock handling.

```mermaid
flowchart TD
  lineup["ff lineup"]
  compare["ff compare"]
  ww["ff waivers --weekly"]
  askw["ff ask weekly tools"]

  prep["cli._prepare_weekly<br/>fresh state + league,<br/>_current_week = max(1, week, display_week)"]
  gate{"season current and<br/>regular season?"}
  ros["fresh rosters + cached league users<br/>build_rosters, find the target team"]
  proj["ProjectionsClient (api.sleeper.com)<br/>snapshot() for waiver candidates,<br/>week() otherwise"]
  lw["services.weekly<br/>load_weekly"]
  sched["Sleeper schedule<br/>api.sleeper.com"]
  espnn["ESPN scoreboard<br/>kickoff times, game status"]
  status["fresh SleeperClient.player<br/>for each rostered player;<br/>player_news only if questionable/doubtful"]
  match["league matchups<br/>roster and matchup starters must agree"]
  ctx["WeeklyContext<br/>game timing, availability, IR eligibility"]
  fail(["refuse with a one-line error<br/>(Clarification, ValueError or _fail)"])

  lineup_own["lineup's own fresh reads<br/>state, league, rosters,<br/>ProjectionsClient.week"]
  cur{"current season<br/>and week?"}
  reg{"regular season?"}
  projonly(["projection-only scenario"])

  lu_out["cli.lineup renders Panel + Table,<br/>render_weekly_notes, run_qa('lineup')"]
  a_lu["analysis.lineup<br/>optimal_lineup<br/>locks started games, skips taxi / IR / unavailable"]
  a_cmp["analysis.compare<br/>compare_players"]
  a_ww["analysis.weekly_waivers<br/>weekly_waivers"]
  jo["services.llm.jev_output<br/>render_comparison / render_weekly_waivers<br/>(each runs its own run_qa)"]

  compare --> prep
  ww --> prep
  askw --> prep
  prep --> gate
  gate -- no --> fail
  gate -- yes --> ros
  ros -- team not found --> fail
  ros --> proj
  proj -- no projections --> fail
  proj --> lw
  lw --> sched & espnn & status & match
  sched & espnn & status & match --> ctx
  lw -- "sources disagree, no matchup,<br/>starters mismatch, no fresh status" --> fail

  lineup --> lineup_own
  lineup_own -- no projections --> fail
  lineup_own --> cur
  cur -- yes --> reg
  reg -- no --> fail
  reg -- yes --> lw
  cur -- no --> projonly --> a_lu

  ctx --> a_lu
  ctx --> a_cmp
  ctx --> a_ww
  a_lu --> lu_out
  a_cmp --> jo
  a_ww --> jo
```

## 6. `ff ask`

Two interpreters share one deterministic back end, and the model never computes. Jev only answers fixed choices, and code builds the arguments. A local model picks the tool and its kwargs, then explains the result in prose. Either way the calculation runs in `analysis/` through `dispatch_tool`, which accepts only names in `services.llm.tools.ALLOWED_TOOLS`, against the same lazily loaded data as the structured commands (`cli._analysis_ctx`). Through `ask`, values come from the cache; `evaluate_trade` gets no drift check and no offer rule.

```mermaid
flowchart TD
  q(["ff ask 'question'<br/>loads config.json if it exists"])
  pick{"backend<br/>--backend, else config.llm_backend, else auto"}

  subgraph localpath["Local runner: auto / agy / gemini / claude / ollama"]
    run1["runner.TerminalRunner.run<br/>print/headless subprocess, 120s timeout"]
    reply{"reply"}
    prose1["print the markdown"]
    onboard["setup_league<br/>onboarding.onboard_user<br/>saves config only if the league is unambiguous"]
    unknown["unknown tool:<br/>list ALLOWED_TOOLS"]
    nocfg(["no config yet:<br/>ask for a Sleeper username"])
    ctxl["cli._analysis_ctx<br/>KTC included"]
    run2["runner.TerminalRunner.run<br/>second call writes prose over the result"]
    qal["run_qa('ask')"]
  end

  subgraph jevpath["Jev: explicit opt-in, never chosen by auto; requires config"]
    ctxj["cli._analysis_ctx<br/>KTC excluded"]
    choose["jev.JevClient.choose<br/>one request to api.typesafe.ai<br/>(retried on 429/529), question text only"]
    interp{"jev.interpret<br/>operation confidence at least 0.80;<br/>team answer picks the method:<br/>mine = saved owner id, named = exact name<br/>or roster number in the question;<br/>then per-question confidence and guards"}
    weeklyprep["weekly tools: cli._prepare_weekly<br/>(section 5); waivers: trending adds"]
    render["jev_output.render_result<br/>tables + domain run_qa, no prose model"]
  end

  clar(["Clarification, exit 3"])
  jerr(["JevError: key, auth, rate limit,<br/>network, exit 1"])
  rerr(["no runner found or runner failed, exit 1"])
  dispatch["dispatcher.dispatch_tool<br/>ALLOWED_TOOLS only;<br/>local weekly tools call prepare_weekly<br/>when a team kwarg is given"]
  analysis["analysis/ functions"]

  q --> pick
  pick -- local --> run1
  run1 -- error --> rerr
  run1 --> reply
  reply -- markdown --> prose1 --> qal
  reply -- unknown tool --> unknown --> qal
  reply -- setup_league --> onboard --> qal
  reply -- "JSON {tool, kwargs}, no config" --> nocfg
  reply -- "JSON {tool, kwargs}" --> ctxl --> dispatch
  dispatch -. local .-> run2 --> qal
  dispatch -. "local: tool error" .-> qal

  pick -- jev --> ctxj --> choose
  choose -- error --> jerr
  choose --> interp
  interp -- "no single team, low confidence,<br/>guard fails" --> clar
  interp -- ok --> weeklyprep --> dispatch
  weeklyprep -- weekly gate fails --> clar
  dispatch -. jev .-> render

  dispatch --> analysis
```
