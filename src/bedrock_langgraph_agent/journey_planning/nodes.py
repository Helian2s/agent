from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import shutil
from typing import Callable

from .ingestion import load_ndjson_events
from .planner import build_journey_spec
from .state import JourneyPlanningState
from ..shared.run_artifacts import create_run_directories
from ..shared.workflow_tracing import (
    append_trace_event,
    duration_ms,
    monotonic_seconds,
    serialize_trace_value,
    snapshot_state,
)


def build_journey_nodes(
    *,
    output_root: Path | None = None,
    now_provider: Callable[[], datetime],
) -> dict[str, object]:
    def prepare_run_artifacts(state: JourneyPlanningState) -> JourneyPlanningState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        source_path = Path(state["journey_events_path"]).expanduser().resolve()
        run_directories = create_run_directories(output_root=output_root, now=now_provider())
        input_copy_path = run_directories.input_dir / source_path.name
        shutil.copy2(source_path, input_copy_path)
        output_update = {
            "run_directories": run_directories,
            "input_copy_path": input_copy_path,
        }

        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="prepare_run_artifacts",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="prepare_run_artifacts",
            input_state=input_state,
            output_update=output_update,
            details={
                "source_path": str(source_path),
                "run_root": str(run_directories.run_root),
                "node_duration_ms": duration_ms(node_started, monotonic_seconds()),
            },
        )
        return {
            **output_update,
            "trace_events": trace_events,
        }

    def load_events(state: JourneyPlanningState) -> JourneyPlanningState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        raw_events = load_ndjson_events(state["journey_events_path"])
        output_update = {"raw_events": raw_events}

        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="load_events",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="load_events",
            input_state=input_state,
            output_update=output_update,
            details={
                "event_count": len(raw_events),
                "node_duration_ms": duration_ms(node_started, monotonic_seconds()),
            },
        )
        return {
            **output_update,
            "trace_events": trace_events,
        }

    def plan_journey(state: JourneyPlanningState) -> JourneyPlanningState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        normalized_events, journey_spec = build_journey_spec(
            state["raw_events"],
            state["journey_events_path"],
        )
        output_update = {
            "normalized_events": normalized_events,
            "journey_spec": journey_spec,
        }

        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="plan_journey",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="plan_journey",
            input_state=input_state,
            output_update=output_update,
            details={
                "page_count": len(journey_spec.page_sequence),
                "unique_page_count": len(journey_spec.unique_page_urls),
                "auth_requirement": journey_spec.auth_requirement,
                "node_duration_ms": duration_ms(node_started, monotonic_seconds()),
            },
        )
        return {
            **output_update,
            "trace_events": trace_events,
        }

    def decide_auth_requirement(state: JourneyPlanningState) -> JourneyPlanningState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        journey_spec = state["journey_spec"]
        if journey_spec.auth_requirement == "not_required":
            next_node = "skip_auth_checkpoint"
        else:
            next_node = "record_auth_checkpoint"

        output_update = {"next_node": next_node}
        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="decide_auth_requirement",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="transition",
            node="decide_auth_requirement",
            input_state=input_state,
            output_update=output_update,
            details={
                "reason": journey_spec.auth_reason,
                "auth_requirement": journey_spec.auth_requirement,
                "to_node": next_node,
            },
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="decide_auth_requirement",
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

    def record_auth_checkpoint(state: JourneyPlanningState) -> JourneyPlanningState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        journey_spec = state["journey_spec"]
        if journey_spec.auth_requirement == "required":
            auth_checkpoint_status = "pending_manual_login"
            auth_checkpoint_message = (
                "Manual login is required before page capture in a later phase."
            )
        else:
            auth_checkpoint_status = "needs_manual_decision"
            auth_checkpoint_message = (
                "Authentication could not be determined from the journey events. "
                "Confirm whether manual login is needed before page capture."
            )

        output_update = {
            "auth_checkpoint_status": auth_checkpoint_status,
            "auth_checkpoint_message": auth_checkpoint_message,
        }
        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="record_auth_checkpoint",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="record_auth_checkpoint",
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

    def skip_auth_checkpoint(state: JourneyPlanningState) -> JourneyPlanningState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        output_update = {
            "auth_checkpoint_status": "skipped",
            "auth_checkpoint_message": (
                "Journey events explicitly indicate that login is not required."
            ),
        }
        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="skip_auth_checkpoint",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="skip_auth_checkpoint",
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

    def persist_journey_artifacts(state: JourneyPlanningState) -> JourneyPlanningState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        run_directories = state["run_directories"]

        normalized_events_path = run_directories.journey_dir / "normalized_events.json"
        journey_spec_path = run_directories.journey_dir / "journey_spec.json"
        auth_checkpoint_path = run_directories.journey_dir / "auth_checkpoint.json"
        manifest_path = run_directories.run_root / "run_manifest.json"

        _write_json(normalized_events_path, state["normalized_events"])
        _write_json(journey_spec_path, state["journey_spec"])
        _write_json(
            auth_checkpoint_path,
            {
                "auth_requirement": state["journey_spec"].auth_requirement,
                "auth_reason": state["journey_spec"].auth_reason,
                "auth_checkpoint_status": state["auth_checkpoint_status"],
                "auth_checkpoint_message": state["auth_checkpoint_message"],
            },
        )
        _write_json(
            manifest_path,
            {
                "run_id": run_directories.run_id,
                "source_journey_path": state["journey_events_path"],
                "copied_input_path": state["input_copy_path"],
                "journey_spec_path": journey_spec_path,
                "normalized_events_path": normalized_events_path,
                "auth_checkpoint_path": auth_checkpoint_path,
                "journey_trace_path": run_directories.journey_trace_path,
            },
        )

        output_update = {
            "normalized_events_path": normalized_events_path,
            "journey_spec_path": journey_spec_path,
            "auth_checkpoint_path": auth_checkpoint_path,
            "manifest_path": manifest_path,
        }

        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="persist_journey_artifacts",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="persist_journey_artifacts",
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

    def complete_journey_planning(state: JourneyPlanningState) -> JourneyPlanningState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        output_update = {"run_status": "succeeded"}
        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="complete_journey_planning",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="complete_journey_planning",
            input_state=input_state,
            output_update=output_update,
            details={
                "run_root": str(state["run_directories"].run_root),
                "node_duration_ms": duration_ms(node_started, monotonic_seconds()),
            },
        )
        return {
            **output_update,
            "trace_events": trace_events,
        }

    return {
        "prepare_run_artifacts": prepare_run_artifacts,
        "load_events": load_events,
        "plan_journey": plan_journey,
        "decide_auth_requirement": decide_auth_requirement,
        "record_auth_checkpoint": record_auth_checkpoint,
        "skip_auth_checkpoint": skip_auth_checkpoint,
        "persist_journey_artifacts": persist_journey_artifacts,
        "complete_journey_planning": complete_journey_planning,
    }


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(serialize_trace_value(value), indent=2),
        encoding="utf-8",
    )
