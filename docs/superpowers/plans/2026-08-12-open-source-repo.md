# Open-Sourcing ff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `ff` publishable at `github.com/savvides/ff` — drop the FantasyPros-comparison framing everywhere it appears, and add the repo hygiene (LICENSE, CONTRIBUTING.md, CI) a stranger needs to install, use, and contribute.

**Architecture:** Pure docs/config change. No source logic changes — every edit is a docstring reword, a new standalone file, or a README section swap. No new dependencies, no new modules.

**Tech Stack:** Existing: Python 3.9+, pytest, GitHub Actions (new).

## Global Constraints

- No occurrence of the string "FantasyPros" may remain in any tracked file when this plan is done.
- No behavior change to any function, CLI command, or test. `make test` (the gate suite) must pass unchanged after every source-touching task.
- Copyright/author name is exactly `Philippos Savvides`. Repo location is the existing `git remote` (`github.com/savvides/ff`) — do not add or change remotes.
- CI runs the gate suite only (`pytest -q`, which defaults to `-m "not live"` per `pyproject.toml`). Never add live tests to CI — they need a real Sleeper league ID and hit external APIs.
- Every new/edited file matches the tone of the existing docs: terse, factual, no marketing language beyond what's specified below verbatim.

---

### Task 1: Add LICENSE

**Files:**
- Create: `LICENSE`

**Interfaces:** None — standalone file, no code dependency.

- [ ] **Step 1: Write the LICENSE file**

Create `LICENSE` with exactly this content (standard MIT license text, matching the `license = { text = "MIT" }` already declared in `pyproject.toml`):

```
MIT License

Copyright (c) 2026 Philippos Savvides

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

- [ ] **Step 2: Verify**

Run: `test -f LICENSE && head -1 LICENSE`
Expected: `MIT License`

- [ ] **Step 3: Commit**

```bash
git add LICENSE
git commit -m "Add MIT LICENSE file"
```

---

### Task 2: Add CONTRIBUTING.md

**Files:**
- Create: `CONTRIBUTING.md`

**Interfaces:** None — references existing `make install`/`make test`/`make test-live` targets and `CLAUDE.md`, all of which already exist unchanged.

- [ ] **Step 1: Write CONTRIBUTING.md**

Create `CONTRIBUTING.md` with exactly this content:

```markdown
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
```

- [ ] **Step 2: Verify**

Run: `test -f CONTRIBUTING.md && grep -c "Gate suite" CONTRIBUTING.md`
Expected: `1`

- [ ] **Step 3: Commit**

```bash
git add CONTRIBUTING.md
git commit -m "Add CONTRIBUTING.md"
```

---

### Task 3: Add CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:** Consumes `pyproject.toml`'s `[project.optional-dependencies].dev` extra and the default pytest `addopts` (`-m 'not live'`) already set in `pyproject.toml` — no changes needed there for this task to work.

- [ ] **Step 1: Write the CI workflow**

Create `.github/workflows/ci.yml` with exactly this content:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.9", "3.10", "3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pip install -e ".[dev]"
      - run: pytest -q
```

- [ ] **Step 2: Verify YAML is well-formed**

Run: `./.venv/bin/python -c "import yaml, sys; yaml.safe_load(open('.github/workflows/ci.yml'))" 2>&1 || python3 -c "import yaml, sys; yaml.safe_load(open('.github/workflows/ci.yml'))"`
Expected: no output, exit code 0. (If neither Python has `pyyaml` installed, instead run `python3 -c "import json; print('skip, no yaml module')"` and visually confirm indentation is consistent 2-space YAML — do not skip validation silently, note in the commit message body if you fell back to visual check.)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "Add GitHub Actions CI running the gate test suite"
```

---

### Task 4: Update pyproject.toml metadata

**Files:**
- Modify: `pyproject.toml:8` (description line) and the line immediately after it (new authors field)

**Interfaces:** None — metadata only, no import-time effect.

- [ ] **Step 1: Edit the description and add authors**

In `pyproject.toml`, find:

```toml
name = "ff"
version = "0.1.0"
description = "Manage a Sleeper dynasty fantasy football league with free data - a FantasyPros replacement."
readme = "README.md"
```

Replace with:

```toml
name = "ff"
version = "0.1.0"
description = "Command-line tool for managing a Sleeper dynasty fantasy football league: rosters, trade values, lineup optimizer, draft board, and waivers."
authors = [{ name = "Philippos Savvides" }]
readme = "README.md"
```

- [ ] **Step 2: Verify the package still installs and the CLI still resolves**

Run: `./.venv/bin/python -m pip install -e . -q && ./.venv/bin/ff --help | head -1`
Expected: exits 0, prints the Typer help header (no error about malformed `pyproject.toml`).

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "Reword package description, add authors field"
```

---

### Task 5: Remove FantasyPros framing from source docstrings and CLAUDE.md

**Files:**
- Modify: `src/ff/__init__.py:3`
- Modify: `src/ff/cli.py:7`
- Modify: `src/ff/analysis/trade.py:1-4`
- Modify: `CLAUDE.md:7`

**Interfaces:** None — docstring/comment text only, no code, no signatures change.

- [ ] **Step 1: Edit `src/ff/__init__.py`**

Find:

```python
"""ff - manage a Sleeper dynasty league with free data.

A FantasyPros replacement built on two free, auth-free sources:
  * Sleeper API      - your league, rosters, matchups, transactions, trending.
```

Replace with:

```python
"""ff - manage a Sleeper dynasty league with free data.

Built on two free, auth-free sources:
  * Sleeper API      - your league, rosters, matchups, transactions, trending.
```

- [ ] **Step 2: Edit `src/ff/cli.py`**

Find:

```python
    ff values [-p WR]       dynasty rankings for your format (FantasyPros killer)
```

Replace with:

```python
    ff values [-p WR]       dynasty rankings for your league format
```

- [ ] **Step 3: Edit `src/ff/analysis/trade.py`**

Find:

```python
"""The trade analyzer - value both baskets (players + picks) and judge fairness.

This is the headline FantasyPros replacement: name the assets on each side and
get totals, the gap as a %, who wins, and a positional breakdown.
"""
```

Replace with:

```python
"""The trade analyzer - value both baskets (players + picks) and judge fairness.

Name the assets on each side and get totals, the gap as a %, who wins, and a
positional breakdown.
"""
```

- [ ] **Step 4: Edit `CLAUDE.md`**

Find:

```
ff is a command-line tool to manage a Sleeper dynasty fantasy football league using only free data, as a replacement for a paid FantasyPros subscription. It joins two free, auth-free, read-only APIs:
```

Replace with:

```
ff is a command-line tool to manage a Sleeper dynasty fantasy football league using only free data. It joins two free, auth-free, read-only APIs:
```

- [ ] **Step 5: Verify no FantasyPros mentions remain in these four files, and the gate suite still passes**

Run: `grep -ri fantasypros src/ff/__init__.py src/ff/cli.py src/ff/analysis/trade.py CLAUDE.md; echo "grep exit: $?"`
Expected: no matching lines printed, `grep exit: 1` (grep's no-match exit code).

Run: `make test`
Expected: full pass, same test count as before this task (these are docstring-only edits, so no test should be affected).

- [ ] **Step 6: Commit**

```bash
git add src/ff/__init__.py src/ff/cli.py src/ff/analysis/trade.py CLAUDE.md
git commit -m "Drop FantasyPros framing from docstrings and CLAUDE.md"
```

---

### Task 6: Rewrite README.md positioning + add badges, Contributing/License sections

**Files:**
- Modify: `README.md:1-28` (title through end of the data-sources bullets)
- Modify: `README.md` end (append Contributing + License sections after the existing "Limits (by design)" section)

**Interfaces:** None — `README.md` is documentation only, not imported by any code or test.

- [ ] **Step 1: Replace the title, intro, and "Why this exists" section**

Find (the first 28 lines of `README.md`, from the title through the end of the data-sources bullets):

```markdown
# ff - manage a Sleeper dynasty league without paying FantasyPros

`ff` pulls your Sleeper dynasty league and overlays free dynasty trade values so
you get the things you were paying FantasyPros for - rankings, a trade analyzer,
roster valuation, power rankings, and waiver targets - from the command line.

## Why this exists

FantasyPros' dynasty tools sit behind the MVP/HOF tiers (~$72-108/yr). Almost
everything they give a dynasty manager is available free:

| What you used FantasyPros for | Free replacement here |
| --- | --- |
| Dynasty rankings | `ff values` - FantasyCalc values for *your* format |
| Trade Analyzer (players + picks) | `ff trade --give … --get …` |
| Start/sit & lineup optimizer | `ff lineup` - best lineup by your exact scoring (incl TEP) |
| Roster / team value | `ff roster` (rostered players; picks are valued in `trade`) |
| League power rankings | `ff power` |
| Buy-low / sell-high | `ff movers [--buy]` - dynasty vs win-now value gap |
| Waiver suggestions | `ff waivers` - trending adds joined to value |

**Data sources (all free, no account, read-only):**
- [Sleeper API](https://docs.sleeper.com/) - your league, rosters, matchups,
  transactions, trending adds.
- Sleeper projections (`api.sleeper.com`) - weekly projected stat lines
  (RotoWire), scored by your league's own rules for the lineup optimizer.
- [FantasyCalc API](https://fantasycalc.com/) - dynasty values for players **and
  draft picks**, tagged with `sleeperId` so they join straight onto your roster.
```

Replace with:

```markdown
# ff

[![CI](https://github.com/savvides/ff/actions/workflows/ci.yml/badge.svg)](https://github.com/savvides/ff/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A command-line tool for managing a Sleeper dynasty fantasy football league -
rankings, trade analyzer, roster valuation, power rankings, lineup optimizer,
waiver targets, live draft board.

## Why a CLI

- **Fast** - no page loads, no ads, answers in milliseconds from cache.
- **Scriptable** - pipe it, cron it, wire it into your own tools.
- **Yours** - runs locally, reads only public league data, no account or
  tracking.
- **Hackable** - pure Python, small, typed contracts between modules, easy to
  extend for your own league's quirks.

**Data sources (all free, no account, read-only):**
- [Sleeper API](https://docs.sleeper.com/) - your league, rosters, matchups,
  transactions, trending adds.
- Sleeper projections (`api.sleeper.com`) - weekly projected stat lines
  (RotoWire), scored by your league's own rules for the lineup optimizer.
- [FantasyCalc API](https://fantasycalc.com/) - dynasty values for players **and
  draft picks**, tagged with `sleeperId` so they join straight onto your roster.
```

- [ ] **Step 2: Append Contributing and License sections**

Find the last lines of `README.md` (the end of the "Limits (by design)" section):

```markdown
- **No trade *finder* and no tiers/VORP yet.** `trade` evaluates a deal you
  specify; it does not scan the league to propose one. Rankings are raw value,
  without tier breaks or value-over-replacement.
```

Replace with (same text, plus two new sections appended after it):

```markdown
- **No trade *finder* and no tiers/VORP yet.** `trade` evaluates a deal you
  specify; it does not scan the league to propose one. Rankings are raw value,
  without tier breaks or value-over-replacement.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, the test lanes, and PR
expectations.

## License

MIT - see [LICENSE](LICENSE).
```

- [ ] **Step 3: Verify no FantasyPros mentions remain and the file is well-formed markdown**

Run: `grep -ci fantasypros README.md; echo "exit: $?"`
Expected: `0` printed (zero matches), `exit: 1`.

Run: `wc -l README.md`
Expected: a line count a few lines higher than the original 89 (badges + Why-a-CLI bullets add lines at the top, Contributing/License sections add lines at the bottom) - sanity check only, no exact number required.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "Rewrite README positioning: drop FantasyPros framing, add Contributing/License sections"
```

---

### Task 7: Final repo-wide verification

**Files:** None modified — this task only verifies the prior six.

**Interfaces:** None.

- [ ] **Step 1: Confirm no FantasyPros mentions remain anywhere in tracked files**

Run: `git ls-files | xargs grep -li fantasypros; echo "exit: $?"`
Expected: no filenames printed, `exit: 1`.

- [ ] **Step 2: Confirm no personal data leaked (regression check on a property that was already true before this plan)**

Run: `git ls-files | xargs grep -lI "1366910390553804800\|philippos\|savvides" 2>/dev/null; echo "exit: $?"`
Expected: no filenames printed, `exit: 1`. (Note: `savvides` will now legitimately appear in `LICENSE`, `pyproject.toml`'s `authors`, and `CONTRIBUTING.md`/`README.md` if you named the author there — if this check now fails only because of the LICENSE/authors name, that's expected and fine; re-run excluding those three files to confirm no *other* file regressed: `git ls-files | grep -v -e LICENSE -e pyproject.toml | xargs grep -lI "1366910390553804800\|philippos" 2>/dev/null; echo "exit: $?"` should print nothing, `exit: 1`.)

- [ ] **Step 3: Confirm the gate suite and package metadata are healthy end to end**

Run: `make test`
Expected: full pass (same as before this plan started - these were docs/config-only changes).

Run: `./.venv/bin/python -m pip install -e . -q && ./.venv/bin/ff --help | head -1`
Expected: exits 0.

- [ ] **Step 4: Confirm all new files exist**

Run: `test -f LICENSE && test -f CONTRIBUTING.md && test -f .github/workflows/ci.yml && echo "all present"`
Expected: `all present`.

- [ ] **Step 5: Push and confirm CI goes green**

```bash
git push
```

Then check the Actions tab (or `gh run watch` if the `gh` CLI is authenticated) for the just-pushed commit's CI run. Expected: green across all four Python versions in the matrix.

No commit for this task - it is verification-only. If any check fails, return to the task that owns the broken file, fix it there, and re-run this task's checks before pushing.
