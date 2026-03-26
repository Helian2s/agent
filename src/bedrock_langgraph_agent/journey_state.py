from __future__ import annotations

from typing import Any, TypedDict

from .journey_models import JourneySpec, NormalizedJourneyEvent
from .run_artifacts import RunDirectories
from .workflow_tracing import TraceEvent


class JourneyPlanningState(TypedDict, total=False):
    journey_events_path: str
    run_directories: RunDirectories
    input_copy_path: str
    raw_events: list[dict[str, Any]]
    normalized_events: list[NormalizedJourneyEvent]
    journey_spec: JourneySpec
    next_node: str
    auth_checkpoint_status: str
    auth_checkpoint_message: str
    auth_checkpoint_path: str
    normalized_events_path: str
    journey_spec_path: str
    manifest_path: str
    run_status: str
    trace_events: list[TraceEvent]
    failure_message: str
    extra: dict[str, Any]
