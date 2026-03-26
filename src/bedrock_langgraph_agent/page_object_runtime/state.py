from __future__ import annotations

from typing import Any, TypedDict

from ..page_capture.models import PageSnapshot
from ..page_object_factory.models import PageObjectArtifact
from .models import RuntimeVerificationArtifact
from ..shared.run_artifacts import RunDirectories
from ..shared.workflow_tracing import TraceEvent


class PageObjectRuntimeState(TypedDict, total=False):
    run_root: str
    max_attempts: int
    run_directories: RunDirectories
    page_capture_manifest: dict[str, Any]
    snapshots: list[PageSnapshot]
    page_object_manifest: dict[str, Any]
    page_object_artifacts: list[PageObjectArtifact]
    runtime_verification_artifacts: list[RuntimeVerificationArtifact]
    runtime_verification_manifest_path: str
    updated_manifest_path: str
    run_status: str
    failure_message: str
    trace_events: list[TraceEvent]
