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
28 supported questions, abstention on all 12 unsupported/ambiguous questions,
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
years/rounds, positions and result counts. The original 40 cases remain unchanged.
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
