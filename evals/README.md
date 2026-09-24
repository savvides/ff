# Jev routing evaluation

Run from the repo root, with `TYPESAFE_API_KEY` exported in the same terminal:

```bash
./.venv/bin/python scripts/eval_jev.py
```

This is an opt-in, paid API evaluation. It sends the 40 synthetic questions in
`jev.json` and synthetic team options to TypeSafe, without accessing your Sleeper
league. There are at most 80 API calls. Requests have a 15-second timeout and are
not retried. The script prints its report to stdout and does not save responses.
Set `TYPESAFE_MODEL` to a supported pinned model ID for comparable repeated runs;
otherwise the default is `jev-latest`. The report records resolved model IDs.

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

Exit codes: `0` passes; `1` fails a gate; `2` means the API key is missing.
The report includes case IDs, exact accuracy, abstentions, API failures, resolved
model versions, latency, and token usage. It excludes credentials and raw replies.
