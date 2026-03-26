from __future__ import annotations

from ..shared.artifacts import (
    load_journey_spec,
    load_page_capture_manifest,
    load_page_object_manifest,
    load_runtime_verification_manifest,
    write_json_artifact,
    load_json_artifact,
)
from ..shared.run_artifacts import load_run_directories
from .models import GeneratedTestArtifact
from .planner import build_generated_test_plan
from .renderer import render_generated_test_module
from .state import TestAuthoringState
from .verifier import verify_generated_test_module
from ..shared.workflow_tracing import (
    append_trace_event,
    duration_ms,
    monotonic_seconds,
    serialize_trace_value,
    snapshot_state,
)


def build_test_authoring_nodes() -> dict[str, object]:
    def load_test_authoring_context(state: TestAuthoringState) -> TestAuthoringState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        run_directories = load_run_directories(state["run_root"])
        journey_spec = load_journey_spec(run_directories.journey_dir / "journey_spec.json")
        page_capture_manifest = load_page_capture_manifest(
            run_directories.page_capture_manifest_path
        )
        page_object_manifest = load_page_object_manifest(
            run_directories.page_object_manifest_path
        )
        runtime_verification_manifest = load_runtime_verification_manifest(
            run_directories.page_object_runtime_verification_manifest_path
        )
        output_update = {
            "run_directories": run_directories,
            "journey_spec": journey_spec,
            "page_capture_manifest": page_capture_manifest,
            "snapshots": list(page_capture_manifest["snapshots"]),
            "page_object_manifest": page_object_manifest,
            "page_object_artifacts": list(page_object_manifest["artifacts"]),
            "runtime_verification_manifest": runtime_verification_manifest,
            "runtime_verification_artifacts": list(
                runtime_verification_manifest["artifacts"]
            ),
        }

        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="load_test_authoring_context",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="load_test_authoring_context",
            input_state=input_state,
            output_update=output_update,
            details={
                "page_count": len(journey_spec.page_sequence),
                "page_object_count": len(page_object_manifest["artifacts"]),
                "runtime_verification_count": len(
                    runtime_verification_manifest["artifacts"]
                ),
                "node_duration_ms": duration_ms(node_started, monotonic_seconds()),
            },
        )
        return {
            **output_update,
            "trace_events": trace_events,
        }

    def build_test_plan(state: TestAuthoringState) -> TestAuthoringState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        try:
            generated_test_plan = build_generated_test_plan(
                run_root=state["run_directories"].run_root,
                journey_spec=state["journey_spec"],
                snapshots=state["snapshots"],
                page_object_artifacts=state["page_object_artifacts"],
                runtime_verification_artifacts=state["runtime_verification_artifacts"],
            )
            output_update = {
                "generated_test_plan": generated_test_plan,
                "run_status": "planned",
            }
        except Exception as exc:
            output_update = {
                "run_status": "failed",
                "failure_message": f"Could not build generated test plan: {exc}",
            }

        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="build_test_plan",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="build_test_plan",
            input_state=input_state,
            output_update=output_update,
            details={
                "node_duration_ms": duration_ms(node_started, monotonic_seconds()),
            },
        )
        return {**output_update, "trace_events": trace_events}

    def render_test_module(state: TestAuthoringState) -> TestAuthoringState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        try:
            generated_test_code = render_generated_test_module(state["generated_test_plan"])
            output_update = {
                "generated_test_code": generated_test_code,
                "run_status": "rendered",
            }
        except Exception as exc:
            output_update = {
                "run_status": "failed",
                "failure_message": f"Could not render generated test module: {exc}",
            }

        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="render_test_module",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="render_test_module",
            input_state=input_state,
            output_update=output_update,
            details={
                "node_duration_ms": duration_ms(node_started, monotonic_seconds()),
            },
        )
        return {**output_update, "trace_events": trace_events}

    def verify_test_module(state: TestAuthoringState) -> TestAuthoringState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        verification_result = verify_generated_test_module(state["generated_test_code"])

        if verification_result.is_valid:
            output_update = {"run_status": "verified"}
        else:
            output_update = {
                "run_status": "failed",
                "failure_message": _render_verification_failure(verification_result.errors),
            }

        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="verify_test_module",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="verify_test_module",
            input_state=input_state,
            output_update=output_update,
            details={
                "error_count": len(verification_result.errors),
                "node_duration_ms": duration_ms(node_started, monotonic_seconds()),
            },
        )
        return {**output_update, "trace_events": trace_events}

    def persist_test_artifacts(state: TestAuthoringState) -> TestAuthoringState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        run_directories = state["run_directories"]
        run_manifest_path = run_directories.run_root / "run_manifest.json"

        generated_test_path = run_directories.generated_test_path
        generated_test_path.write_text(state["generated_test_code"], encoding="utf-8")

        test_plan_path = write_json_artifact(
            run_directories.generated_test_plan_path,
            serialize_trace_value(state["generated_test_plan"]),
        )

        generated_test_artifact = GeneratedTestArtifact(
            test_name=state["generated_test_plan"].test_name,
            output_path=str(generated_test_path),
            test_plan_path=str(test_plan_path),
            trace_path=str(run_directories.test_authoring_trace_path),
            page_count=state["generated_test_plan"].page_count,
            step_count=state["generated_test_plan"].step_count,
            run_status="succeeded",
        )

        test_authoring_manifest_path = write_json_artifact(
            run_directories.test_authoring_manifest_path,
            {"artifacts": serialize_trace_value([generated_test_artifact])},
        )

        updated_manifest = {}
        if run_manifest_path.exists():
            updated_manifest = load_json_artifact(run_manifest_path)
        updated_manifest.update(
            {
                "generated_test_path": str(generated_test_path),
                "generated_test_plan_path": str(test_plan_path),
                "test_authoring_manifest_path": str(test_authoring_manifest_path),
                "test_authoring_trace_path": str(run_directories.test_authoring_trace_path),
            }
        )
        write_json_artifact(run_manifest_path, updated_manifest)

        output_update = {
            "generated_test_artifact": generated_test_artifact,
            "generated_test_path": str(generated_test_path),
            "test_plan_path": str(test_plan_path),
            "test_authoring_manifest_path": str(test_authoring_manifest_path),
            "updated_manifest_path": str(run_manifest_path),
        }
        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="persist_test_artifacts",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="persist_test_artifacts",
            input_state=input_state,
            output_update=output_update,
            details={
                "page_count": generated_test_artifact.page_count,
                "step_count": generated_test_artifact.step_count,
                "node_duration_ms": duration_ms(node_started, monotonic_seconds()),
            },
        )
        return {**output_update, "trace_events": trace_events}

    def complete_test_authoring(state: TestAuthoringState) -> TestAuthoringState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        output_update = {"run_status": "succeeded"}
        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="complete_test_authoring",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="complete_test_authoring",
            input_state=input_state,
            output_update=output_update,
            details={"node_duration_ms": duration_ms(node_started, monotonic_seconds())},
        )
        return {**output_update, "trace_events": trace_events}

    def fail_test_authoring(state: TestAuthoringState) -> TestAuthoringState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        output_update = {
            "run_status": "failed",
            "failure_message": state["failure_message"],
        }
        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="fail_test_authoring",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="fail_test_authoring",
            input_state=input_state,
            output_update=output_update,
            details={"node_duration_ms": duration_ms(node_started, monotonic_seconds())},
        )
        return {**output_update, "trace_events": trace_events}

    return {
        "load_test_authoring_context": load_test_authoring_context,
        "build_test_plan": build_test_plan,
        "render_test_module": render_test_module,
        "verify_test_module": verify_test_module,
        "persist_test_artifacts": persist_test_artifacts,
        "complete_test_authoring": complete_test_authoring,
        "fail_test_authoring": fail_test_authoring,
    }


def _render_verification_failure(errors: list[str]) -> str:
    lines = ["Generated pytest module failed verification:"]
    for error in errors:
        lines.append(f"- {error}")
    return "\n".join(lines)
