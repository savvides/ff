# Specification: Removal of Jev / TypeSafe Integration

## 1. Overview & Objective
Jev was an opt-in, paid hosted AI classification backend powered by TypeSafe (`https://api.typesafe.ai/v1/systemone`). It received natural language questions, classified them into bounded tool operations and arguments using fixed Choice questions, and rendered deterministic Rich tables without conversational prose.

This task removes the entire Jev integration from the codebase to streamline maintenance, eliminate external paid service dependencies, and simplify `ff ask` to use local terminal runners (`agy`, `gemini`, `claude`, `ollama`).

## 2. Scope & Contracts

### 2.1 CLI Interface (`src/ff/cli.py`)
- **Remove Command:** `ff config set-jev-key` is completely removed.
- **Update Command `ff config set-llm <backend>`:**
  - Argument `backend` help updated to: `"LLM backend: auto, agy, gemini, claude, ollama"`.
  - Backend validation accepts only: `SUPPORTED_BACKENDS + ["auto"]` (`['agy', 'gemini', 'claude', 'ollama', 'auto']`).
- **Update Command `ff ask <query>`:**
  - Option `--backend` help updated to: `"Override backend (agy, gemini, claude, ollama)"`.
  - Target backend validation rejects `"jev"` with exit code 1 (`Invalid backend 'jev'. Must be one of: agy, gemini, claude, ollama, auto`).
  - Remove `_ask_jev` execution branch.
- **Preserve Shared UI Rendering:**
  - `_table`, `render_weekly_notes`, `render_comparison`, and `render_weekly_waivers` were previously housed in `src/ff/services/llm/jev_output.py`. Move these 4 UI functions into `src/ff/cli.py` to support `ff compare`, `ff lineup`, and `ff waivers --weekly`.
- **Remove Imports:**
  - Remove imports from `ff.services.llm.jev` and `ff.services.llm.jev_output`.

### 2.2 Core Configuration (`src/ff/core/config.py`)
- **Field `Config.llm_backend`:**
  - Allowed options: `"auto" | "agy" | "gemini" | "claude" | "ollama"`.
  - Default remains `"auto"`.

### 2.3 Dispatcher Cleanup (`src/ff/services/llm/dispatcher.py`)
- Remove stale comment referencing Jev team resolution.

### 2.4 Deleted Source Files
- `src/ff/services/llm/jev.py` (JevClient, ChoiceAnswer, JevResponse, Route, interpret, save_jev_key)
- `src/ff/services/llm/jev_output.py` (render_result)

### 2.5 Deleted Tests
- `tests/test_cli_jev.py`
- `tests/test_jev.py`
- `tests/test_jev_eval.py`

### 2.6 Deleted Scripts & Evals
- `scripts/eval_jev.py`
- `evals/README.md`
- `evals/jev.json`
- `evals/jev-boundaries.json`
- `evals/jev-waivers.json`
- `evals/jev-weekly.json`

### 2.7 Git Configuration (`.gitignore`)
- Remove `typesafe_api_key`.

### 2.8 CLI Regression Tests (`tests/test_cli.py`)
- Add tests verifying:
  - `ff compare <player_a> <player_b>` executes and renders comparisons via local UI helper.
  - `ff waivers --weekly` executes and renders weekly waivers via local UI helper.
  - `ff ask "<query>" --backend jev` is rejected with invalid backend error.
  - `ff config set-llm jev` is rejected with invalid backend error.

### 2.9 Contract & Documentation Updates
- Update `AGENTS.md`, `README.md`, `docs/architecture.md`.
- Update `.ai/specs/api-contracts.json`, `.ai/specs/coding-guardrails.md`, and `.ai/specs/system-architecture.md`.
