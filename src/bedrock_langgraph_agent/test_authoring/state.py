from __future__ import annotations

from typing import Any, TypedDict

from ..journey_planning.models import JourneySpec
from ..page_capture.models import PageSnapshot
from ..page_object_factory.models import PageObjectArtifact
from ..page_object_runtime.models import RuntimeVerificationArtifact
from ..shared.run_artifacts import RunDirectories
from .models import GeneratedTestArtifact, GeneratedTestPlan
from ..shared.workflow_tracing import TraceEvent


class TestAuthoringState(TypedDict, total=False):
    run_root: str
    run_directories: RunDirectories
    journey_spec: JourneySpec
    page_capture_manifest: dict[str, Any]
    snapshots: list[PageSnapshot]
    page_object_manifest: dict[str, Any]
    page_object_artifacts: list[PageObjectArtifact]
    runtime_verification_manifest: dict[str, Any]
    runtime_verification_artifacts: list[RuntimeVerificationArtifact]
    generated_test_plan: GeneratedTestPlan
    generated_test_code: str
    generated_test_artifact: GeneratedTestArtifact
    generated_test_path: str
    test_plan_path: str
    test_authoring_manifest_path: str
    updated_manifest_path: str
    run_status: str
    failure_message: str
    trace_events: list[TraceEvent]
