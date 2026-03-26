from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
from typing import Protocol

from .config import PROJECT_ROOT
from .workflow_tracing import duration_ms, monotonic_seconds


@dataclass(frozen=True)
class TestRunResult:
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float


class GeneratedTestRunner(Protocol):
    def run(self, *, test_path: Path, run_root: Path) -> TestRunResult:
        """Execute the generated test file and return a normalized result."""


class PytestCommandRunner:
    def __init__(
        self,
        *,
        timeout_seconds: int = 120,
    ) -> None:
        self._timeout_seconds = timeout_seconds

    def run(self, *, test_path: Path, run_root: Path) -> TestRunResult:
        started = monotonic_seconds()
        command = [
            sys.executable,
            "-m",
            "pytest",
            str(test_path),
            "-q",
            "--maxfail=1",
            "--disable-warnings",
        ]
        env = os.environ.copy()
        env.setdefault("PROOFICA_HEADLESS", "1")

        try:
            completed = subprocess.run(
                command,
                cwd=str(PROJECT_ROOT),
                env=env,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                check=False,
            )
            exit_code = int(completed.returncode)
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as exc:
            exit_code = 124
            stdout = exc.stdout or ""
            stderr = (exc.stderr or "") + (
                f"\nPytest timed out after {self._timeout_seconds} seconds."
            )
        except Exception as exc:
            exit_code = 1
            stdout = ""
            stderr = f"Pytest runner could not start: {exc}"

        return TestRunResult(
            command=command,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms(started, monotonic_seconds()),
        )
