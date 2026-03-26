from __future__ import annotations

from typing import Any, TypedDict

from .journey_models import JourneySpec
from .page_object_factory_models import PageObjectArtifact
from .run_artifacts import RunDirectories
from .test_authoring_models import GeneratedTestArtifact, GeneratedTestPlan
from .test_execution_models import TestExecutionArtifact, TestExecutionAttempt
from .workflow_tracing import TraceEvent


class TestExecutionState(TypedDict, total=False):
    run_root: str
    max_attempts: int
    run_directories: RunDirectories
    journey_spec: JourneySpec
    page_object_manifest: dict[str, Any]
    page_object_artifacts: list[PageObjectArtifact]
    generated_test_artifact: GeneratedTestArtifact
    generated_test_plan: GeneratedTestPlan
    generated_test_code: str
    failure_feedback: str
    execution_passed: bool
    repaired_since_last_execution: bool
    last_repair_trace_path: str
    next_node: str
    execution_attempts: list[TestExecutionAttempt]
    test_execution_artifact: TestExecutionArtifact
    test_execution_report_path: str
    test_execution_manifest_path: str
    updated_manifest_path: str
    run_status: str
    failure_message: str
    trace_events: list[TraceEvent]
