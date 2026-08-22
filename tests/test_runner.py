import subprocess
from unittest.mock import patch
import pytest

def test_runner_auto_detect_agy() -> None:
    from ff.services.llm.runner import TerminalRunner
    with patch("shutil.which", side_effect=lambda bin_name: "/usr/bin/agy" if bin_name == "agy" else None):
        runner = TerminalRunner(backend="auto")
        assert runner.backend == "agy"

def test_runner_executes_subprocess() -> None:
    from ff.services.llm.runner import RUN_TIMEOUT, TerminalRunner
    with patch("shutil.which", return_value="/usr/bin/agy"):
        runner = TerminalRunner(backend="agy")
        completed = subprocess.CompletedProcess(args=["agy"], returncode=0, stdout="Answer text", stderr="")
        with patch("subprocess.run", return_value=completed) as mock_run:
            res = runner.run(prompt="Hello", system_prompt="You are an assistant.")
            assert res == "Answer text"
            args, kwargs = mock_run.call_args
            assert args[0][0:3] == ["agy", "--print", "--sandbox"]
            assert kwargs["timeout"] == RUN_TIMEOUT
            assert kwargs["check"] is True
            assert kwargs.get("shell") is not True


def test_runner_claude_and_gemini_use_headless_flags() -> None:
    from ff.services.llm.runner import TerminalRunner
    with patch("shutil.which", return_value="/usr/bin/bin"):
        claude = TerminalRunner(backend="claude")
        assert claude._cmd("hi")[:3] == ["claude", "-p", "--bare"]
        gemini = TerminalRunner(backend="gemini")
        cmd = gemini._cmd("hi")
        assert cmd[:2] == ["gemini", "-p"]
        assert "--approval-mode" in cmd
        assert "plan" in cmd

def test_runner_explicit_backend_missing() -> None:
    from ff.services.llm.runner import TerminalRunner
    with patch("shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="not found in PATH"):
            TerminalRunner(backend="claude")

def test_runner_unsupported_backend() -> None:
    from ff.services.llm.runner import TerminalRunner
    with pytest.raises(ValueError, match="Unsupported backend"):
        TerminalRunner(backend="invalid_backend")
