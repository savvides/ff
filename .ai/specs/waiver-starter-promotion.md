# Specification: Waiver Starter Promotion & Fresh Depth Chart Data

## 1. Overview & Objective
When an NFL starting quarterback suffers an injury resulting in an Out/IR designation, their direct backup inherits starting duties. In a Superflex dynasty league, any starting NFL QB immediately commands starting-tier dynasty capital (typically 1,700–2,000+ points). However, third-party dynasty valuation books (e.g. FantasyCalc) lag behind breaking NFL news, leaving newly promoted starting QBs anchored to their backup prices (e.g. Kyle McCord at 640).

Furthermore, Sleeper's raw players dictionary has a default cache TTL of 24 hours (`PLAYERS_TTL = 24 * 3600`). If depth charts or injury statuses update mid-week, `ff waivers` can evaluate stale data unless a fresh snapshot is requested.

This specification formalizes:
1. Fresh player metadata retrieval in `SleeperClient.players()`.
2. Dynamic Superflex starting QB floor derived from the league's `ValueBook` for backups promoted due to starter Out/IR status.
3. Pure function integration in `src/ff/analysis/depth.py` and `src/ff/analysis/waivers.py`.
4. CLI wiring in `src/ff/cli.py`.

## 2. Scope & Contracts

### 2.1 Sleeper Client Fresh Players (`src/ff/sleeper/client.py`)
- **Contract:** `players(self, sport: str = "nfl", *, fresh: bool = False) -> Dict[str, Any]`
- **Requirements:**
  - When `fresh=False` (default), use standard `ttl=PLAYERS_TTL`.
  - When `fresh=True`, use `ttl=0` to bypass cache and fetch current player depth charts and injury designations.

### 2.2 Dynamic Superflex Starter Floor (`src/ff/analysis/waivers.py`)
- **Contract:** `waiver_targets(...)`
- **Requirements:**
  - When `is_superflex=True` and `book` contains valued QBs, compute the baseline starter floor dynamically as the value of the 32nd ranked QB (`qb_values[31]` when `len(qb_values) >= 32`, else minimum 1500).
  - Pass this computed floor into `opportunity_score(..., superflex_starter_floor=floor)`.

### 2.3 Promoted Backup Floor Application (`src/ff/analysis/depth.py`)
- **Contract:** `opportunity_score(..., superflex_starter_floor: Optional[int] = None)`
- **Requirements:**
  - If `is_superflex` is True, `pos == "QB"`, `depth_chart_order == 2` (including precomputed QB2 promotions), and `starter_injury` contains `"out"` or `"ir"` (including `"injured reserve"`, `"pup"`, `"dnr"`):
    - `mult = min(1.0, mult + 0.25)` (existing behavior).
    - `base = max(base, superflex_starter_floor if superflex_starter_floor is not None else 1500)`.
  - Inactive starters or co-listed order 1 QBs (such as Joe Fagnano) do not trigger this condition.
  - Existing starters (order == 1, e.g. Carson Wentz) retain their market valuation and do not receive an artificial bump.

### 2.4 CLI Refresh Wiring (`src/ff/cli.py`)
- **Contract:** `waivers(...)` command
- **Requirements:**
  - Invoke `sc.players(fresh=True)` so waiver rankings evaluate current depth charts and injury tags.
  - Pass the resulting fresh `players_meta` to `waiver_targets` and `run_qa`.
