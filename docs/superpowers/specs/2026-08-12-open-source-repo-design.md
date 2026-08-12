# Open-sourcing ff

## Outcome

`ff` is ready to publish publicly at `github.com/savvides/ff`: the pitch no
longer positions it against FantasyPros, and the repo has the hygiene a
stranger needs to install, use, and contribute (LICENSE, CONTRIBUTING, CI).

Measurable: no occurrence of "FantasyPros" anywhere in tracked files;
`LICENSE`, `CONTRIBUTING.md`, and `.github/workflows/ci.yml` exist; `make
test` and the new CI workflow both pass; `git ls-files | xargs grep` for the
personal league ID / Sleeper username still returns nothing (already true
today, must stay true).

## Scope

In scope: messaging/positioning rewrite, LICENSE, CONTRIBUTING.md, CI
workflow, README badges. No behavior changes, no renaming, no restructuring
of `src/ff/`. Not in scope: PyPI packaging, changelog, issue/PR templates,
code of conduct — none were requested and the repo doesn't need them to be
usable by another dynasty manager.

## 1. Positioning rewrite

Replace the "free FantasyPros replacement" framing with capability + why-a-CLI,
everywhere it appears:

- **`README.md`** — new title and intro lead with what the tool does (Sleeper
  dynasty league management: rankings, trade analyzer, roster valuation, power
  rankings, lineup optimizer, waiver targets, live draft board), backed by
  free Sleeper + FantasyCalc APIs. Replace the "Why this exists" section (the
  FantasyPros pricing table) with a "Why a CLI" section: fast (no page loads,
  cached), scriptable (pipe/cron/wire into other tools), yours (runs locally,
  public data only, no account or tracking), hackable (typed contracts, small
  modules, easy to extend for another league's quirks). Quickstart, Commands,
  Development, and Limits sections are unchanged — none of them mention
  FantasyPros today. Add a CI badge and MIT license badge under the title.
- **`pyproject.toml`** — reword `description`; add `authors = [{name =
  "Philippos Savvides"}]`.
- **`src/ff/__init__.py`** — reword the module docstring's second line ("A
  FantasyPros replacement built on two free, auth-free sources:") to drop the
  comparison, keep the two-bullet source list as-is.
- **`src/ff/cli.py`** — reword the `ff values` line in the module docstring to
  drop the "(FantasyPros killer)" aside; state what it does instead.
- **`src/ff/analysis/trade.py`** — reword the module docstring's second line
  ("This is the headline FantasyPros replacement: ...") to describe the
  trade analyzer directly.
- **`CLAUDE.md`** — reword line 7 ("as a replacement for a paid FantasyPros
  subscription") to a standalone description of what `ff` is. No other line
  in this file mentions FantasyPros; everything else is untouched.

No other files reference FantasyPros (confirmed by repo-wide grep).

## 2. LICENSE

Standard MIT license text. Copyright Philippos Savvides, 2026. Makes real the
claim `pyproject.toml` already makes (`license = { text = "MIT" }`).

## 3. CONTRIBUTING.md

Surfaces what `CLAUDE.md` already documents, for people who won't read that
file:

- Dev setup: `make install` (venv, editable install, pre-commit hook).
- Two test lanes: gate suite (`make test`, offline/deterministic/<2s, runs on
  every commit via the pre-commit hook) vs. live checks (`make test-live`,
  hits real Sleeper + FantasyCalc APIs, run before shipping — not part of CI
  since it needs a real league ID).
- PR expectations: tests in the diff, surgical changes (touch only what the
  change requires), match existing style, Python 3.9+ compatible (`from
  __future__ import annotations` for modern type hints).

## 4. CI workflow

`.github/workflows/ci.yml`: on push and pull_request, matrix Python
3.9/3.10/3.11/3.12, steps = checkout, setup-python, `pip install -e ".[dev]"`,
`make test`. Gate suite only — deliberately excludes live tests (they need a
real Sleeper league ID and hit external APIs, which is wrong for CI).

## Testing

This is a docs/config change, not application logic — no new unit tests
apply. Verification is: `make test` still passes (gate suite untouched by
these edits), the new CI workflow runs green on a pushed branch, and the
FantasyPros/personal-data greps above return nothing.
