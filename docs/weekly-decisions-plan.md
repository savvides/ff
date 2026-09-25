# Weekly decisions implementation plan

The user-visible outcome is advice for the remaining playable portion of the
current week: respect existing locked starters, show fresh availability and
conditional replacements, compare two named rostered players, and rank unrostered
players by improvement to this team's lineup. All advice remains read-only.

## 1. Timing and availability

- Preserve empty starter slots and fetch fresh rosters/matchups for weekly advice.
- Join Sleeper's season schedule (team, week, status) to ESPN's weekly scoreboard
  (UTC kickoff and status). Validate season/week and team pairs. Both public feeds
  are undocumented; malformed, missing or conflicting records must not create
  confident legal recommendations.
- Refresh individual Sleeper player records rather than repeatedly downloading
  the daily players dictionary. Show retrieval time, injury designation and linked,
  dated reporting for uncertain players. Reports are context, not invented injury
  probabilities. Definite out/IR/suspended/PUP players cannot enter movable slots.
- Keep locked starters in their exact slots, disallow started bench players,
  preserve actual zero/negative scores, and separate live actuals from remaining
  projections. Do not add a full-game projection to live actual points.
- Prefer later players in flexible slots when the selected lineup score is equal.
- Unknown timing freezes affected existing assignments; unsupported slots,
  AutoSubs, best-ball or invalid roster settings prevent actionable advice.
- Verification: frozen-clock tests before/at/after kickoff, empty slots, completed
  and live games, missing/conflicting/postponed feeds, injury changes and fallback
  deadlines; mocked HTTP and one real league read-through.

## 2. Named-player start/sit

- Add `ff compare PLAYER_A PLAYER_B` for the current week and a bounded Jev route.
- Resolve names/aliases locally to unique rostered Sleeper IDs; ambiguous and
  missing names clarify. Do not silently choose a fuzzy match.
- Compare the best whole lineup with each player starting and the other sitting;
  explain when both fit, neither is legal, or a lock makes the choice unavailable.
- Show per-player points/status and whole-lineup difference with injury conditions.
- Verification: ID/name ambiguity, ownership, positional eligibility, locks,
  both-fit cases, league scoring and unchanged roster control in live Jev evals.

## 3. Weekly waiver improvement

- Add explicit `ff waivers --weekly` and a Jev weekly-waiver operation. Preserve
  existing dynasty ranking for requests without a weekly objective.
- Evaluate all projected unrostered league-eligible candidates before truncation,
  using the same timing/availability constraints and whole-lineup scoring.
- Report lineup gain and displaced starter. This is conditional on acquisition;
  pending claims, waiver clearance, FAAB and drop selection are not inferred.
- Verification: candidates outside trending, filter-before-limit, no owned/locked/
  unavailable candidates, zero-gain depth, missing projections and direct/Jev parity.

## Release gate

Run the relevant tests per stage, then `make check`, live API checks, all affected
Jev regression sets and a dedicated weekly-decision set. Keep the original
confidence floor, abstention requirements and `Show my roster` control. Inspect
real CLI output, commit only this task's files, push and update PR #35, inspect the
actual PR diff and CI. Do not merge. Preserve the pre-existing uncommitted
`CLAUDE.md` edit.

Source checks (2026-09-25): Sleeper individual player and player-news endpoints,
season schedule and weekly matchups returned live records. Sleeper schedule has
dates but no kickoff times; ESPN scoreboard supplies timezone-aware timestamps.
Sleeper support confirms AutoSub pairings lock when either player starts:
https://support.sleeper.com/en/articles/9731991-how-does-player-autosubs-work


## Completion evidence

- Timing/availability: `tests/test_weekly.py` and `tests/test_weekly_sources.py`
  cover the frozen clock, exact slots, actual zero/negative points, source mismatch,
  injury states, missing projections and earlier replacement deadlines. Exhaustive
  legal-lineup enumeration independently checks constrained optimization.
- Comparisons: `tests/test_compare.py` checks unique names/IDs, ambiguity, ownership,
  whole-lineup differences, both-fit choices and locked alternatives.
- Weekly waivers: `tests/test_weekly_waivers.py` checks the full pool, ownership,
  position-before-limit, injured/started/unknown exclusions, depth-only zero gain,
  explicit trending and locked incumbents.
- `tests/test_cli_jev.py` checks real interpretation/dispatch/render wiring against
  offline HTTP and direct-command parity under strict QA. Live CLI checks confirm
  the corresponding journeys against the configured league.
- Routing results and known clarification limits are recorded in
  [evals/README.md](../evals/README.md). All gates passed without lowering thresholds.
- Public data cannot verify AutoSub pairings or instant acquisition eligibility.
  Those cases explicitly refuse advice or require checking Sleeper, respectively.
  Availability uses fresh Sleeper designations and dated source-linked reporting;
  no independent official-report scraper or speculative injury model is introduced.
