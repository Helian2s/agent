from __future__ import annotations

from pathlib import Path

from ..shared.artifacts import load_page_capture_manifest, load_json_artifact, write_json_artifact
from ..shared.llm import TextGenerator
from .models import PageObjectArtifact
from .state import PageObjectFactoryState
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


def build_page_object_factory_nodes(
    text_generator: TextGenerator,
) -> dict[str, object]:
    single_page_graph = build_page_object_graph(text_generator)

    def load_factory_context(state: PageObjectFactoryState) -> PageObjectFactoryState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        run_directories = load_run_directories(state["run_root"])
        page_capture_manifest = load_page_capture_manifest(
            run_directories.page_capture_manifest_path
        )
        snapshots = list(page_capture_manifest["snapshots"])
        output_update = {
            "run_directories": run_directories,
            "page_capture_manifest": page_capture_manifest,
            "snapshots": snapshots,
        }

        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="load_factory_context",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="load_factory_context",
            input_state=input_state,
            output_update=output_update,
            details={
                "snapshot_count": len(snapshots),
                "run_root": str(run_directories.run_root),
                "node_duration_ms": duration_ms(node_started, monotonic_seconds()),
            },
        )
        return {
            **output_update,
            "trace_events": trace_events,
        }

    def generate_page_objects(state: PageObjectFactoryState) -> PageObjectFactoryState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        run_directories = state["run_directories"]
        max_attempts = int(state.get("max_attempts", 3))
        artifacts: list[PageObjectArtifact] = []
        run_status = "running"
        failure_message = ""

        run_directories.page_object_traces_dir.mkdir(parents=True, exist_ok=True)

        for snapshot in state["snapshots"]:
            page_object_name_hint = snapshot.title.strip() or snapshot.page_name
            page_result = single_page_graph.invoke(
                {
                    "html_path": snapshot.html_path,
                    "page_object_name_hint": page_object_name_hint,
                    "max_attempts": max_attempts,
                }
            )

            trace_path = _resolve_page_object_trace_path(
                run_directories=run_directories,
                snapshot=snapshot,
                run_status=str(page_result.get("run_status", "unknown")),
            )
            write_trace_log(
                serialize_trace_value(page_result.get("trace_events", [])),
                trace_path,
            )

            if page_result.get("run_status") == "failed":
                run_status = "failed"
                failure_message = (
                    f"Page object generation failed for `{snapshot.page_name}`.\n"
                    f"{page_result.get('failure_message', 'Unknown page object failure.')}\n"
                    f"Trace log: {trace_path}"
                )
                break

            page_spec = page_result["page_spec"]
            output_path = (
                run_directories.page_objects_dir
                / f"{snapshot.sequence:02d}_{snapshot.page_name}_page.py"
            )
            output_path.write_text(page_result["final_page_object"], encoding="utf-8")
            artifacts.append(
                PageObjectArtifact(
                    sequence=snapshot.sequence,
                    page_name=snapshot.page_name,
                    class_name=page_spec.class_name,
                    source_html_path=snapshot.html_path,
                    output_path=str(output_path),
                    trace_path=str(trace_path),
                    attempt_count=int(page_result.get("attempt_count", 0)),
                    run_status=str(page_result.get("run_status", "unknown")),
                )
            )

        output_update = {
            "page_object_artifacts": artifacts,
            "run_status": run_status,
        }
        if failure_message:
            output_update["failure_message"] = failure_message

        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="generate_page_objects",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="generate_page_objects",
            input_state=input_state,
            output_update=output_update,
            details={
                "generated_count": len(artifacts),
                "snapshot_count": len(state["snapshots"]),
                "node_duration_ms": duration_ms(node_started, monotonic_seconds()),
            },
        )
        return {
            **output_update,
            "trace_events": trace_events,
        }

    def persist_page_object_manifest(state: PageObjectFactoryState) -> PageObjectFactoryState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        run_directories = state["run_directories"]
        page_object_manifest_path = run_directories.page_object_manifest_path
        run_manifest_path = run_directories.run_root / "run_manifest.json"

        write_json_artifact(
            page_object_manifest_path,
            {
                "artifacts": serialize_trace_value(state.get("page_object_artifacts", [])),
            },
        )

        updated_manifest = {}
        if run_manifest_path.exists():
            updated_manifest = load_json_artifact(run_manifest_path)
        updated_manifest.update(
            {
                "page_object_manifest_path": str(page_object_manifest_path),
                "page_object_factory_trace_path": str(run_directories.page_object_factory_trace_path),
                "page_object_traces_dir": str(run_directories.page_object_traces_dir),
            }
        )
        write_json_artifact(run_manifest_path, updated_manifest)

        output_update = {
            "page_object_manifest_path": page_object_manifest_path,
            "updated_manifest_path": run_manifest_path,
        }
        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="persist_page_object_manifest",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="persist_page_object_manifest",
            input_state=input_state,
            output_update=output_update,
            details={
                "artifact_count": len(state.get("page_object_artifacts", [])),
                "node_duration_ms": duration_ms(node_started, monotonic_seconds()),
            },
        )
        return {
            **output_update,
            "trace_events": trace_events,
        }

    def complete_page_object_factory(state: PageObjectFactoryState) -> PageObjectFactoryState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        output_update = {"run_status": "succeeded"}
        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="complete_page_object_factory",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="complete_page_object_factory",
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

    def fail_page_object_factory(state: PageObjectFactoryState) -> PageObjectFactoryState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        output_update = {
            "run_status": "failed",
            "failure_message": state["failure_message"],
        }
        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="fail_page_object_factory",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="fail_page_object_factory",
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
        "load_factory_context": load_factory_context,
        "generate_page_objects": generate_page_objects,
        "persist_page_object_manifest": persist_page_object_manifest,
        "complete_page_object_factory": complete_page_object_factory,
        "fail_page_object_factory": fail_page_object_factory,
    }


def _resolve_page_object_trace_path(
    *,
    run_directories,
    snapshot,
    run_status: str,
) -> Path:
    filename = f"{snapshot.sequence:02d}_{snapshot.page_name}_{run_status}.json"
    return run_directories.page_object_traces_dir / filename
