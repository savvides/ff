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
    with patch("shutil.which", return_value="/usr/bin/agy"):
        runner = TerminalRunner(backend="agy")
        completed = subprocess.CompletedProcess(args=["agy"], returncode=0, stdout="Answer text", stderr="")
        with patch("subprocess.run", return_value=completed) as mock_run:
            res = runner.run(prompt="Hello", system_prompt="You are an assistant.")
            assert res == "Answer text"
            assert mock_run.called

def test_runner_explicit_backend_missing() -> None:
    from ff.services.llm.runner import TerminalRunner
    with patch("shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="not found in PATH"):
            TerminalRunner(backend="claude")

def test_runner_unsupported_backend() -> None:
    from ff.services.llm.runner import TerminalRunner
    with pytest.raises(ValueError, match="Unsupported backend"):
        TerminalRunner(backend="invalid_backend")
