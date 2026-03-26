from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PageObjectArtifact:
    sequence: int
    page_name: str
    class_name: str
    source_html_path: str
    output_path: str
    trace_path: str
    attempt_count: int
    run_status: str
