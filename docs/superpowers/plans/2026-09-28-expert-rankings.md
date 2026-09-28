# Expert Rankings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add attributable weekly expert comparisons and dynasty disagreement signals without changing existing recommendations or valuations.

**Architecture:** Source adapters produce validated ranking snapshots; pure analysis checks applicability and computes comparisons. Optional CLI flags render that evidence and preserve requested pair comparisons for a future prospective evaluation. Validate source access before building the integration.

**Tech Stack:** Python 3.9+, existing requests, Pydantic 2, Typer, Rich, pytest, responses, Ruff, and mypy; standard-library parsing and hashing. No new dependency is planned.

**Spec:** [Approved expert-ranking design](../specs/2026-09-28-expert-rankings-design.md). Written specification approved in the user's subsequent “proceed” message. This plan awaits review and an execution-method selection.

## Global Constraints

- “Expert ranks never become invented projected points or trade dollars.”
- “The first release displays expert evidence without changing recommendations.”
- Weekly freshness: requested season/week, source age no more than 48 hours; dynasty freshness: no more than 30 days. Retrieval time is not publication time.
- Unknown/mismatched material format assumptions and missing/uncertain/future/stale publication dates cannot contribute to counts or rank differences.
- Count each analyst once per pair; position scope precedes FLEX, then overall, then newest update. Equal-precedence conflicts exclude the analyst.
- Dynasty comparison uses competition ranks within the same shared player pool; positive `market rank - expert rank` means expert above market. Filter display candidates only after ranking.
- “All local state lives under FF_HOME”; use temporary `FF_HOME` in tests. No background collection, transactions, credentials, or personal league snapshots in Git.
- Keep I/O outside `analysis/`; inject UTC evaluation time. Preserve locks, availability, both-players-start results, default CLI output, and Jev routing.
- Use existing Python 3.9 conventions and module boundaries. Preserve unrelated changes to `CLAUDE.md` and untracked `AGENTS.md`.
- No evaluator, automatic tie threshold, blend weights, new routing operation, generic scraper, or manual import workflow in this release.
- Source viability is a gate: no product implementation after Task 1 unless both horizons have validated usable sources. A substitute publisher requires the source decision described in the spec.

## Review Focus

1. An analyst's date refers to the article wrapper, not the ranking revision: exclude uncertain evidence instead of treating a newly fetched old list as current (Tasks 1, 3, 4).
2. One author appears in positional, FLEX, and syndicated lists: count once and reject equal-precedence conflicts (Task 4).
3. A truncated HTTP-200 response looks like a short valid list: require source-specific completeness evidence while allowing a deliberately published top-N list (Tasks 1, 3).
4. Two concurrent CLI calls write the same snapshot, or storage fails after analysis: preserve immutable records and show the base result with an explicit recording warning (Tasks 2, 5).
5. Expert labels contain Rich markup, and CLI filtering changes the apparent dynasty gap: render source strings literally and compute ranks before display filters (Tasks 4, 5).

## File map and execution order

Create `src/ff/contracts/rankings.py` for ranking-only contracts; import it directly rather than enlarging `models.py`. Create `src/ff/rankings/{__init__,identity,storage,cbs}.py` for provider I/O, identity joins, and persistence. Create `src/ff/analysis/rankings.py` for applicability, deduplication, preferences, and shared-pool ranks. Create `src/ff/services/expert_output.py` for Rich rendering. Modify only the three affected commands in `src/ff/cli.py` and add an `experts` validator in the existing QA files.

Each task owns matching tests named below. Source fixtures live in `tests/fixtures/rankings/`. Provider findings go in `docs/expert-ranking-sources.md`; user documentation goes in `README.md`. Do not create empty modules before their owning task. Tasks 1–6 are sequential because each consumes the preceding contracts or evidence.

At execution time, use the worktree skill and managed-worktree tools to establish suitable isolation, carrying the approved spec and plan into that checkout. Inspect branch/base and preserve existing changes. Run the current offline gate as a baseline before modifying product code. Do not push, merge, or deploy as part of this plan.

---

### Task 1: Establish usable sources and extraction evidence

**Files:** Create `docs/expert-ranking-sources.md` and `tests/fixtures/rankings/cbs-weekly.txt`, `cbs-dynasty.txt`, `expected.json` only after access and reuse checks pass. These are curated fixture extracts, not complete republished lists.

**Interfaces:** Consumes the two CBS page URLs in the spec. Produces a documented source contract for Task 3: exact accessible URLs, content type, field paths/selectors, completeness signal, author identity, horizon/scope, scoring declarations, timezone/date provenance, and representative expected rows. No undocumented API endpoint is assumed.

- [ ] **Step 1: Inspect actual published lists and metadata.** Use read-only web/HTTP tools. Record findings independently for weekly and dynasty lists, distinguishing article dates from ranking dates and a complete top-N list from a partial response. Record access/reuse constraints and whether authentication/payment is required; do not purchase access or bypass a restriction.
- [ ] **Step 2: Verify the source contract.** Cross-check at least three rows per horizon against the visible published list, including author, rank, and player. Confirm at least one applicable scope per horizon with established freshness and material scoring assumptions. Record exact unresolved fields if this fails. A context-only list does not satisfy this gate.
- [ ] **Step 3: Stop or preserve representative fixtures.** If either horizon fails, report the precise blocker and propose a verified alternative as required by the spec; do not build a speculative adapter. If both pass, save a small structurally representative extract in each `.txt` and an `expected.json` with the fixture metadata, rows, counts, and relevant timestamps. Keep actual update dates; tests will inject an appropriate clock.
- [ ] **Step 4: Check and commit source evidence.** Validate the expected JSON with `./.venv/bin/python -m json.tool tests/fixtures/rankings/expected.json`; run `git diff --check`. Inspect the staged files for personal data and unintended source content. Commit only these files with `docs: record validated expert ranking source contracts`.

### Task 2: Define contracts, safe player matching, and immutable storage

**Files:** Create `src/ff/contracts/rankings.py`, `src/ff/rankings/__init__.py`, `src/ff/rankings/identity.py`, `src/ff/rankings/storage.py`; create `tests/test_ranking_models.py`, `tests/test_ranking_identity.py`, `tests/test_ranking_storage.py`.

**Interfaces:** Define these Pydantic contracts in `contracts/rankings.py`; datetime fields used for ordering must be timezone-aware:

- `RankingEntry`: `source_id: Optional[str]`, `name: str`, `position: str`, `team: Optional[str]`, `rank: int`, `tier: Optional[str]`, `sleeper_id: Optional[str]`.
- `RankingSnapshot`: `revision_id: str`, `publisher: str`, `analyst_id: str` (canonical across syndication), `analyst_name: str`, `source_url: str`, `retrieved_at: datetime`, `published_at: Optional[datetime]` (conservative earliest instant for date-only sources), `date_precision: Literal['timestamp','date','unknown']`, `source_date: str`, `source_timezone: Optional[str]`, `horizon: Literal['weekly','dynasty']`, `season: Optional[str]`, `week: Optional[int]`, `scope: str`, `positions: List[str]`, `scoring: Dict[str,float]`, `superflex: Optional[bool]`, `num_teams: Optional[int]`, `entries: List[RankingEntry]`, `published_count: int`. Missing scoring keys mean unknown; explicit zero means known zero. Validate allowed scopes and position membership.
- `RankingIssue`: `source_url: str`, `revision_id: Optional[str]`, `reason: str`.
- `RankingBatch`: `snapshots: List[RankingSnapshot]`, `issues: List[RankingIssue]`.
- `ExpertVote`: `revision_id: str`, `analyst_id: str`, `publisher: str`, `rank_a: int`, `rank_b: int`, `preferred_id: Optional[str]` (None is a tie).
- `ExpertMover`: `revision_id: str`, `player_id: str`, `name: str`, `position: str`, `value: int`, `published_rank: int`, `expert_rank: int`, `market_rank: int`, `gap: int`, `pool_size: int`.
- `ExpertDecisionRecord`: `decision_id: str`, `recorded_at: datetime`, `season: str`, `week: int`, `player_ids: List[str]`, `roster: Roster`, `roster_positions: List[str]`, `scoring: Dict[str,float]`, `weekly: WeeklyContext`, `comparison: PlayerComparison`, `evidence: RankingBatch`, `votes: List[ExpertVote]`. Embed evidence so the record remains interpretable after cache cleanup or a separate snapshot-write failure.

Functions: `resolve_entries(snapshot: RankingSnapshot, players_meta: Dict[str,Any]) -> RankingSnapshot`; `save_snapshot(snapshot: RankingSnapshot) -> Path`; `load_snapshots(horizon: str) -> RankingBatch`; `save_decision(record: ExpertDecisionRecord) -> Path`.

- [ ] **Step 1: Write failing contract, matching, and storage tests.** Reject rank 0, blank author/URL, duplicate source identities, two entries resolved to one Sleeper ID, and weekly snapshots without season/week. Allow published rank ties and unresolved individual players. Test exact full-name matching, suffix normalization, verified IDs, duplicate-name ambiguity, and a stale team label on an otherwise unique name. Assertions must include `resolved.entries[0].sleeper_id == 'a'`, ambiguous match `is None`, and unchanged source name/rank. Storage tests assert saved JSON round-trips, a repeated revision preserves its original `retrieved_at`, distinct decision IDs produce distinct files, and all paths are below temporary `FF_HOME`.
- [ ] **Step 2: Run the new tests and confirm missing-contract/function failures.** Run `./.venv/bin/pytest -q tests/test_ranking_models.py tests/test_ranking_identity.py tests/test_ranking_storage.py`.
- [ ] **Step 3: Implement the interfaces.** Reuse `normalize_name` for candidate matching; never use `ValueBook.resolve`'s fuzzy matching for source joins. Resolve only a uniquely supported identity and retain unresolved rows. Use SHA-256 revision IDs over canonical source metadata and entries, excluding retrieval time and local Sleeper resolution. Store source revisions under `FF_HOME/rankings/snapshots/` and decisions under `FF_HOME/rankings/decisions/`. Publish complete temporary files with an exclusive create/link operation so concurrent writes cannot replace an existing immutable file. Corrupt snapshot files yield issues, not successful empty data; write errors propagate to CLI handling in Task 5.
- [ ] **Step 4: Run the tests to passing.** Include concurrent same-revision writes, corrupt snapshot recovery, and denied-write failure cases. Re-read the preserved first snapshot and verify byte equality after the second write. Run `make lint` and `make typecheck`.
- [ ] **Step 5: Commit this task's modules and tests.** Use message `feat: add expert ranking contracts and immutable snapshots`.

### Task 3: Implement the validated CBS adapter

**Files:** Create `src/ff/rankings/cbs.py`, `tests/test_cbs_rankings.py`, `tests/test_rankings_live.py`; use Task 1 fixtures and source contract.

**Interfaces:** `parse_cbs(payload: str, source_url: str, retrieved_at: datetime) -> RankingBatch`; `fetch_cbs(horizon: str, season: Optional[str], week: Optional[int], players_meta: Dict[str,Any], now: datetime) -> RankingBatch`. Return resolved valid snapshots and individual source failures. Preserve unknown assumptions; never fabricate defaults to make a list compatible.

- [ ] **Step 1: Write failing fixture and HTTP tests.** Compare parsed metadata and entries exactly with `expected.json`. Use `responses` for HTTP failures, invalid payloads, an incomplete HTTP-200 document, complete intentional top-N lists, and a fresh article wrapper surrounding old rankings. Assert a malformed list contributes no snapshot and a nonempty issue; another valid analyst list survives independently. Add a test that response retrieval time does not replace the source update date.
- [ ] **Step 2: Confirm the tests fail.** Run `./.venv/bin/pytest -q tests/test_cbs_rankings.py`; expected failure is the missing adapter.
- [ ] **Step 3: Implement the exact extraction described in Task 1.** Use requests with the existing HTTP session/retry/timeout pattern. Fetch on explicit expert commands, with no additional HTTP cache layer for version one; persisted validated snapshots are the fallback. Use standard-library JSON/HTML parsing according to the observed payload. Validate each list's completeness before resolving players or saving it. Retain original publication-date precision/timezone. On fetch or parse failure, return a visible issue and last valid snapshots for that horizon; Task 4 still applies freshness. A snapshot-write error adds an issue but retains the valid fetched snapshot in the returned batch. Never replace valid snapshots with a failed response.
- [ ] **Step 4: Run offline tests and a live shape check.** Mark live tests `pytest.mark.live`. `./.venv/bin/pytest -q tests/test_cbs_rankings.py` must pass offline. `./.venv/bin/pytest -q -m live tests/test_rankings_live.py` must fetch both validated horizons, assert attributed nonempty lists and documented metadata, and distinguish old-but-structurally-valid data from fresh evidence. Manually cross-check three rows per horizon again. Live failures are reported, not fixed by weakening checks.
- [ ] **Step 5: Commit the adapter, tests, and any source-contract corrections.** Message: `feat: fetch attributed CBS expert ranking snapshots`.

### Task 4: Compute applicability, expert preferences, and dynasty disagreements

**Files:** Create `src/ff/analysis/rankings.py`, `tests/test_ranking_analysis.py`; modify `src/ff/qa/validators.py`, `src/ff/qa/engine.py`; create `tests/test_ranking_qa.py`.

**Interfaces:** All functions are pure. `applicable_rankings(batch: RankingBatch, horizon: str, season: Optional[str], week: Optional[int], fmt: Format, scoring: Dict[str,float], compared_positions: List[str], now: datetime) -> RankingBatch` returns only usable snapshots plus original and new exclusion issues. `expert_preferences(batch: RankingBatch, player_a: str, player_b: str) -> Tuple[List[ExpertVote],List[RankingIssue]]` applies pair coverage and author precedence. `dynasty_movers(snapshot: RankingSnapshot, assets: List[Asset], min_value: int = 1000, limit: int = 20, direction: Optional[str] = None) -> List[ExpertMover]` uses direction `buy`, `sell`, or None. `validate_experts(batch: RankingBatch, votes: Optional[List[ExpertVote]] = None, movers: Optional[List[ExpertMover]] = None) -> List[QACheck]` is registered as `experts`.

- [ ] **Step 1: Write failing applicability tests.** Inject fixed UTC times. Assert 48 hours is accepted and 48 hours plus one second excluded; likewise 30 days and 30 days plus one second. Cover week/season mismatch, future/missing/uncertain dates, PPR mismatch, unknown versus explicit-zero bonuses, TEP involving TEs, positional RB lists versus RB/WR comparisons, and 1QB overall lists in superflex. Check a positional comparison can use a list despite an immaterial roster-format difference. For weekly scoring, compare relevant source-declared stat weights with the league's actual scoring settings; unrepresented material custom scoring makes evidence context-only. Dynasty uses the declared market format and preserves its TEP limitation.
- [ ] **Step 2: Write failing preference/rank/QA tests.** Use an analyst with positional, FLEX, and syndicated lists to assert one vote and precedence. Equal-precedence contradictory copies produce no vote and an issue; absent players produce no vote; equal ranks produce a tie. For expert order `a,b,c` and market values `a=100,b=300,c=200`, assert `(expert_rank, market_rank, gap)` is `a=(1,3,2)`, `b=(2,1,-1)`, `c=(3,2,-1)`. Raising the display floor to 150 must leave b/c gaps at -1, not recompute them to zero. Test tied values/order using competition ranks, excluded picks/zero values, insufficient shared pools, positive/negative direction filtering, and per-table limits. QA must reject duplicate analyst votes, missing revision references, and inconsistent gaps/counts.
- [ ] **Step 3: Confirm failures, then implement these interfaces.** Run `./.venv/bin/pytest -q tests/test_ranking_analysis.py tests/test_ranking_qa.py` first and inspect failures. Do not mutate assets or snapshots. For the dynasty usable-list selection, deduplicate latest per analyst/scope/format and exclude equal-precedence conflicts. Rank before applying display filters; sort by descending absolute gap then player ID. `dynasty_movers` raises `ValueError('insufficient shared pool')` for fewer than two usable players; the CLI converts that to an availability issue. A usable pool with zero disagreements returns an empty list, including direction=None (exclude gap zero). Use explicit exclusions; do not infer an unranked player's position in a list.
- [ ] **Step 4: Verify deterministic results and QA integration.** Rerun both new test modules and `tests/test_qa_engine.py tests/test_qa_validators.py`. Assert input model dumps match before/after analysis. In strict QA mode, corrupt evidence must raise the existing `QAInvariantError`; unavailable optional evidence is an availability condition, not an invariant failure.
- [ ] **Step 5: Commit analysis and QA changes.** Message: `feat: compare compatible expert and market rankings`.

### Task 5: Add optional CLI displays and prospective decision records

**Files:** Modify `src/ff/cli.py`; create `src/ff/services/expert_output.py`, `tests/test_cli_experts.py`, `tests/test_expert_output.py`; extend storage tests for decision content.

**Interfaces:** Add `experts: bool = typer.Option(False, '--experts')` to `lineup`, `compare`, and `movers`. Renderer interfaces: `render_expert_ranks(batch: RankingBatch, player_ids: List[str], console: Console) -> None`; `render_expert_votes(votes: List[ExpertVote], batch: RankingBatch, player_ids: List[str], console: Console) -> None`; `render_expert_movers(rows: List[ExpertMover], snapshot: RankingSnapshot, console: Console) -> None`; `render_expert_issues(issues: List[RankingIssue], console: Console) -> None`. Source-context ranks may be shown but must be labeled excluded using assessment issues; counts use eligible evidence only.

- [ ] **Step 1: Write failing CLI and rendering tests.** Without `--experts`, assert no ranking fetch/write and unchanged baseline output. With it, assert source links, date/scope/author, actual publisher count, literal bracket-containing names, exclusion reasons, and no confidence/probability claim. For `compare`, assert original recommendation, projected totals, both-players-start conclusion, and locked/unavailable alternative handling survive even when votes prefer the other player. For `lineup`, show ranks for displayed starters/bench, not a new lineup. For a historical scenario, assert no current-week evidence fetch and an explicit unavailability notice.
- [ ] **Step 2: Write failing movers and recording tests.** Reject `--experts --arbitrage` and `--experts --buy --sell` before a fetch. Valid no-disagreement results exit 0; unavailable or fewer-than-two shared players exit 1. Compare `--min-value`/`--limit` behavior against Task 4. Capture a comparison record and assert its saved `comparison.model_dump()` equals the baseline result, its evidence revisions resolve to embedded snapshots, and it contains scoring, decision time, roster slots, both alternatives, and weekly facts. A later invocation must create a new record rather than overwrite it. Simulate snapshot/decision write errors and assert the result still renders with a recording warning; do not claim evaluation data was saved.
- [ ] **Step 3: Run the new tests and confirm missing-flag/renderer failures.** Run `./.venv/bin/pytest -q tests/test_cli_experts.py tests/test_expert_output.py`.
- [ ] **Step 4: Implement orchestration and renderers.** Reuse the existing baseline computations and retain their QA. Fetch expert evidence only on the optional path. Derive fresh league format for expert compatibility from current Sleeper league data rather than asking the user or trusting a stale saved format; do not alter legacy command calculations. Assess each lineup scope against the relevant positions. Pass both original and assessed evidence to rendering through the batch/issues contracts. Register/render expert QA separately. Escape external strings or use Rich `Text`. Record only explicit current-week `compare --experts` calls; use a unique decision ID and immutable Task 2 storage. Record ineligible/locked comparisons faithfully so a future evaluator can exclude them; never mark them as evaluable observations. Suppress optional source/storage failures only with a visible explanation.
- [ ] **Step 5: Verify affected journeys and existing routing.** Run `./.venv/bin/pytest -q tests/test_cli_experts.py tests/test_expert_output.py tests/test_ranking_storage.py tests/test_cli.py tests/test_compare.py tests/test_lineup.py tests/test_cli_jev.py tests/test_dispatcher.py`. Assert no `Asset.value`/`secondary_value`, base recommendations, Jev tools, or interpretation questions changed. Verify command help includes the flags.
- [ ] **Step 6: Commit the CLI and rendering changes.** Message: `feat: show optional expert evidence in weekly and dynasty commands`.

### Task 6: Document behavior and run the release checks

**Files:** Modify `README.md` and `docs/expert-ranking-sources.md`; change product code only if checks expose a task-related defect, with a focused regression test.

**Interfaces:** Uses the three CLI flags and source contracts from Tasks 1–5. Produces user instructions and a verification record, not an automated tie-breaking policy.

- [ ] **Step 1: Document exact usage and limits.** Include `ff lineup --experts`, `ff compare 'PLAYER A' 'PLAYER B' --experts`, and `ff movers --experts --buy`. Explain dates, format exclusions, single-analyst evidence, shared-pool ranks, exit codes, and `FF_HOME/rankings/`. State that command-triggered recordings are not continuous coverage, snapshot tests do not prove improved decisions, and activation requires a separately reviewed prospective evaluation with held-out weeks. Document missing outcomes and correlated/repeated decisions as evaluator requirements, not implemented behavior.
- [ ] **Step 2: Run the full offline gate.** Execute `make check` and `git diff --check`. Expected: Ruff, mypy, default offline pytest, and package build all pass. Resolve actual failures; do not rerun successful suites without a relevant change.
- [ ] **Step 3: Run live checks.** Execute `make test-live`, including the new ranking tests. Report skipped league-dependent tests and external failures individually. For each enabled ranking source, cross-check representative ranks/metadata against the live publication; do not declare both horizons available if one fails. No paid Jev eval is needed unless routing changed contrary to this plan, in which case stop and review that scope change.
- [ ] **Step 4: Exercise the three user journeys.** Run the new CLI commands with valid current evidence where available; verify visible provenance, frozen base recommendations, and saved comparison data. Use deterministic CLI tests for unavailable sources, unsupported format, and historical-week cases that cannot be reproduced live. Report actual coverage separately from simulated coverage. Inspect final diff against the spec and preserve unrelated working files.
- [ ] **Step 5: Commit documentation and report the result.** Message: `docs: explain expert ranking evidence and validation limits`. Report changed behavior, checks actually run, source limitations, and disabled automatic tie-breaking. Do not claim improved recommendations from parsing/QA tests.

## Plan self-review

- Source feasibility and metadata provenance: Task 1, with an explicit gate before product work.
- Contracts, identities, immutable revisions and decision records: Tasks 2 and 5.
- Live adapter, complete-list detection, fallback and freshness: Tasks 3 and 4.
- Weekly scope/author counts and dynasty shared-pool arithmetic: Task 4.
- Three optional user journeys, source/context rendering, exit codes, QA, and preserved behavior: Task 5.
- Prospective activation boundary, live proof, gate checks, and documentation: Task 6.
- All five Review Focus items have named test assertions in their owning tasks. Automatic tie-breaking and its evaluator remain explicitly out of scope.

## Execution handoff

Recommended method: **Native**. These six tasks share contracts and provider evidence, so one implementer can carry that context through the sequential work; use one fresh whole-branch reviewer at the end. **Subagent-driven** is also available: a fresh implementer and reviewer per task, followed by whole-branch review, at higher context cost.

Review this plan and select the execution method before implementation. The source gate is part of the approved work, not a claim that CBS access has already been validated.
