# Coding guardrails

Baseline inspected on 2026-10-05 at commit `5bd80cd397d516969c800849544e91751479ee50` (main source snapshot). These are existing repository rules and observed implementation constraints, not new application behavior. Sources: `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `pyproject.toml`, `Makefile`, `.githooks/pre-commit`, `.github/workflows/ci.yml`, `.gitignore`, and the source files named below. When prose is stale, use the source-backed contracts and flag the discrepancy.

## Style and tooling

- Maintain Python 3.9 compatibility. Use `from __future__ import annotations` with modern annotations. Follow the existing `src/ff/` package layout and local style; do not reformat adjacent code.
- Use Pydantic v2 models for domain data crossing module boundaries in `contracts/models.py`; update producers and consumers together. Config, Jev transport and QA report models have existing separate homes. Preserve `Field(default_factory=...)` for collection defaults.
- Ruff targets `py39`, line length 100, selects `E4`, `E7`, `E9`, `F`, and ignores `E501`. Tests additionally ignore `F401` and `E402`. This is the actual lint contract; no formatter, comprehensive Ruff rule set or strict mypy mode is configured.
- mypy targets Python 3.9, checks `ff` under `src`, uses `strict_optional`, `warn_unused_ignores` and `show_error_codes`. Keep existing narrow, justified ignores; do not suppress failures broadly.
- Use tools/code for calculations, sorting, parsing, schema extraction and checkable transformations. Keep interpretation and judgment separate from deterministic execution. Claim a command/check ran only from its literal output and exit status.

## Boundary constraints

- Do not introduce HTTP microservices, a web routing layer, ORM, database, auth/session system or job queue as an incidental refactor. This is a local CLI with module contracts and file state.
- Keep I/O in clients, CLI orchestration and services such as `services/weekly.py`. Do not put network/config reads or subprocess calls into `analysis/`.
- Do not expand analysis cross-imports. Existing conveniences include Sleeper's pure `player_name` and `values.ValueBook`; share helpers via the established modules rather than adding cyclic dependencies.
- Do not move calculations into model prompts or trust model arithmetic. `dispatch_tool` runs deterministic analysis; reject names outside `ALLOWED_TOOLS` and keep the advertised registry synchronized with dispatch branches.
- Do not confuse a local Python dictionary/model return with an HTTP response or promise a JSON CLI mode that does not exist. Direct commands render Rich terminal output. Dispatcher serialization uses `model_dump()`; ordinary `@property` values are not automatically included.
- Preserve `_guard`'s wrapped function signatures so Typer still sees argument/option definitions. Do not claim it catches every exception: strict `QAInvariantError` and unexpected programming/I/O failures are not uniformly converted into friendly messages.

## Domain constraints

- Derive league format from Sleeper settings. Do not ask users for format or guess superflex/PPR/team count. Preserve the source-defined TEP mapping: FantasyCalc accepts `te+`/`te++` strings, not a numeric premium; KTC selects matching nested tiers. Keep dedicated TE-slot detection and the qualification for premiums below supported cut points. Lineup scores raw stats with `scoring_settings`, including `bonus_rec_te`; do not apply that reception bonus twice.
- Keep player-only totals in `roster` and `power`. Draft capital belongs in `picks`/trade/draft surfaces; folding picks into player power totals requires an explicit scope decision.
- Join roster players using FantasyCalc `sleeperId`. Preserve `secondary_value` plus `ktc_value`/`dealer_value` input/property compatibility. The active secondary provider is KTC; do not treat the compatibility Dealer module as a separate live market.
- Preserve pick tier suffixes in `normalize_pick`; otherwise early/mid/late keys collide. Resolve slot picks to round values and use the existing flat/Mid fallbacks. Preserve exact KTC tier values when requested; flag generic Mid stand-ins with `secondary_approx` and do not use them to pass an exact-price offer rule. Do not invent a price for an unpriced pick round.
- For future picks, reconcile default endowment with traded picks, retaining the last re-trade owner and the original roster ID. Determine tier from the original team's power rank. Prefer league `draft_rounds` over startup-draft rounds; retain traded higher rounds and explicit `--rounds` overrides.
- Use the individual `draft/{id}` endpoint for live `slot_to_roster_id`; do not substitute the league drafts list. Keep draft reads fresh (TTL 0). Direct draft fit excludes drafted and rostered players. Its roster-relative bounded fit tilts do not add age or format scarcity already priced by FantasyCalc.
- Do not start taxi/IR players. Keep laminar slot assignment in the shared score-independent `_assign`/`starting_slots` helpers; do not claim optimality for overlapping or unsupported slots. Dynasty waiver eligibility supports `WRRB_FLEX`/`REC_FLEX` even though weekly lineup optimization rejects those combinations.
- Filter waiver ownership, eligible league positions and requested position before limiting results. General dynasty requests search the broader active/market/trending pool; trending is annotation unless explicitly requested as a filter. Describe results as unrostered, never automatically claimable or instantly available. Pending claims, waiver clearance and pickup legality require Sleeper.
- Keep dynasty waiver opportunity separate from weekly lineup gain. Weekly waivers evaluate the full projected unrostered pool with verified timing/availability and rank whole-lineup improvements. Reject `--weekly --all`.
- Cleanup must distinguish active, taxi and IR capacity. Dropping a taxi/IR player frees no active space; an active bench drop, eligible bench-to-taxi move or permitted active-to-IR move opens active room. Preserve shared `designation`/`ir_eligible_statuses` reserve rules; cap suggestions at open capacity, skip Coach's Decision IR scratches and avoid IR/taxi candidate duplication.

- Trade totals include the sites' package adjustments, not just asset sums. Preserve JS-compatible rounding/numerical behavior, complete KTC pricing/top-value inputs, KTC's own rounded combined-side fairness measure, and raw-only positional deltas. Do not substitute mocked/self-retyped formulas for the golden live-site vectors.
- Direct trade fetches fresh values and shows provenance; the default offer rule requires strictly under 10% of the larger side in each market and KTC Fair Trade. Missing/approximate values, redraft or calculator drift must remain CANNOT_JUDGE, not a guessed pass/fail. Keep content/version-addressed formula fingerprint checks before trusting the rule.
- Arbitrage differences use rank-restated KTC values on the FC scale (averaging ties). Keep raw market numbers visible, but do not subtract their incompatible raw scales for recommendation gaps.
- The standalone `scripts/find_offers.py` searches owned player/pick packages and obeys the same offer rule; do not turn recommendations into trade execution or conflate it with the direct `ff trade` evaluator. CBS links remain manual context, not automatic model inputs or overrides.

## Weekly-data constraints

- Do not present cached roster metadata as fresh injury clearance. Current weekly flows refresh state/league/rosters/projections and owned-player statuses and validate roster/matchup starter alignment.
- Validate schedule and scoreboard season, regular-season type, week and opponent pairings before trusting kickoff/status. Require timezone-aware observation and kickoff values. Freeze existing assignments with unknown timing; exclude such new candidates instead of assuming their games have not started.
- Preserve already locked slots and actual scores. If actual points are unavailable, label the displayed zero/incomplete total. Do not replace a completed game's result with projected points.
- Fail closed for unsupported slots, best-ball, AutoSubs, unverified/invalid IR eligibility, excess active capacity or capacity override. Keep questionable/doubtful recommendations conditional and retain replacement deadlines/warnings.
- Other-week direct lineup scenarios are projection-only; current injuries and locks are not applied. `_prepare_weekly` requires the configured season to match fresh state. Choose the open week with `_current_week = max(1, week, display_week)`, because the two state fields can roll over in either order. Do not restore the older display-week-only fallback.
- Do not treat a passed QA invariant suite as proof of provider freshness, interpretation accuracy, legal transaction eligibility or fantasy outcome quality.

## LLM and credentials

- Use local runners only in the existing print/headless modes with a 120-second timeout. Do not add permission-bypass flags. Supported binaries are currently `agy`, `gemini`, `claude`, `ollama`; automatic selection follows that order and never chooses paid Jev.
- Jev must stay explicitly selected, pinned by default to `jev-1.13.0` (unless `TYPESAFE_MODEL` overrides), with confidence floor 0.80, fixed Choice questions and locally built arguments. Do not lower thresholds, guess team identity, silently discard requested restrictions or add a fallback model to hide failure.
- Preserve local resolution of `mine` by saved owner ID and named teams by explicit full name/roster number. Reject conflicting ownership wording, unsupported execution requests and unverifiable acquisition conditions.
- TypeSafe receives the question and classification schema, not appended league datasets. Local terminal synthesis does receive dispatched results; do not generalize Jev's payload boundary to every backend.
- Preserve the 15-second TypeSafe request timeout, disabled redirects and at most two retries only for 429/529. Keep provider error messages safe and do not expose credentials or raw provider replies.
- Keep all application state under `FF_HOME`. Store the optional key separately via hidden input and atomic mode-0600 replacement. Never print, commit or request credentials in chat. Remember `make clean` removes the default saved key.

## Existing rough edges to preserve unless specifically addressed

These are observed compatibility/implementation details, not patterns to spread:

- Tool parameter schemas are instructions to local models, not a global runtime validation layer. Dispatcher accepts extra kwargs such as `get_waivers.trending_only` and cleanup `limit` absent from their advertised schemas. CLI-local onboarding also accepts `league_id` beyond advertised `setup_league.username`. Jev constructs a narrower set itself. `api-contracts.json` records these differences; do not claim strict schema enforcement.
- Broad catches exist around optional KTC loading, legacy compatibility paths, lazy projection loading and local `ask` dispatch. Do not extend catch-all handling to hide required weekly data failures, model failures or invalid primary inputs.
- `_book` retries an older `include_ktc` signature after `TypeError`; `values/dealer.py` and legacy property aliases support existing integrations. Avoid unrequested removal or new general abstractions.
- Most command bodies emit their result before QA. Local `ask` can print onboarding/unknown-tool/calculation failures and return normally (exit 0); strict QA may instead raise. Do not infer a universal exit-1 error contract.
- Older supplied architecture prose includes stale TEP, KTC-layout, cleanup and week-selection claims. Current source supports provider TEP tiers, script-embedded KTC JSON, IR moves and the later of week/display_week. The local runner uses Claude rather than a Codex binary. Keep source-derived specs current without editing unrelated instructions.

## Required verification commands

Run from the repository root after dependencies exist. Setup is `make install` (also configures `.githooks`); CI's reproducible dependency setup is `uv sync --frozen --extra dev`.

| Check | Local command | Scope |
| --- | --- | --- |
| Lint | `make lint` or `./.venv/bin/python -m ruff check` | Configured Python lint rules |
| Types | `make typecheck` or `./.venv/bin/python -m mypy src` | Application typing |
| Offline gate | `make test` or `./.venv/bin/pytest -q` | Curated deterministic fixtures; live marker excluded by default |
| Package build | `make build` or `uv build` | PEP 517 sdist/wheel |
| Full local gate | `make check` | Lint, typecheck, offline tests, build |
| Whitespace/scope | `git diff --check` and `git status --short` | Review tracked diff plus newly created/untracked files separately |
| Live API canaries | `make test-live` or `./.venv/bin/pytest -m live` | Real provider shape/freshness checks; optional league-specific checks use `FF_LIVE_LEAGUE_ID` |

`.githooks/pre-commit` runs only the offline suite, using `.venv/bin/python` or `python3`; the hook is enabled by `make install`/`make hooks`, not merely by existing in Git. CI tests Python 3.9, 3.10, 3.11 and 3.12 with frozen dependencies, Ruff, mypy, offline pytest and `uv build` on main pushes and pull requests. Live tests and paid Jev evaluations are not CI/offline gates. Before shipping provider-facing changes run live checks and report skips; before committing/opening a PR run the local lint/type/test gates and review scope.

Offline HTTP tests use `responses`; `tests/conftest.py` redirects `FF_HOME` to a temporary directory. Do not read/write real league config in tests. Mocked interface changes require a matching contract check; prioritize integration smokes and schema validation over heavy mocking. A practical bug regression must be run and fail before the fix, then pass after it. Documentation-only verification should parse/check the generated contracts and establish source-file preservation; no new application regression is needed for this baseline.

For calculator port/parity changes, run the offline golden-vector tests and the real-site oracle with Node 18+ (`node scripts/calculator_oracle.mjs --check tests/fixtures/calculator_vectors.json`), plus the affected live calculator checks. Do not generate replacement golden vectors merely to hide drift; retain formula/fingerprint evidence. The oracle is networked and excluded from the ordinary offline gate.

For changes to Jev questions, confidence floor, routing or default model, run the affected opt-in paid suites with a privately configured key:

```sh
./.venv/bin/python scripts/eval_jev.py
./.venv/bin/python scripts/eval_jev.py --cases evals/jev-boundaries.json
./.venv/bin/python scripts/eval_jev.py --cases evals/jev-waivers.json
./.venv/bin/python scripts/eval_jev.py --cases evals/jev-weekly.json
```

Main/boundary acceptance: at least 90% exact supported routes, every unsupported case abstaining, zero API errors, passing fixed `Show my roster` control (`get_roster`, `team="1"`, `limit=15`). Focused waiver coverage requires all 22 cases passing twice consecutively; weekly coverage requires all 23 passing twice. Check case results, not only exit status. Historical results in `evals/README.md` are not a fresh run or independent accuracy/calibration evidence.

## Change and specification hygiene

Keep changes surgical, reuse project patterns, and remove only orphans caused by the requested change. Verify the intended branch/worktree before edits and preserve pre-existing work. Leave temporary inspection scripts outside the repository. Do not create unrelated features, helpers, refactors, tests or abstractions. For future brainstorming/planning, anchor architecture/schema/API contracts in `.ai/specs/` before execution tasks. Assign atomic file scopes to delegated work and ask code reviewers to check architecture drift, unrequested abstractions and spec violations. The specification change is limited to the three requested spec files. The follow-up merge/push instruction authorizes integration of these files, while unrelated local changes and application code remain outside scope.
