from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TestExecutionAttempt:
    attempt: int
    command: list[str]
    exit_code: int
    succeeded: bool
    duration_ms: float
    stdout: str
    stderr: str
    normalized_failure: str
    repaired: bool = False
    repair_trace_path: str | None = None


@dataclass(frozen=True)
class TestExecutionArtifact:
    test_name: str
    output_path: str
    execution_report_path: str
    trace_path: str
    repair_traces_dir: str
    attempt_count: int
    last_exit_code: int
    run_status: str
    errors: list[str] = field(default_factory=list)
