from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RuntimeVerificationArtifact:
    sequence: int
    page_name: str
    output_path: str
    trace_path: str
    verification_report_path: str
    runtime_attempt_count: int
    run_status: str
    errors: list[str] = field(default_factory=list)
