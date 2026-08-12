# Natural Language Commands (`ff ask`) Design Document

**Date:** 2026-08-12  
**Status:** Approved  
**Topic:** Natural Language Interface & League Onboarding for `ff`

---

## 1. Overview

`ff` is a command-line tool for managing Sleeper dynasty fantasy football leagues. Currently, users interact with `ff` via structured CLI subcommands (`ff trade`, `ff lineup`, `ff waivers`, etc.).

This feature introduces a natural language interface (`ff ask "<query>"`) and natural language league onboarding. It leverages local terminal AI subscription tools (`agy`, `gemini`, `claude`, `ollama`) to interpret natural language requests, route them to existing deterministic Python analysis functions via tool calling, and return human-friendly plain English explanations backed by rich CLI data.

---

## 2. Goals & Non-Goals

### Goals
* **Natural Language Queries:** Allow users to ask arbitrary plain English questions (`ff ask "Should I trade Gibbs for Bijan?"`).
* **Zero API Key Requirement:** Use the user's active terminal subscription tools (`agy`, `gemini`, `claude`, `ollama`) via subshell execution.
* **100% Deterministic Calculations:** Execute existing Python analysis modules (`analysis.trade`, `analysis.lineup`, `analysis.waivers`, etc.) to get real Sleeper API and FantasyCalc values. No math is guessed or hallucinated by the LLM.
* **Multi-Provider Auto-Detection:** Automatically detect installed terminal binaries in PATH (`agy` → `gemini` → `claude` → `ollama`).
* **Natural Language Onboarding:** Automatically guide un-configured users through setup (`ff ask "connect Sleeper account savvides"`).

### Non-Goals
* Custom remote cloud API keys or billing management inside `ff`.
* Replacing structured CLI subcommands (structured commands like `ff trade` remain fully functional).

---

## 3. Architecture & System Design

```
                     ┌──────────────────────────────────────────────┐
                     │          User (`ff ask "<query>"`)          │
                     └──────────────────────┬───────────────────────┘
                                            │
                                            ▼
                     ┌──────────────────────────────────────────────┐
                     │          Terminal Runner Service             │
                     │  Auto-detects PATH: agy / gemini / claude... │
                     └──────────────────────┬───────────────────────┘
                                            │
                           (1) Query + Tool Schemas
                                            ▼
                     ┌──────────────────────────────────────────────┐
                     │          Tool Dispatcher Engine              │
                     │  Executes pure Python analysis modules       │
                     └──────────────────────┬───────────────────────┘
                                            │
                           (2) Deterministic Data Result
                                            ▼
                     ┌──────────────────────────────────────────────┐
                     │          Terminal Runner Synthesis           │
                     │    Formats plain English + Rich table       │
                     └──────────────────────────────────────────────┘
```

### Module Structure
All LLM integration code lives under `src/ff/services/llm/`:
* `src/ff/services/llm/runner.py`: Subprocess wrapper for `agy`, `gemini`, `claude`, and `ollama` CLI binaries.
* `src/ff/services/llm/tools.py`: Tool definitions & Pydantic schema exports for all `ff` analysis tools.
* `src/ff/services/llm/dispatcher.py`: Maps tool calls to `src/ff/analysis/` and `src/ff/sleeper/` functions.
* `src/ff/services/llm/onboarding.py`: Handles natural language setup and first-run detection.

---

## 4. Tool Registry Specification

| Tool Function | Description | Underlying Python Implementation |
| :--- | :--- | :--- |
| `setup_league(username, league_id)` | Configures Sleeper league & auto-detects format | `sleeper.client.get_user_leagues()` + `detect_format()` |
| `evaluate_trade(give, get)` | Evaluates trade baskets for players & picks | `analysis.trade.evaluate_trade()` |
| `get_lineup(team, week)` | Scores optimal start/sit lineup | `analysis.lineup.optimize_lineup()` |
| `get_waivers(position, limit)` | Ranks trending waiver targets by dynasty value | `analysis.waivers.rank_waivers()` |
| `get_roster(team)` | Prices team roster & positional breakdown | `analysis.roster.price_roster()` |
| `get_power_rankings()` | Ranks league power by dynasty value vs W-L | `sleeper.client.build_rosters()` + valuation |
| `get_picks(team)` | Reconciles future draft capital ownership & tiers | `analysis.picks.pick_ledger()` |
| `get_roster_cleanup(team)` | Finds drop candidates & taxi-stash suggestions | `analysis.cleanup.audit_roster()` |
| `get_movers(mode, min_value)` | Ranks sell-high / buy-low candidates | `analysis.movers.rank_movers()` |
| `get_draft_fit(position, mode)` | Live draft board scored for team fit | `analysis.fit.rank_fits()` |
| `get_dynasty_values(position, limit)` | Returns top format dynasty rankings | `values.client.ValueBook.top()` |

---

## 5. Configuration Updates

Extend `Config` model in `src/ff/core/config.py`:
```python
class Config(BaseModel):
    league_id: str
    season: int
    user_id: Optional[str] = None
    # ... existing fields
    
    # Terminal LLM Settings:
    llm_backend: str = "auto"  # "auto" | "agy" | "gemini" | "claude" | "ollama"
    ollama_model: str = "llama3.2"
```

---

## 6. Error Handling & Fallbacks

1. **No Terminal AI Tool Found:** If `agy`, `gemini`, `claude`, and `ollama` are all missing from PATH, `ff ask` alerts the user with instructions to install one or switch backends via `ff config set-llm`.
2. **Unconfigured League:** If `ff ask` is executed without `.ff/config.json`, it prompts the user for their Sleeper username to run automatic onboarding.
3. **Execution Failure:** If a tool call fails (e.g. invalid player name), `ff ask` catches the error cleanly via `@_guard` and asks the LLM to clarify or retry.

---

## 7. Testing Strategy

* **Unit & Gate Tests:** Offline mock tests in `tests/test_llm.py` testing `TerminalRunner` binary detection, tool schema generation, dispatcher routing, and onboarding flows with mocked subprocess outputs.
* **Live CLI Tests:** Added to `tests/test_live.py` (marked `@pytest.mark.live`) to test real execution against system CLI runners when available.
