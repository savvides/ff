from __future__ import annotations

import shutil
import subprocess
from typing import List, Optional

SUPPORTED_BACKENDS = ["agy", "gemini", "claude", "ollama"]
RUN_TIMEOUT = 120  # seconds; a hung local model must not block the CLI forever


class TerminalRunner:
    def __init__(self, backend: str = "auto", ollama_model: str = "llama3.2") -> None:
        self.ollama_model = ollama_model
        self.backend = self._resolve_backend(backend)

    def _resolve_backend(self, backend: str) -> str:
        if backend != "auto":
            if backend in SUPPORTED_BACKENDS:
                if not shutil.which(backend):
                    raise RuntimeError(f"Backend '{backend}' requested but binary '{backend}' was not found in PATH.")
                return backend
            raise ValueError(f"Unsupported backend '{backend}'. Must be 'auto' or one of {SUPPORTED_BACKENDS}")
        for b in SUPPORTED_BACKENDS:
            if shutil.which(b):
                return b
        return "none"

    def _cmd(self, full_prompt: str) -> List[str]:
        # Print/headless flags only. Do not pass permission-bypass flags: these
        # binaries are coding agents, and ff ask should be a completion, not a
        # session with filesystem tools.
        if self.backend == "agy":
            return ["agy", "--print", "--sandbox", full_prompt]
        if self.backend == "gemini":
            return ["gemini", "-p", full_prompt, "--approval-mode", "plan"]
        if self.backend == "claude":
            return ["claude", "-p", "--bare", full_prompt]
        if self.backend == "ollama":
            return ["ollama", "run", self.ollama_model, full_prompt]
        raise ValueError(f"Unknown backend: {self.backend}")

    def run(self, prompt: str, system_prompt: str = "") -> str:
        if self.backend == "none":
            raise RuntimeError("No supported terminal AI runner (agy, gemini, claude, ollama) found in PATH.")

        full_prompt = f"System: {system_prompt}\nUser: {prompt}" if system_prompt else prompt
        res = subprocess.run(
            self._cmd(full_prompt),
            capture_output=True,
            text=True,
            check=True,
            timeout=RUN_TIMEOUT,
        )
        return res.stdout.strip()
