# Specification: Ponytail Audit Defect Fixes & Optimizations

## 1. Overview & Objective
This specification formalizes the fixes, contract anchors, and performance optimizations identified during the codebase audit of `ff`. All changes adhere strictly to the Ponytail philosophy: minimal surgical diffs, standard libraries over abstractions, and deterministic verification.

## 2. Scope of Changes

### 2.1 Value Normalization: Multi-Round Draft Picks (`src/ff/values/normalize.py`)
- **Contract:** `normalize_pick(label: str) -> Optional[str]`
- **Requirements:** Must accurately canonicalize draft pick labels for all rookie draft rounds 1 through 9 (including ordinals `1st` through `9th`, numeric words `first` through `ninth`, and digits `1` through `9`).
- **Signature & Behavior:**
  - Input: `"2026 5th"` -> Returns: `"2026 5"`
  - Input: `"2026 5th round"` -> Returns: `"2026 5"`
  - Input: `"2026 round 5"` -> Returns: `"2026 5"`
  - Input: `"2026 5th (Early)"` -> Returns: `"2026 5 early"`
  - Input: Non-pick or missing year -> Returns `None`

### 2.2 Core Config: Atomic Storage (`src/ff/core/config.py`)
- **Contract:** `save_config(cfg: Config, path: Optional[Path] = None) -> Path`
- **Requirements:** Must write configuration atomically using a PID-tagged temp file and `os.replace` to prevent corrupted/truncated `config.json` on unexpected process termination. Must write with explicit `utf-8` encoding.
- **Contract:** `load_config(path: Optional[Path] = None) -> Config`
- **Requirements:** Must read with explicit `utf-8` encoding.

### 2.3 HTTP Client: SSL Fallback Exception Handling (`src/ff/core/http.py`)
- **Contract:** `get_text(url: str, *, ttl: Optional[float] = 3600.0, timeout: int = DEFAULT_TIMEOUT) -> str`
- **Requirements:** When falling back to `curl` on `SSLError`, any `subprocess.CalledProcessError`, `subprocess.SubprocessError`, or `FileNotFoundError` must be caught and raised as a `requests.exceptions.RequestException` so it is cleanly handled by `_guard` without leaking a raw traceback.

### 2.4 CLI Hardening & Past-Season Resolution (`src/ff/cli.py`)
- **Contract:** `setup()` command: When `--league-id` is provided without `--season`, the season must fall back to `league.get("season")` if present, rather than the current live NFL state.
- **Contract:** `cleanup()` command: Line 956 must fall back safely: `sc.league(cfg.league_id) or {}` to avoid `AttributeError` on empty API responses.

### 2.5 Dead Code Pruning (`src/ff/values/dealer.py`)
- **Contract:** `DynastyDealerClient` remains aliased to `KtcClient` in `src/ff/values/__init__.py`.
- **Requirements:** Deprecate the 98-line `dealer.py` module by replacing it with a minimal compatibility shim delegating to `KtcClient`.

### 2.6 Player Comparison Performance (`src/ff/analysis/compare.py`)
- **Contract:** `comparison_players(query: str, players_meta: Dict[str, Any]) -> List[str]`
- **Requirements:** Tokenize the input query into 1-to-4 word n-grams and match candidate aliases using set intersection against `phrases`, reducing regex operations from ~60,000 to candidate hits only. Must maintain identical span extraction and ambiguity detection.

### 2.7 Waiver Scoring Optimization (`src/ff/analysis/waivers.py`)
- **Contract:** `waiver_targets(...) -> List[WaiverTarget]`
- **Requirements:** Filter out already rostered players (when `free_agents_only=True`) and unrequested positions upfront before instantiating `Asset`, `WaiverTarget`, or calculating `opportunity_score`.

### 2.8 Type Checking Version Target (`pyproject.toml`)
- **Requirements:** Update `python_version = "3.10"` under `[tool.mypy]` to eliminate unsupported Python 3.9 deprecation warnings.
