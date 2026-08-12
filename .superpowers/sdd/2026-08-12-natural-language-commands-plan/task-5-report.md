# Task 5 Report: `ff ask` CLI Command & Typer Integration

## Summary
Successfully integrated `ff ask "<query>"` natural language command and `ff config set-llm <backend>` configuration command into `src/ff/cli.py`, backed by unit tests in `tests/test_cli_ask.py`.

## Files Modified & Created
- **Modified**: `src/ff/cli.py`
  - Integrated `ff ask` command accepting query string argument and optional `--backend` override option.
  - Formatted LLM output using `rich.markdown.Markdown`.
  - Added `config` Typer sub-app (`config_app`) with `set-llm` command to set and persist `llm_backend` and optional `ollama_model` in local config.
- **Created**: `tests/test_cli_ask.py`
  - Added unit test `test_ask_command_with_mock_runner` verifying successful execution and output rendering.
  - Added unit test `test_ask_command_backend_override` verifying backend override option.
  - Added unit test `test_config_set_llm_command` verifying setting and saving configuration backend settings.
  - Added unit test `test_config_set_llm_invalid_backend` verifying validation error handling for invalid backends.

## Verification
- Test execution: `./.venv/bin/pytest tests/test_cli_ask.py -v` (Passed 4/4 tests)
- Full test suite execution: `make test` (Passed 135/135 tests)
- Git commit created: `feat(cli): add 'ff ask' natural language command` (`387ee0d`)

## Conclusion
Task 5 implementation is complete, fully tested, and verified.

## Review Fixes Applied
- **`src/ff/cli.py`**:
  - Updated `ask()` command to pass `ollama_model=cfg.ollama_model if cfg else "llama3.2"` to `TerminalRunner`.
  - Updated `set_llm()` command to handle missing configuration gracefully via `config_exists()` check and `FileNotFoundError` handling, exiting with `_fail("No league configured. Run 'ff setup <username>' first.")`.
  - Removed unused imports (`Format`, `_config_path`, `dispatch_tool`, `onboard_user`).
- **`tests/test_cli_ask.py`**:
  - Added `from __future__ import annotations` as the top line.
  - Updated `test_ask_command_backend_override` assertion to include `ollama_model`.
  - Removed obsolete `ff.cli._config_path` monkeypatches.
  - Added unit test `test_config_set_llm_no_config` verifying graceful failure when config is missing.
- **Verification**: `./.venv/bin/pytest tests/test_cli_ask.py` (5/5 passed), full test suite (136/136 passed).

