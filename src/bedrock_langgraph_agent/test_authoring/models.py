from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


TestStepType = Literal["open_page", "page_object_call", "scroll"]
TestStepSource = Literal["journey", "runtime_fallback"]


@dataclass(frozen=True)
class GeneratedTestStep:
    sequence: int
    step_type: TestStepType
    source: TestStepSource
    page_name: str
    description: str
    variable_name: str | None = None
    url: str | None = None
    page_title: str | None = None
    class_name: str | None = None
    page_object_relative_path: str | None = None
    method_name: str | None = None
    method_action: str | None = None
    args: list[Any] = field(default_factory=list)
    scroll_fraction: float | None = None


@dataclass(frozen=True)
class GeneratedTestPlan:
    test_name: str
    page_count: int
    step_count: int
    steps: list[GeneratedTestStep] = field(default_factory=list)


@dataclass(frozen=True)
class GeneratedTestArtifact:
    test_name: str
    output_path: str
    test_plan_path: str
    trace_path: str
    page_count: int
    step_count: int
    run_status: str
