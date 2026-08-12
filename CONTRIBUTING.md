# Contributing to ff

## Setup

```bash
make install     # creates .venv, installs ff + dev deps editable, enables the pre-commit hook
```

Manual equivalent: `python3 -m venv .venv && ./.venv/bin/python -m pip install -e ".[dev]"`.

## Tests

Two lanes:

- **Gate suite** (`make test` or `./.venv/bin/pytest -q`) — offline, deterministic,
  under 2 seconds. Runs automatically before every commit via the pre-commit
  hook (`make hooks` to (re-)enable it), and in CI on every push/PR.
- **Live checks** (`make test-live` or `./.venv/bin/pytest -m live`) — hit the
  real Sleeper and FantasyCalc APIs. Not run in CI (they need a real league ID
  and a live network). Run them yourself before shipping a change that touches
  `sleeper/`, `values/`, or `projections/`.

Run one test: `./.venv/bin/pytest tests/test_trade.py::test_trade_with_players_and_picks`.

## Before opening a PR

- Every change needs a test in the same PR. A bug fix needs a regression test
  that fails before the fix and passes after.
- Keep changes surgical — touch only what the change requires. Don't refactor
  or reformat unrelated code in the same PR.
- Match the existing style: Python 3.9+ compatible, `from __future__ import
  annotations` for modern type-hint syntax, pydantic models in
  `contracts/models.py` for anything crossing module boundaries.
- `make test` must pass before you push (the pre-commit hook enforces this
  locally; CI enforces it again).

## Architecture

See `CLAUDE.md` for the module layout, the contracts pattern, and the design
decisions behind them (format auto-detection, pick valuation, etc.) before
making structural changes.
