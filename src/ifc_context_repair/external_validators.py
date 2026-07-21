from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(slots=True)
class ExternalValidationResult:
    validator: str
    version: str | None
    success: bool
    exit_code: int | None
    duration_seconds: float
    messages: list[str]


class ExternalValidator(Protocol):
    def validate(self, path: Path) -> ExternalValidationResult: ...


@dataclass(slots=True)
class CommandValidator:
    """Future validator adapter; arguments are fixed, never evaluated by a shell."""

    name: str
    executable: Path
    arguments: list[str]
    timeout_seconds: float = 300.0
    version: str | None = None

    def validate(self, path: Path) -> ExternalValidationResult:
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                [str(self.executable), *self.arguments, str(path)],
                capture_output=True, text=True, timeout=self.timeout_seconds,
                check=False, shell=False,
            )
            messages = [line for line in (completed.stdout + "\n" + completed.stderr).splitlines()
                        if line.strip()]
            return ExternalValidationResult(
                self.name, self.version, completed.returncode == 0, completed.returncode,
                time.perf_counter() - started, messages,
            )
        except subprocess.TimeoutExpired:
            return ExternalValidationResult(
                self.name, self.version, False, None, time.perf_counter() - started,
                [f"Validator exceeded {self.timeout_seconds:g} second timeout"],
            )
