# Contributing to ff

## Setup

```bash
make install     # creates .venv, installs ff + dev deps editable, enables the pre-commit hook
```

Alternative with `uv`: `uv sync --frozen --extra dev && make hooks`.

Manual equivalent: `python3 -m venv .venv && ./.venv/bin/python -m pip install -U pip setuptools wheel && ./.venv/bin/python -m pip install -e ".[dev]" && git config core.hooksPath .githooks`. The pip/setuptools upgrade isn't optional - a stock `venv`'s bundled pip can be too old for a PEP 660 editable install of a `pyproject.toml`-only package.

## Tests

- **Full check** (`make check`) — runs lint (`make lint`), typecheck (`make typecheck`), test (`make test`), and build (`make build`).
- **Gate suite** (`make test` or `uv run pytest -q` or `./.venv/bin/pytest -q`) — offline, deterministic, under 2 seconds. Runs automatically before every commit via the pre-commit hook (`make hooks` to (re-)enable it), and in CI on every push/PR.
- **Live checks** (`make test-live` or `./.venv/bin/pytest -m live`) — hit the real Sleeper, FantasyCalc, DynastyProcess, KeepTradeCut (opt-in), ESPN, and NFL RSS APIs. Not run in CI (they need a real league ID and a live network). Run them yourself before shipping a change that touches `sleeper/`, `values/`, `projections/`, `news/`, or `services/weekly.py`. Set `FF_LIVE_LEAGUE_ID=<a league id you can see>` to also run the traded-picks and draft-shape canaries; without it those two tests skip.
- **Calculator oracle** (Node 18+): `node scripts/calculator_oracle.mjs --check tests/fixtures/calculator_vectors.json` verifies FantasyCalc and KTC live calculator parity against pinned vectors.

Run one test: `./.venv/bin/pytest tests/test_trade.py::test_trade_with_players_and_picks`.

## Before opening a PR

- Every change needs a test in the same PR. A bug fix needs a regression test that fails before the fix and passes after.
- Keep changes surgical — touch only what the change requires. Don't refactor or reformat unrelated code in the same PR.
- Match the existing style: Python 3.9+ compatible, `from __future__ import annotations` for modern type-hint syntax, Pydantic v2 models in `contracts/models.py` for anything crossing module boundaries.
- `make check` (lint, typecheck, offline tests, build) must pass before you push (the pre-commit hook enforces `pytest` locally; CI enforces the full matrix on Python 3.9–3.12).

## Architecture

See [`AGENTS.md`](AGENTS.md) and [`docs/architecture.md`](docs/architecture.md) for the module layout, the contracts pattern, and the design decisions behind them (format auto-detection, pick valuation, weekly fail-closed gates, etc.) before making structural changes.
