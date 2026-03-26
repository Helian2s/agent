from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..config import PROJECT_ROOT


RUN_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"


@dataclass(frozen=True)
class RunDirectories:
    run_id: str
    run_root: Path
    input_dir: Path
    journey_dir: Path
    pages_dir: Path
    page_objects_dir: Path
    tests_dir: Path
    logs_dir: Path

    @property
    def journey_trace_path(self) -> Path:
        return self.logs_dir / "journey_planning_trace.json"

    @property
    def page_capture_trace_path(self) -> Path:
        return self.logs_dir / "page_capture_trace.json"

    @property
    def page_capture_manifest_path(self) -> Path:
        return self.pages_dir / "page_capture_manifest.json"

    @property
    def page_object_manifest_path(self) -> Path:
        return self.page_objects_dir / "page_object_manifest.json"

    @property
    def page_object_factory_trace_path(self) -> Path:
        return self.logs_dir / "page_object_factory_trace.json"

    @property
    def page_object_traces_dir(self) -> Path:
        return self.logs_dir / "page_object_traces"

    @property
    def page_object_runtime_verification_manifest_path(self) -> Path:
        return self.page_objects_dir / "page_object_runtime_verification_manifest.json"

    @property
    def page_object_runtime_verification_trace_path(self) -> Path:
        return self.logs_dir / "page_object_runtime_verification_trace.json"

    @property
    def generated_test_path(self) -> Path:
        return self.tests_dir / "test_generated_journey.py"

    @property
    def generated_test_plan_path(self) -> Path:
        return self.tests_dir / "generated_journey_plan.json"

    @property
    def test_authoring_manifest_path(self) -> Path:
        return self.tests_dir / "test_authoring_manifest.json"

    @property
    def test_authoring_trace_path(self) -> Path:
        return self.logs_dir / "test_authoring_trace.json"

    @property
    def test_execution_report_path(self) -> Path:
        return self.tests_dir / "test_execution_report.json"

    @property
    def test_execution_manifest_path(self) -> Path:
        return self.tests_dir / "test_execution_manifest.json"

    @property
    def test_execution_trace_path(self) -> Path:
        return self.logs_dir / "test_execution_trace.json"

    @property
    def test_repair_traces_dir(self) -> Path:
        return self.logs_dir / "test_repair_traces"


def create_run_directories(
    *,
    output_root: Path | None = None,
    now: datetime | None = None,
) -> RunDirectories:
    base_output_root = (output_root or (PROJECT_ROOT / "output")).resolve()
    timestamp = (now or datetime.now(timezone.utc)).strftime(RUN_TIMESTAMP_FORMAT)
    run_root = _resolve_unique_run_root(base_output_root, timestamp)

    input_dir = run_root / "input"
    journey_dir = run_root / "journey"
    pages_dir = run_root / "pages"
    page_objects_dir = run_root / "page_objects"
    tests_dir = run_root / "tests"
    logs_dir = run_root / "logs"

    for path in (
        input_dir,
        journey_dir,
        pages_dir,
        page_objects_dir,
        tests_dir,
        logs_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)

    return RunDirectories(
        run_id=run_root.name,
        run_root=run_root,
        input_dir=input_dir,
        journey_dir=journey_dir,
        pages_dir=pages_dir,
        page_objects_dir=page_objects_dir,
        tests_dir=tests_dir,
        logs_dir=logs_dir,
    )


def load_run_directories(run_root: str | Path) -> RunDirectories:
    resolved_run_root = Path(run_root).expanduser().resolve()
    return RunDirectories(
        run_id=resolved_run_root.name,
        run_root=resolved_run_root,
        input_dir=resolved_run_root / "input",
        journey_dir=resolved_run_root / "journey",
        pages_dir=resolved_run_root / "pages",
        page_objects_dir=resolved_run_root / "page_objects",
        tests_dir=resolved_run_root / "tests",
        logs_dir=resolved_run_root / "logs",
    )


def _resolve_unique_run_root(base_output_root: Path, timestamp: str) -> Path:
    candidate = base_output_root / timestamp
    suffix = 1
    while candidate.exists():
        candidate = base_output_root / f"{timestamp}_{suffix:02d}"
        suffix += 1
    return candidate
