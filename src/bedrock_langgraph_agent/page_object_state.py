from __future__ import annotations

from typing import TypedDict

from .page_object_policy import PageSpec
from .page_object_tracing import TraceEvent


class PageObjectState(TypedDict, total=False):
    html_path: str
    max_attempts: int
    page_spec: PageSpec
    attempt_count: int
    generated_code: str
    verification_passed: bool
    verification_feedback: str
    verification_errors: list[str]
    final_page_object: str
    next_node: str
    run_status: str
    failure_message: str
    trace_events: list[TraceEvent]
