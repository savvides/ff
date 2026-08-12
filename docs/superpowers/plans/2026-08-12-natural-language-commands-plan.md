# Natural Language Commands (`ff ask`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a natural language command interface (`ff ask "<query>"`) and interactive league onboarding using zero-API-key terminal subscription runners (`agy`, `gemini`, `claude`, `ollama`) and deterministic Python tool dispatcher execution.

**Architecture:** A new `src/ff/services/llm/` module containing `runner.py` (subprocess wrapper for system AI binaries), `tools.py` (tool definitions for all analysis modules), `dispatcher.py` (tool execution router), and `onboarding.py` (league setup helper). The `ask` subcommand in `src/ff/cli.py` orchestrates the tool-calling loop, data dispatching, and rich response formatting.

**Tech Stack:** Python 3.9+, Typer, Pydantic, Rich, `subprocess`, `shutil`, Pytest.

## Global Constraints

- Target Python 3.9 using `from __future__ import annotations`.
- Strict typing and Pydantic contracts maintained across module boundaries.
- Gate tests must remain offline, deterministic, and fast (`< 2s`).
- Zero required remote API keys; auto-detects `agy`, `gemini`, `claude`, or `ollama` binaries in PATH.

---

### Task 1: Config Model Extension

**Files:**
- Modify: `src/ff/core/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: Existing `Config` model in `src/ff/core/config.py`
- Produces: `Config` model with `llm_backend` ("auto"|"agy"|"gemini"|"claude"|"ollama") and `ollama_model` ("llama3.2") fields.

- [ ] **Step 1: Write the failing test**

Edit `tests/test_config.py` to add `test_llm_config_defaults`:
```python
def test_llm_config_defaults(tmp_path: pytest.TempPathFactory) -> None:
    from ff.core.config import Config, save_config, load_config
    cfg = Config(league_id="123456", season=2026, llm_backend="gemini")
    assert cfg.llm_backend == "gemini"
    assert cfg.ollama_model == "llama3.2"
    
    cfg_file = tmp_path / "config.json"
    save_config(cfg, path=cfg_file)
    loaded = load_config(path=cfg_file)
    assert loaded.llm_backend == "gemini"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_config.py::test_llm_config_defaults -v`
Expected: FAIL with `ValidationError` (unexpected field `llm_backend`).

- [ ] **Step 3: Write minimal implementation**

Update `src/ff/core/config.py`:
```python
class Config(BaseModel):
    league_id: str
    season: int
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    league_name: Optional[str] = None
    format: Format
    # LLM Terminal Runner settings
    llm_backend: str = "auto"  # "auto" | "agy" | "gemini" | "claude" | "ollama"
    ollama_model: str = "llama3.2"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ff/core/config.py tests/test_config.py
git commit -m "feat(config): add llm_backend and ollama_model settings to Config schema"
```

---

### Task 2: Terminal Subprocess Runner

**Files:**
- Create: `src/ff/services/__init__.py`
- Create: `src/ff/services/llm/__init__.py`
- Create: `src/ff/services/llm/runner.py`
- Test: `tests/test_runner.py`

**Interfaces:**
- Consumes: System `shutil.which` and `subprocess.run`
- Produces: `TerminalRunner` class with `run(prompt: str, system_prompt: str) -> str` and `detect_backend() -> str`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_runner.py`:
```python
import subprocess
from unittest.mock import patch
import pytest

def test_runner_auto_detect_agy() -> None:
    from ff.services.llm.runner import TerminalRunner
    with patch("shutil.which", side_effect=lambda bin_name: "/usr/bin/agy" if bin_name == "agy" else None):
        runner = TerminalRunner(backend="auto")
        assert runner.backend == "agy"

def test_runner_executes_subprocess() -> None:
    from ff.services.llm.runner import TerminalRunner
    runner = TerminalRunner(backend="agy")
    completed = subprocess.CompletedProcess(args=["agy"], returncode=0, stdout="Answer text", stderr="")
    with patch("subprocess.run", return_value=completed) as mock_run:
        res = runner.run(prompt="Hello", system_prompt="You are an assistant.")
        assert res == "Answer text"
        assert mock_run.called
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_runner.py -v`
Expected: FAIL (ModuleNotFoundError: No module named 'ff.services').

- [ ] **Step 3: Write minimal implementation**

Create `src/ff/services/__init__.py` and `src/ff/services/llm/__init__.py`.
Create `src/ff/services/llm/runner.py`:
```python
from __future__ import annotations

import shutil
import subprocess
from typing import Optional

SUPPORTED_BACKENDS = ["agy", "gemini", "claude", "ollama"]

class TerminalRunner:
    def __init__(self, backend: str = "auto", ollama_model: str = "llama3.2") -> None:
        self.ollama_model = ollama_model
        self.backend = self._resolve_backend(backend)

    def _resolve_backend(self, backend: str) -> str:
        if backend in SUPPORTED_BACKENDS:
            return backend
        for b in SUPPORTED_BACKENDS:
            if shutil.which(b):
                return b
        return "none"

    def run(self, prompt: str, system_prompt: str = "") -> str:
        if self.backend == "none":
            raise RuntimeError("No supported terminal AI runner (agy, gemini, claude, ollama) found in PATH.")

        full_prompt = f"System: {system_prompt}\nUser: {prompt}" if system_prompt else prompt

        if self.backend == "agy":
            cmd = ["agy", "exec", full_prompt]
        elif self.backend == "gemini":
            cmd = ["gemini", "ask", full_prompt]
        elif self.backend == "claude":
            cmd = ["claude", "-p", full_prompt]
        elif self.backend == "ollama":
            cmd = ["ollama", "run", self.ollama_model, full_prompt]
        else:
            raise ValueError(f"Unknown backend: {self.backend}")

        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return res.stdout.strip()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_runner.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ff/services/ tests/test_runner.py
git commit -m "feat(llm): implement TerminalRunner for system AI binaries"
```

---

### Task 3: Tool Registry and Dispatcher Engine

**Files:**
- Create: `src/ff/services/llm/tools.py`
- Create: `src/ff/services/llm/dispatcher.py`
- Test: `tests/test_dispatcher.py`

**Interfaces:**
- Consumes: Pure functions from `src/ff/analysis/` (`trade`, `lineup`, `waivers`, `roster`, `movers`, `cleanup`, `picks`, `fit`) and `src/ff/sleeper/client.py`.
- Produces: `TOOL_SCHEMAS` list and `dispatch_tool(tool_name: str, kwargs: dict, ctx: dict) -> dict`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_dispatcher.py`:
```python
from unittest.mock import MagicMock, patch
import pytest

def test_tool_schemas_registered() -> None:
    from ff.services.llm.tools import TOOL_SCHEMAS
    tool_names = [t["name"] for t in TOOL_SCHEMAS]
    assert "evaluate_trade" in tool_names
    assert "get_lineup" in tool_names
    assert "get_waivers" in tool_names

def test_dispatch_evaluate_trade() -> None:
    from ff.services.llm.dispatcher import dispatch_tool
    mock_eval = MagicMock()
    mock_eval.model_dump.return_value = {"give_total": 5000, "get_total": 5500}
    with patch("ff.analysis.trade.evaluate_trade", return_value=mock_eval):
        res = dispatch_tool("evaluate_trade", {"give": ["Gibbs"], "get": ["Bijan"]}, ctx={})
        assert res == {"give_total": 5000, "get_total": 5500}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_dispatcher.py -v`
Expected: FAIL (ModuleNotFoundError: No module named 'ff.services.llm.tools').

- [ ] **Step 3: Write minimal implementation**

Create `src/ff/services/llm/tools.py`:
```python
from __future__ import annotations

TOOL_SCHEMAS = [
    {
        "name": "setup_league",
        "description": "Onboard or set up Sleeper league by username.",
        "parameters": {
            "type": "object",
            "properties": {
                "username": {"type": "string", "description": "Sleeper username"}
            },
            "required": ["username"]
        }
    },
    {
        "name": "evaluate_trade",
        "description": "Evaluate trade fairness between given assets and received assets.",
        "parameters": {
            "type": "object",
            "properties": {
                "give": {"type": "array", "items": {"type": "string"}},
                "get": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["give", "get"]
        }
    },
    {
        "name": "get_lineup",
        "description": "Get optimal starting lineup for a team/week.",
        "parameters": {
            "type": "object",
            "properties": {
                "team": {"type": "string"},
                "week": {"type": "integer"}
            }
        }
    },
    {
        "name": "get_waivers",
        "description": "Get top waiver targets ranked by dynasty value.",
        "parameters": {
            "type": "object",
            "properties": {
                "position": {"type": "string"},
                "limit": {"type": "integer"}
            }
        }
    },
    {
        "name": "get_roster",
        "description": "Get roster breakdown and dynasty valuation.",
        "parameters": {
            "type": "object",
            "properties": {
                "team": {"type": "string"}
            }
        }
    }
]
```

Create `src/ff/services/llm/dispatcher.py`:
```python
from __future__ import annotations

from typing import Any, Dict
from ff.analysis import trade, lineup, waivers, roster

def dispatch_tool(tool_name: str, kwargs: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    if tool_name == "evaluate_trade":
        value_book = ctx.get("value_book")
        res = trade.evaluate_trade(
            give_inputs=kwargs.get("give", []),
            get_inputs=kwargs.get("get", []),
            book=value_book
        )
        return res.model_dump() if hasattr(res, "model_dump") else res

    raise ValueError(f"Unknown tool: {tool_name}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_dispatcher.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ff/services/llm/tools.py src/ff/services/llm/dispatcher.py tests/test_dispatcher.py
git commit -m "feat(llm): create tool schema registry and dispatcher engine"
```

---

### Task 4: Natural Language Onboarding Service

**Files:**
- Create: `src/ff/services/llm/onboarding.py`
- Test: `tests/test_onboarding.py`

**Interfaces:**
- Consumes: `sleeper.client.get_user_leagues()` and `sleeper.client.detect_format()`
- Produces: `onboard_user(username: str, path: Optional[Path]) -> Config`

- [ ] **Step 1: Write the failing test**

Create `tests/test_onboarding.py`:
```python
from unittest.mock import MagicMock, patch
import pytest

def test_onboard_user_creates_config(tmp_path: pytest.TempPathFactory) -> None:
    from ff.services.llm.onboarding import onboard_user
    mock_leagues = [{"league_id": "999", "name": "My Dynasty", "season": "2026"}]
    mock_format = MagicMock(is_superflex=True, ppr=1.0)
    
    with patch("ff.sleeper.client.get_user_leagues", return_value=mock_leagues), \
         patch("ff.sleeper.client.detect_format", return_value=mock_format):
        cfg_file = tmp_path / "config.json"
        cfg = onboard_user(username="philippos", config_path=cfg_file)
        assert cfg.league_id == "999"
        assert cfg.user_name == "philippos"
        assert cfg_file.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_onboarding.py -v`
Expected: FAIL (ModuleNotFoundError: No module named 'ff.services.llm.onboarding').

- [ ] **Step 3: Write minimal implementation**

Create `src/ff/services/llm/onboarding.py`:
```python
from __future__ import annotations

from pathlib import Path
from typing import Optional
from ff.core.config import Config, save_config
from ff.sleeper import client as sleeper_client

def onboard_user(username: str, config_path: Optional[Path] = None) -> Config:
    user = sleeper_client.get_user(username)
    leagues = sleeper_client.get_user_leagues(user["user_id"])
    if not leagues:
        raise ValueError(f"No active leagues found for user '{username}'.")
    
    league = leagues[0]  # Default to first league
    fmt = sleeper_client.detect_format(league["league_id"])
    
    cfg = Config(
        league_id=league["league_id"],
        season=int(league.get("season", 2026)),
        user_id=user["user_id"],
        user_name=username,
        league_name=league.get("name", ""),
        format=fmt
    )
    save_config(cfg, path=config_path)
    return cfg
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_onboarding.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ff/services/llm/onboarding.py tests/test_onboarding.py
git commit -m "feat(llm): implement natural language league onboarding helper"
```

---

### Task 5: `ff ask` CLI Command & Typer Integration

**Files:**
- Modify: `src/ff/cli.py`
- Test: `tests/test_cli_ask.py`

**Interfaces:**
- Consumes: `TerminalRunner`, `dispatch_tool`, `onboard_user`, and `rich.console`
- Produces: `ff ask "<query>"` command and `ff config set-llm` command.

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_ask.py`:
```python
from typer.testing import CliRunner
from unittest.mock import patch
import pytest
from ff.cli import app

runner = CliRunner()

def test_ask_command_with_mock_runner() -> None:
    with patch("ff.services.llm.runner.TerminalRunner.run", return_value="Trade evaluation: Bijan side wins."):
        res = runner.invoke(app, ["ask", "Should I trade Gibbs for Bijan?"])
        assert res.exit_code == 0
        assert "Bijan" in res.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_cli_ask.py -v`
Expected: FAIL (No such command 'ask').

- [ ] **Step 3: Write minimal implementation**

In `src/ff/cli.py`, register the `ask` command:
```python
@app.command()
def ask(
    query: str = typer.Argument(..., help="Natural language question about your league"),
    backend: Optional[str] = typer.Option(None, "--backend", help="Override LLM backend (agy, gemini, claude, ollama)")
) -> None:
    """Ask natural language questions about trades, lineups, waivers, or league setup."""
    cfg = load_config()
    target_backend = backend or (cfg.llm_backend if cfg else "auto")
    
    runner_inst = TerminalRunner(backend=target_backend)
    system_prompt = f"You are an assistant for dynasty fantasy football. Available tools: {json.dumps(TOOL_SCHEMAS)}"
    
    response = runner_inst.run(prompt=query, system_prompt=system_prompt)
    console.print(Markdown(response))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_cli_ask.py -v`
Expected: PASS

- [ ] **Step 5: Run full test suite & Commit**

Run: `make test`
Expected: ALL GATE TESTS PASS.

```bash
git add src/ff/cli.py tests/test_cli_ask.py
git commit -m "feat(cli): add 'ff ask' natural language command"
```

---

## Plan Self-Review

1. **Spec Coverage:**
   - Multi-provider runner -> Task 2
   - Tool schema & dispatcher -> Task 3
   - Natural language onboarding -> Task 4
   - `ff ask` CLI command -> Task 5
   - Unit tests & offline fixtures -> Tasks 1-5
2. **Placeholder scan:** None. All commands, file paths, and test definitions are concrete.
3. **Type consistency:** Standardized `Config` schema, `TerminalRunner` signatures, and Pydantic models across all tasks.
