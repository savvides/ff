# ff draft - live draft board

## Outcome
A `ff draft` command that, run while you're on the clock, prints the live Sleeper
draft state for your configured league: your picks (used + upcoming with gap
sizes), a positional snapshot of your roster (a needs glance), and the best
available players joined to dynasty value. It replaces the ad-hoc Python script
used during the 2026 rookie draft.

Measurable: `ff draft` returns the same pick list and available ranking the
hand-run script produced today (roster 3: used #6/#7/#13, upcoming #25/#29/#35/#37),
with no manual draft-id entry.

## Scope
- Deterministic data only. The "who to take" judgment stays with the LLM. The
  command guarantees correct numbers, the human/LLM makes the call. (CLAUDE.md
  deterministic/latent split.)
- Auto-detect the league's active draft; no draft-id needed in the common case.

## Architecture (existing module boundaries)
- `sleeper/client.py`: I/O only, live (`ttl=0`, board moves):
  `drafts(league_id)`, `draft(draft_id)`, `draft_picks(draft_id)`,
  `draft_traded_picks(draft_id)`.
- `analysis/draft.py`: new, pure:
  - `pick_number(round, slot, teams, *, snake=False, reversal_round=0)`: overall
    pick number. Linear (same order each round), snake (even rounds reverse), and
    3rd-round-reversal (direction flips again from `reversal_round` on) via one
    rule: `forward = round odd; if reversal_round and round >= reversal_round: flip`.
  - `my_picks(roster_id, slot_to_roster, traded_picks, picks_made, *, teams,
    rounds, snake, reversal_round)`: every pick currently owned by `roster_id`
    (made + upcoming), sorted by pick number. Ownership = `slot_to_roster[slot]`
    overridden by `traded_picks` `(round, roster_id) -> owner_id`. `used` is
    count-based (`pick_no <= len(picks_made)`), so it's correct regardless of
    snake numbering; player name/pos enriched from the matching `picks_made` row.
  - `available(book, taken_ids, *, position=None, limit=None)`: delegates to
    `ValueBook.top(exclude=taken_ids)` so `values` and `draft` rank identically.
- `contracts/models.py`: add `DraftPickInfo(pick_no, round, slot, used,
  player_id, player_name, position)`. Reuse `Asset` for available players.
- `cli.py`: `draft` command under `@_guard`. Auto-detect draft, reuse
  `_league_rosters` + `_pick_roster`, compute the taken set (rostered league-wide
  + drafted this draft), value the needs glance through `value_roster`, render
  with rich tables. Flags: `--position/-p`, `--limit` (default 30), `--rookies/-r`
  (filter via players file `years_exp==0`), `--draft-id`. Unsupported draft types
  (auction) and zero-round drafts fail cleanly rather than render a wrong board.

## Tests (gate, offline, deterministic)
`tests/test_draft.py`:
- `pick_number` for linear, snake, and 3rd-round-reversal.
- `my_picks` on today's real scenario (traded-away R1, two acquired R3s) returns
  the exact `[6,7,13,25,29,35,37]` with correct used flags + names.
- `available` excludes taken, sorts by value, honors position filter and limit.
- `SleeperClient` draft methods hit the right URLs (mocked with `responses`).

`tests/test_cli.py`:
- `draft` populates "your picks", proving it fetches full draft detail (the
  `/drafts` list omits `slot_to_roster_id`).

## Out of scope
- Auction drafts (no slot/round pick model): guarded with a clean error.
- An embedded text recommendation (latent, goes to the LLM, not gate-testable).
- Whole-league upcoming-pick board (YAGNI; add if wanted).
