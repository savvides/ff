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
