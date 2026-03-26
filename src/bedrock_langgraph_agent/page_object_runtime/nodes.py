from __future__ import annotations

from pathlib import Path

from ..shared.artifacts import (
    load_json_artifact,
    load_page_capture_manifest,
    write_json_artifact,
)
from ..shared.llm import TextGenerator
from ..page_capture.browser import BrowserSession
from ..page_object_factory.models import PageObjectArtifact
from .models import RuntimeVerificationArtifact
from .state import PageObjectRuntimeState
from .verifier import (
    render_runtime_verification_feedback,
    verify_page_object_runtime,
)
from ..page_object_generation.tracing import write_trace_log
from ..page_object_generation.workflow import build_page_object_graph
from ..shared.run_artifacts import load_run_directories
from ..shared.workflow_tracing import (
    append_trace_event,
    duration_ms,
    monotonic_seconds,
    serialize_trace_value,
    snapshot_state,
)


def build_page_object_runtime_nodes(
    text_generator: TextGenerator,
    browser_session: BrowserSession,
) -> dict[str, object]:
    single_page_graph = build_page_object_graph(text_generator)

    def load_runtime_context(state: PageObjectRuntimeState) -> PageObjectRuntimeState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        run_directories = load_run_directories(state["run_root"])
        page_capture_manifest = load_page_capture_manifest(
            run_directories.page_capture_manifest_path
        )
        page_object_manifest = load_json_artifact(run_directories.page_object_manifest_path)
        page_object_artifacts = [
            PageObjectArtifact(
                sequence=int(artifact["sequence"]),
                page_name=str(artifact["page_name"]),
                class_name=str(artifact["class_name"]),
                source_html_path=str(artifact["source_html_path"]),
                output_path=str(artifact["output_path"]),
                trace_path=str(artifact["trace_path"]),
                attempt_count=int(artifact["attempt_count"]),
                run_status=str(artifact["run_status"]),
            )
            for artifact in page_object_manifest.get("artifacts", [])
        ]
        output_update = {
            "run_directories": run_directories,
            "page_capture_manifest": page_capture_manifest,
            "snapshots": list(page_capture_manifest["snapshots"]),
            "page_object_manifest": page_object_manifest,
            "page_object_artifacts": page_object_artifacts,
        }

        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="load_runtime_context",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="load_runtime_context",
            input_state=input_state,
            output_update=output_update,
            details={
                "artifact_count": len(page_object_artifacts),
                "snapshot_count": len(page_capture_manifest["snapshots"]),
                "node_duration_ms": duration_ms(node_started, monotonic_seconds()),
            },
        )
        return {
            **output_update,
            "trace_events": trace_events,
        }

    def verify_and_repair_page_objects(state: PageObjectRuntimeState) -> PageObjectRuntimeState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        run_directories = state["run_directories"]
        max_attempts = int(state.get("max_attempts", 2))
        runtime_artifacts: list[RuntimeVerificationArtifact] = []
        run_status = "running"
        failure_message = ""

        snapshot_by_sequence = {
            snapshot.sequence: snapshot for snapshot in state["snapshots"]
        }
        run_directories.page_object_traces_dir.mkdir(parents=True, exist_ok=True)

        for artifact in state["page_object_artifacts"]:
            snapshot = snapshot_by_sequence.get(artifact.sequence)
            if snapshot is None:
                run_status = "failed"
                failure_message = (
                    f"Could not find a captured snapshot for page object `{artifact.page_name}`."
                )
                break

            output_path = Path(artifact.output_path)
            runtime_attempt = 1

            while True:
                code = output_path.read_text(encoding="utf-8")
                verification_result = verify_page_object_runtime(
                    code,
                    snapshot,
                    browser_session,
                    class_name_source=snapshot.title.strip() or snapshot.page_name,
                )
                verification_report_path = (
                    run_directories.page_objects_dir
                    / f"{artifact.sequence:02d}_{artifact.page_name}_runtime_verification.json"
                )
                write_json_artifact(
                    verification_report_path,
                    serialize_trace_value(
                        {
                            "page_name": artifact.page_name,
                            "runtime_attempt": runtime_attempt,
                            "is_valid": verification_result.is_valid,
                            "errors": verification_result.errors,
                            "checks": verification_result.checks,
                        }
                    ),
                )

                if verification_result.is_valid:
                    runtime_artifacts.append(
                        RuntimeVerificationArtifact(
                            sequence=artifact.sequence,
                            page_name=artifact.page_name,
                            output_path=str(output_path),
                            trace_path=artifact.trace_path,
                            verification_report_path=str(verification_report_path),
                            runtime_attempt_count=runtime_attempt,
                            run_status="succeeded",
                            errors=[],
                        )
                    )
                    break

                if runtime_attempt >= max_attempts:
                    run_status = "failed"
                    failure_message = (
                        f"Runtime verification failed for `{artifact.page_name}` after "
                        f"{runtime_attempt} attempts.\n"
                        f"{render_runtime_verification_feedback(verification_result)}\n"
                        f"Verification report: {verification_report_path}"
                    )
                    runtime_artifacts.append(
                        RuntimeVerificationArtifact(
                            sequence=artifact.sequence,
                            page_name=artifact.page_name,
                            output_path=str(output_path),
                            trace_path=artifact.trace_path,
                            verification_report_path=str(verification_report_path),
                            runtime_attempt_count=runtime_attempt,
                            run_status="failed",
                            errors=verification_result.errors,
                        )
                    )
                    break

                repair_feedback = render_runtime_verification_feedback(verification_result)
                page_result = single_page_graph.invoke(
                    {
                        "html_path": snapshot.html_path,
                        "page_object_name_hint": snapshot.title.strip() or snapshot.page_name,
                        "max_attempts": max_attempts,
                        "verification_feedback": repair_feedback,
                    }
                )
                repair_trace_path = (
                    run_directories.page_object_traces_dir
                    / f"{artifact.sequence:02d}_{artifact.page_name}_runtime_repair_{runtime_attempt}_{page_result.get('run_status', 'unknown')}.json"
                )
                write_trace_log(
                    serialize_trace_value(page_result.get("trace_events", [])),
                    repair_trace_path,
                )

                if page_result.get("run_status") == "failed":
                    run_status = "failed"
                    failure_message = (
                        f"Runtime repair failed for `{artifact.page_name}`.\n"
                        f"{page_result.get('failure_message', 'Unknown page object failure.')}\n"
                        f"Repair trace: {repair_trace_path}"
                    )
                    runtime_artifacts.append(
                        RuntimeVerificationArtifact(
                            sequence=artifact.sequence,
                            page_name=artifact.page_name,
                            output_path=str(output_path),
                            trace_path=str(repair_trace_path),
                            verification_report_path=str(verification_report_path),
                            runtime_attempt_count=runtime_attempt,
                            run_status="failed",
                            errors=verification_result.errors,
                        )
                    )
                    break

                output_path.write_text(page_result["final_page_object"], encoding="utf-8")
                artifact = PageObjectArtifact(
                    sequence=artifact.sequence,
                    page_name=artifact.page_name,
                    class_name=page_result["page_spec"].class_name,
                    source_html_path=artifact.source_html_path,
                    output_path=artifact.output_path,
                    trace_path=str(repair_trace_path),
                    attempt_count=int(page_result.get("attempt_count", 0)),
                    run_status=str(page_result.get("run_status", "unknown")),
                )
                runtime_attempt += 1

            if run_status == "failed":
                break

        output_update = {
            "runtime_verification_artifacts": runtime_artifacts,
            "run_status": run_status,
        }
        if failure_message:
            output_update["failure_message"] = failure_message

        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="verify_and_repair_page_objects",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="verify_and_repair_page_objects",
            input_state=input_state,
            output_update=output_update,
            details={
                "verified_count": len(runtime_artifacts),
                "node_duration_ms": duration_ms(node_started, monotonic_seconds()),
            },
        )
        return {
            **output_update,
            "trace_events": trace_events,
        }

    def persist_runtime_manifest(state: PageObjectRuntimeState) -> PageObjectRuntimeState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        run_directories = state["run_directories"]
        runtime_manifest_path = run_directories.page_object_runtime_verification_manifest_path
        run_manifest_path = run_directories.run_root / "run_manifest.json"

        write_json_artifact(
            runtime_manifest_path,
            {
                "artifacts": serialize_trace_value(
                    state.get("runtime_verification_artifacts", [])
                ),
            },
        )

        updated_manifest = {}
        if run_manifest_path.exists():
            updated_manifest = load_json_artifact(run_manifest_path)
        updated_manifest.update(
            {
                "page_object_runtime_verification_manifest_path": str(runtime_manifest_path),
                "page_object_runtime_verification_trace_path": str(
                    run_directories.page_object_runtime_verification_trace_path
                ),
            }
        )
        write_json_artifact(run_manifest_path, updated_manifest)

        output_update = {
            "runtime_verification_manifest_path": runtime_manifest_path,
            "updated_manifest_path": run_manifest_path,
        }
        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="persist_runtime_manifest",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="persist_runtime_manifest",
            input_state=input_state,
            output_update=output_update,
            details={
                "artifact_count": len(state.get("runtime_verification_artifacts", [])),
                "node_duration_ms": duration_ms(node_started, monotonic_seconds()),
            },
        )
        return {
            **output_update,
            "trace_events": trace_events,
        }

    def complete_runtime_verification(state: PageObjectRuntimeState) -> PageObjectRuntimeState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        output_update = {"run_status": "succeeded"}
        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="complete_runtime_verification",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="complete_runtime_verification",
            input_state=input_state,
            output_update=output_update,
            details={
                "node_duration_ms": duration_ms(node_started, monotonic_seconds()),
            },
        )
        return {
            **output_update,
            "trace_events": trace_events,
        }

    def fail_runtime_verification(state: PageObjectRuntimeState) -> PageObjectRuntimeState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        output_update = {
            "run_status": "failed",
            "failure_message": state["failure_message"],
        }
        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="fail_runtime_verification",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="fail_runtime_verification",
            input_state=input_state,
            output_update=output_update,
            details={
                "node_duration_ms": duration_ms(node_started, monotonic_seconds()),
            },
        )
        return {
            **output_update,
            "trace_events": trace_events,
        }

    return {
        "load_runtime_context": load_runtime_context,
        "verify_and_repair_page_objects": verify_and_repair_page_objects,
        "persist_runtime_manifest": persist_runtime_manifest,
        "complete_runtime_verification": complete_runtime_verification,
        "fail_runtime_verification": fail_runtime_verification,
    }
