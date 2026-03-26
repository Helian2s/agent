from __future__ import annotations

from typing import TypedDict

from .policy import PageSpec
from .tracing import TraceEvent


class PageObjectState(TypedDict, total=False):
    html_path: str
    page_object_name_hint: str
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
