"""Data contracts for the post-command QA validation system."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class QACheck(BaseModel):
    """An individual assertion or sanity check performed during QA."""

    name: str
    passed: bool
    message: str = ""
    is_warning: bool = False


class QAReport(BaseModel):
    """Aggregated QA report containing results of all checks for a command."""

    command: str
    passed: bool
    checks: List[QACheck] = Field(default_factory=list)
    checks_passed: int = 0
    checks_failed: int = 0
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    duration_ms: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_checks(
        cls,
        command: str,
        checks: List[QACheck],
        duration_ms: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> QAReport:
        errors = [f"[{c.name}] {c.message or 'Check failed'}" for c in checks if not c.passed and not c.is_warning]
        warnings = [f"[{c.name}] {c.message or 'Warning detected'}" for c in checks if not c.passed and c.is_warning]
        passed = len(errors) == 0
        checks_passed = sum(1 for c in checks if c.passed)
        checks_failed = sum(1 for c in checks if not c.passed)
        return cls(
            command=command,
            passed=passed,
            checks=checks,
            checks_passed=checks_passed,
            checks_failed=checks_failed,
            errors=errors,
            warnings=warnings,
            duration_ms=round(duration_ms, 2),
            metadata=metadata or {},
        )


class QAInvariantError(Exception):
    """Raised when one or more strict QA invariants are violated."""

    def __init__(self, command: str, errors: List[str]):
        self.command = command
        self.errors = errors
        error_lines = "\n  - ".join(errors)
        super().__init__(f"QA invariant violation in '{command}':\n  - {error_lines}")
