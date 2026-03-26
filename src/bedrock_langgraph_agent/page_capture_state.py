from __future__ import annotations

from typing import Any, TypedDict

from .journey_models import JourneySpec
from .page_capture_models import PageSnapshot
from .run_artifacts import RunDirectories
from .workflow_tracing import TraceEvent


class PageCaptureState(TypedDict, total=False):
    run_root: str
    run_directories: RunDirectories
    journey_spec: JourneySpec
    auth_checkpoint: dict[str, Any]
    auth_session_status: str
    auth_session_message: str
    page_snapshots: list[PageSnapshot]
    page_capture_manifest_path: str
    updated_manifest_path: str
    run_status: str
    trace_events: list[TraceEvent]
