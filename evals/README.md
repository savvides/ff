# Jev routing evaluation

Run from the repo root, after saving a key with `ff config set-jev-key` or
exporting `TYPESAFE_API_KEY` in the same terminal:

```bash
./.venv/bin/python scripts/eval_jev.py
```

This is an opt-in, paid API evaluation. It sends the 40 synthetic questions in
`jev.json` to TypeSafe, one API call each (40 per run, plus any retries), and
matches them to synthetic teams locally, without accessing your Sleeper league.
Requests have a 15-second timeout; only rate-limit and overload replies (HTTP
429/529) are retried, twice, after a short pause. The script prints its report
to stdout and does not save responses. The tested default is pinned to
`jev-1.13.0`; `TYPESAFE_MODEL` can override it. The report records resolved model IDs.

Acceptance requires at least 90% exact operation-and-argument accuracy across
29 supported questions, abstention on all 11 unsupported/ambiguous questions,
no API errors, and a passing fixed control. API errors never count as abstentions.
Low-confidence abstentions on supported questions count as incorrect.

The fixed control is **"Show my roster"**, resolving to `get_roster` with
`team="1"` and `limit=15`. Keep it unchanged when tuning prompts. Offline tests
verify this control's routing mechanics with mocked responses; live model
performance requires running this evaluator. Do not treat mock results as model
accuracy. This small set is a pilot gate, not a fantasy-outcome benchmark or a
calibration study. Do not lower thresholds merely to make the set pass.

Exit codes: `0` passes; `1` fails a gate; `2` means the API key is missing or cannot be loaded.
The report includes case IDs, exact accuracy, abstentions, API failures, resolved
model versions, latency, and token usage. Each abstention names the ff question
that abstained, ff's own message, and, when it fell below the floor, its
confidence; each incorrect case shows the locally built route, and each API
error its message. It excludes credentials and raw replies.
`api_calls` counts all HTTP attempts, including retries and failed requests;
`valid_responses` counts responses accepted by the client. Token totals cover
only those valid responses, so they are not a billing total when calls fail.

## Additional phrasing and boundary checks

```bash
./.venv/bin/python scripts/eval_jev.py --cases evals/jev-boundaries.json
```

This separate set has 16 supported cases (including the unchanged control) and
14 must-abstain cases. It uses the same gate: at least 90% supported exact matches,
every unsupported case abstaining, no API errors, and a passing control. It covers
different wording, roster numbers, and unsupported markets, scoring rules, draft
years/rounds, positions and result counts. The original 40 question texts and percentage/error/control gates remain unchanged. The named-player start/sit case is now supported; the explicit trending query expects `trending_only=true`.
These are regression sets used during development, not an independent accuracy estimate.

## Verified 2026-09-25 on jev-1.13.0

The unchanged original gate first reproduced 23/28 supported matches, with 12/12
abstentions and no API errors. After clarifying the operation, position, filter
and count questions and adding the calculation-settings guard:

| Suite | Final run 1 | Final run 2 | Unsupported abstentions (both runs) |
|---|---|---|---|
| Original 40 cases | 27/28 (96.4%) | 27/28 (96.4%) | 12/12 |
| Additional 30 cases | 15/16 (93.8%) | 16/16 (100%) | 14/14 |

Both runs of both suites passed the unchanged 90% gate, the fixed control, and
the zero-API-error requirement. No incorrect route executed in these final runs;
misses were clarification responses. The confidence floor stayed at 0.80.
"Show the top three players on Dynasty Warriors" still needed clarification in
both original runs. "Value my top 8 players" needed clarification in one
additional run. Small wording changes and provider variability can affect results.

All seven real `ff ask --backend jev` journeys (roster, power, values, waivers,
picks, cleanup and lineup) also completed against the configured Sleeper league
with `FF_QA=strict`: exit 0, expected interpretation/table, passing domain QA,
and empty stderr. Private league output and credentials are not included here.

## FA and waiver root-cause investigation, 2026-09-25

The initial focused evaluation matched 9/11 supported waiver requests plus the
roster control, and rejected 9/10 unsupported requests. Rechecks also exposed
inconsistent immediate-pickup filtering. The plan was to reproduce each failure,
fix candidate selection and interpretation separately, then verify the original
cases, the fixed roster control, and real league results before shipping.

| Failure | Root cause | Fix and verification |
|---|---|---|
| Kickers recommended in a no-kicker league | Waiver analysis never received starting slots. Its zero-value opportunity floor let trending kickers rank. | Pass league slots through both commands, filter before ranking/limit, and add a QA eligibility invariant. Tests cover kicker-enabled leagues and overlapping flexes too. |
| Non-trending RBs omitted | A sample of 50 trending adds was the entire candidate universe. | General requests now search active NFL players and market-listed prospects. Non-trending RB regression passes; the live RB results include the previously omitted player. |
| Available QB query returned nothing | The same truncated candidate universe contained no unrostered QB. | The full pool is searched before position and count filters. Live QB requests now return results and include the previously omitted candidate. |
| `Show 3 FA RBs` abstained | Classification questions did not explain the FA shorthand, causing operation and position ambiguity. | Define FA/FAs and position abbreviations in the classification questions. Exact query passes both final live runs and the real CLI journey. |
| This-week pickup request sometimes abstained | The count question treated pickup wording as an ambiguous quantity. | Clarify that pickup verbs and current-week wording do not specify a result count. The query resolves to the existing default of 20 in both final live runs. |
| Claim submission became a recommendation | A broad operation question was the only mutation check. | A separate action question distinguishes analysis from execution. Claim submission prints a read-only explanation, exits 3, and never dispatches. |
| Immediate-only request silently lost its restriction | Unrostered ownership was conflated with acquisition eligibility; there was no explicit acquisition-condition check. | Label results unrostered with unknown claim status. Explicit immediate/claim-state requests abstain with guidance to check Sleeper. |

The [public Sleeper API](https://docs.sleeper.com/) is read-only. This change does
not add transactions or infer pending-claim/instant-pickup eligibility from
roster ownership. Rankings remain dynasty opportunity heuristics, not weekly
projected-point rankings. Explicit trending requests retain their sample filter.

Six new regression cases failed against the original implementation before the
fixes. They pass afterward, along with additional guard, filter, and QA checks.
The 0.80 confidence floor and existing acceptance thresholds are unchanged.

```bash
./.venv/bin/python scripts/eval_jev.py --cases evals/jev-waivers.json
```

The focused set contains 11 supported waiver queries, the unchanged `Show my
roster` control, and 10 must-abstain queries. For this fix, all 22 must pass on
two consecutive runs, in addition to the broader suites' existing gates.

| Final verification | Exact supported | Must abstain | API errors | Control |
|---|---|---|---|---|
| Original 40 questions | 27/28 | 12/12 | 0 | pass |
| Additional 30 questions | 16/16 | 14/14 | 0 | pass |
| Focused FA/waivers, run 1 | 12/12 | 10/10 | 0 | pass |
| Focused FA/waivers, run 2 | 12/12 | 10/10 | 0 | pass |

The original known ambiguous named-team query (`roster_other`) still asks for
clarification. No incorrect route executed in these final evaluations. These
are development regression results, not an independent accuracy estimate.

Ten real league journeys passed with `FF_QA=strict`: eight recommendation
requests, including non-trending RB/QB coverage and explicit trending WRs,
plus two unsupported requests. Returned structured results matched direct
analysis exactly; current roster ownership, requested position/count, and
league-slot eligibility were checked independently. Both unsupported requests
exited 3 without dispatch. No league transactions occurred.

`make check` passed Ruff, mypy, all 575 offline tests, and package build.
`git diff --check` passed. No restart is required.


## Weekly decisions, 2026-09-25

Plan and source boundaries: [weekly decisions plan](../docs/weekly-decisions-plan.md).
Current-week lineup advice now applies fresh availability and kickoff constraints;
`ff compare` compares two named rostered players; `ff waivers --weekly` ranks the
full projected unrostered pool by whole-lineup gain. The same functions serve Jev.

Two expected routes changed because the supported capability expanded, not to
relax a gate: `Start Gibbs or Bijan?` now resolves to a start/sit comparison, and
`Who should I pick up on waivers this week?` now selects weekly lineup improvement.
The main set therefore has 29 supported and 11 unsupported cases. Original question
texts, the 0.80 floor, 90% broad accuracy threshold, zero-error requirement, every
unsupported abstention and fixed `Show my roster` control remain intact.
Synthetic player IDs are resolved locally and never appended to Jev's input.

```bash
./.venv/bin/python scripts/eval_jev.py --cases evals/jev-weekly.json
```

This fourth set contains 11 supported cases and 12 must-abstain cases. It covers
full/short player names, different start/sit phrasing, weekly lineup-gain waivers,
trending filters, dynasty and lineup controls, ambiguous/unowned players, other
weeks, custom scoring, execution requests and acquisition conditions. Require all
23 passing twice, plus the existing broader and focused waiver gates.

| Final evaluation on jev-1.13.0 | Exact supported | Required abstentions | API errors | Control |
|---|---|---|---|---|
| Main, 40 cases | 28/29 | 11/11 | 0 | pass |
| Boundaries, 30 cases | 15/16 | 14/14 | 0 | pass |
| Focused waivers, final run 1 | 12/12 | 10/10 | 0 | pass |
| Focused waivers, final run 2 | 12/12 | 10/10 | 0 | pass |
| Weekly decisions, final run 1 | 11/11 | 12/12 | 0 | pass |
| Weekly decisions, final run 2 | 11/11 | 12/12 | 0 | pass |

The main `roster_other` and boundary `picks_default` phrasings abstained below the
floor. Earlier tuning runs exposed false abstentions on short names, team selection,
and a weekly ranking objective; the comparison team question is now separate from
the existing roster team question. One earlier boundary response failed schema
validation, and one intervening focused-waiver run abstained on `fa_rb` at 0.75.
No incorrect route executed in these final evaluations. These are development
regressions with provider variability, not independent accuracy estimates.

Live strict-QA journeys covered direct lineup, direct and Jev comparisons, and
direct and Jev weekly waivers. The real Thursday starters retained their exact
slots and actual scores. Offline direct/Jev parity tests use the same snapshot and
compare the complete rendered result (excluding QA elapsed time). A rendering
variable bug found by strict QA and an unknown-timing injury contingency bug both
have reproduced regression tests and verified fixes.

The live suite passed 9 checks; the optional KTC check skipped because no values
were returned. Weekly features do not depend on KTC. New live checks exercise the
cross-provider schedule, fresh projection/player/news shape and roster/matchup
slot alignment. The schedule/player endpoints are undocumented; unknown timing
freezes assignments, and unsupported league rules refuse actionable advice.

`make check` passed Ruff, mypy, all 644 offline tests, and the package build.
`git diff --check` passed. No restart is required.
