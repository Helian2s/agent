from __future__ import annotations

import json
from pathlib import Path

from ..shared.artifacts import (
    load_journey_spec,
    load_json_artifact,
    load_page_object_manifest,
    load_test_authoring_manifest,
    write_json_artifact,
)
from ..shared.llm import TextGenerator
from ..page_object_generation.nodes import extract_python_code
from ..shared.run_artifacts import load_run_directories
from ..test_authoring.models import GeneratedTestArtifact, GeneratedTestPlan, GeneratedTestStep
from ..test_authoring.verifier import verify_generated_test_module
from .models import TestExecutionArtifact, TestExecutionAttempt
from .prompts import TEST_REPAIR_SYSTEM_PROMPT, build_test_repair_prompt
from .runner import GeneratedTestRunner
from .state import TestExecutionState
from ..shared.workflow_tracing import (
    append_trace_event,
    duration_ms,
    monotonic_seconds,
    serialize_trace_value,
    snapshot_state,
    utc_now_iso,
)


NON_REPAIRABLE_FAILURE_MARKERS = (
    "No module named pytest",
    "Pytest runner could not start",
    "Pytest timed out",
    "session not created",
    "chrome not reachable",
    "ERR_NAME_NOT_RESOLVED",
    "Operation not permitted",
    "Can't find free port",
)


def build_test_execution_nodes(
    text_generator: TextGenerator,
    test_runner: GeneratedTestRunner,
) -> dict[str, object]:
    llm_trace_metadata = _get_llm_trace_metadata(text_generator)

    def load_test_execution_context(state: TestExecutionState) -> TestExecutionState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        run_directories = load_run_directories(state["run_root"])
        journey_spec = load_journey_spec(run_directories.journey_dir / "journey_spec.json")
        page_object_manifest = load_page_object_manifest(
            run_directories.page_object_manifest_path
        )
        test_authoring_manifest = load_test_authoring_manifest(
            run_directories.test_authoring_manifest_path
        )
        artifacts = list(test_authoring_manifest["artifacts"])
        if not artifacts:
            raise ValueError("Test authoring manifest does not contain any generated test artifacts.")

        generated_test_artifact = artifacts[0]
        generated_test_plan = _load_generated_test_plan(generated_test_artifact.test_plan_path)
        generated_test_code = Path(generated_test_artifact.output_path).read_text(
            encoding="utf-8"
        )

        output_update = {
            "run_directories": run_directories,
            "journey_spec": journey_spec,
            "page_object_manifest": page_object_manifest,
            "page_object_artifacts": list(page_object_manifest["artifacts"]),
            "generated_test_artifact": generated_test_artifact,
            "generated_test_plan": generated_test_plan,
            "generated_test_code": generated_test_code,
            "execution_attempts": [],
            "failure_feedback": "",
            "execution_passed": False,
            "repaired_since_last_execution": False,
        }

        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="load_test_execution_context",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="load_test_execution_context",
            input_state=input_state,
            output_update=output_update,
            details={
                "test_name": generated_test_artifact.test_name,
                "page_object_count": len(page_object_manifest["artifacts"]),
                "node_duration_ms": duration_ms(node_started, monotonic_seconds()),
            },
        )
        return {**output_update, "trace_events": trace_events}

    def execute_generated_test(state: TestExecutionState) -> TestExecutionState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        generated_test_path = Path(state["generated_test_artifact"].output_path).resolve()
        generated_test_path.write_text(state["generated_test_code"], encoding="utf-8")

        attempt_number = len(state.get("execution_attempts", [])) + 1
        run_result = test_runner.run(
            test_path=generated_test_path,
            run_root=state["run_directories"].run_root,
        )
        normalized_failure = _normalize_execution_failure(run_result)
        attempt = TestExecutionAttempt(
            attempt=attempt_number,
            command=run_result.command,
            exit_code=run_result.exit_code,
            succeeded=run_result.exit_code == 0,
            duration_ms=run_result.duration_ms,
            stdout=run_result.stdout,
            stderr=run_result.stderr,
            normalized_failure=normalized_failure,
            repaired=bool(state.get("repaired_since_last_execution", False)),
            repair_trace_path=state.get("last_repair_trace_path"),
        )

        output_update = {
            "execution_attempts": [*state.get("execution_attempts", []), attempt],
            "execution_passed": attempt.succeeded,
            "failure_feedback": "" if attempt.succeeded else normalized_failure,
            "repaired_since_last_execution": False,
            "last_repair_trace_path": "",
        }
        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="execute_generated_test",
            input_state=input_state,
            details={"attempt_number": attempt_number},
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="execute_generated_test",
            input_state=input_state,
            output_update=output_update,
            details={
                "attempt_number": attempt_number,
                "exit_code": attempt.exit_code,
                "execution_passed": attempt.succeeded,
                "duration_ms": attempt.duration_ms,
                "node_duration_ms": duration_ms(node_started, monotonic_seconds()),
            },
        )
        return {**output_update, "trace_events": trace_events}

    def choose_next_step(state: TestExecutionState) -> TestExecutionState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        attempt_count = len(state.get("execution_attempts", []))
        latest_failure = str(state.get("failure_feedback", ""))

        if state.get("execution_passed"):
            next_node = "persist_test_execution"
            reason = "execution_passed"
            output_update = {
                "next_node": next_node,
                "run_status": "succeeded",
            }
        elif not _is_repairable_failure(latest_failure):
            next_node = "persist_test_execution"
            reason = "non_repairable_failure"
            output_update = {
                "next_node": next_node,
                "run_status": "failed",
                "failure_message": (
                    "Generated pytest test failed with a non-repairable environment or setup error.\n"
                    f"{latest_failure}"
                ),
            }
        elif attempt_count >= int(state.get("max_attempts", 3)):
            next_node = "persist_test_execution"
            reason = "max_attempts_reached"
            output_update = {
                "next_node": next_node,
                "run_status": "failed",
                "failure_message": (
                    f"Generated pytest test failed after {attempt_count} execution attempts.\n"
                    f"{latest_failure}"
                ),
            }
        else:
            next_node = "repair_generated_test"
            reason = "retry_with_repair"
            output_update = {
                "next_node": next_node,
                "run_status": "running",
            }

        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="choose_next_step",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="transition",
            node="choose_next_step",
            input_state=input_state,
            output_update=output_update,
            details={
                "reason": reason,
                "from_node": "execute_generated_test",
                "to_node": next_node,
            },
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="choose_next_step",
            input_state=input_state,
            output_update=output_update,
            details={"node_duration_ms": duration_ms(node_started, monotonic_seconds())},
        )
        return {**output_update, "trace_events": trace_events}

    def repair_generated_test(state: TestExecutionState) -> TestExecutionState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        run_directories = state["run_directories"]
        attempt_count = len(state.get("execution_attempts", []))
        page_object_sources = [
            (artifact, Path(artifact.output_path).read_text(encoding="utf-8"))
            for artifact in state["page_object_artifacts"]
        ]
        user_prompt = build_test_repair_prompt(
            current_test_code=state["generated_test_code"],
            failure_feedback=state["failure_feedback"],
            generated_test_plan=state["generated_test_plan"],
            journey_spec=state["journey_spec"],
            page_object_artifacts=state["page_object_artifacts"],
            page_object_sources=page_object_sources,
        )
        llm_started_at = utc_now_iso()
        llm_wait_started = monotonic_seconds()

        try:
            generated_text = text_generator.generate(
                system_prompt=TEST_REPAIR_SYSTEM_PROMPT,
                user_prompt=user_prompt,
            )
        except Exception as exc:
            failure_message = (
                "Test repair generation failed.\n"
                f"{exc}"
            )
            output_update = {
                "run_status": "failed",
                "failure_message": failure_message,
            }
            generated_text = ""
            repaired_code = ""
        else:
            llm_wait_finished = monotonic_seconds()
            llm_finished_at = utc_now_iso()
            repaired_code = extract_python_code(generated_text)
            verification_result = verify_generated_test_module(repaired_code)
            repair_trace_path = run_directories.test_repair_traces_dir / (
                f"attempt_{attempt_count:02d}_repair.json"
            )
            write_json_artifact(
                repair_trace_path,
                {
                    "attempt": attempt_count,
                    "system_prompt": TEST_REPAIR_SYSTEM_PROMPT,
                    "user_prompt": user_prompt,
                    "raw_response_text": generated_text,
                    "repaired_code": repaired_code,
                    "verification": serialize_trace_value(verification_result),
                },
            )

            if verification_result.is_valid:
                Path(state["generated_test_artifact"].output_path).write_text(
                    repaired_code,
                    encoding="utf-8",
                )
                output_update = {
                    "generated_test_code": repaired_code,
                    "run_status": "running",
                    "repaired_since_last_execution": True,
                    "last_repair_trace_path": str(repair_trace_path),
                }
            else:
                output_update = {
                    "run_status": "failed",
                    "failure_message": (
                        "Generated test repair failed verification.\n"
                        + "\n".join(f"- {error}" for error in verification_result.errors)
                        + f"\nRepair trace: {repair_trace_path}"
                    ),
                    "last_repair_trace_path": str(repair_trace_path),
                }

        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="repair_generated_test",
            input_state=input_state,
            details={"attempt_number": attempt_count},
        )
        if generated_text:
            trace_events = append_trace_event(
                {**state, "trace_events": trace_events},
                event_type="llm_call",
                node="repair_generated_test",
                input_state=input_state,
                output_update=output_update,
                details={
                    **llm_trace_metadata,
                    "llm_started_at": llm_started_at,
                    "llm_finished_at": llm_finished_at,
                    "llm_wait_ms": duration_ms(llm_wait_started, llm_wait_finished),
                    "system_prompt": TEST_REPAIR_SYSTEM_PROMPT,
                    "user_prompt": user_prompt,
                    "raw_response_text": generated_text,
                    "normalized_code": repaired_code,
                },
            )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="repair_generated_test",
            input_state=input_state,
            output_update=output_update,
            details={"node_duration_ms": duration_ms(node_started, monotonic_seconds())},
        )
        return {**output_update, "trace_events": trace_events}

    def persist_test_execution(state: TestExecutionState) -> TestExecutionState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        run_directories = state["run_directories"]
        run_manifest_path = run_directories.run_root / "run_manifest.json"
        attempts = list(state.get("execution_attempts", []))
        latest_exit_code = attempts[-1].exit_code if attempts else 1
        errors = [state["failure_message"]] if state.get("run_status") == "failed" else []

        test_execution_artifact = TestExecutionArtifact(
            test_name=state["generated_test_artifact"].test_name,
            output_path=state["generated_test_artifact"].output_path,
            execution_report_path=str(run_directories.test_execution_report_path),
            trace_path=str(run_directories.test_execution_trace_path),
            repair_traces_dir=str(run_directories.test_repair_traces_dir),
            attempt_count=len(attempts),
            last_exit_code=latest_exit_code,
            run_status=str(state.get("run_status", "unknown")),
            errors=errors,
        )

        write_json_artifact(
            run_directories.test_execution_report_path,
            {
                "test_name": state["generated_test_artifact"].test_name,
                "run_status": state.get("run_status", "unknown"),
                "attempts": serialize_trace_value(attempts),
                "failure_message": state.get("failure_message", ""),
            },
        )
        write_json_artifact(
            run_directories.test_execution_manifest_path,
            {"artifacts": serialize_trace_value([test_execution_artifact])},
        )

        updated_manifest = {}
        if run_manifest_path.exists():
            updated_manifest = load_json_artifact(run_manifest_path)
        updated_manifest.update(
            {
                "test_execution_report_path": str(run_directories.test_execution_report_path),
                "test_execution_manifest_path": str(run_directories.test_execution_manifest_path),
                "test_execution_trace_path": str(run_directories.test_execution_trace_path),
                "test_repair_traces_dir": str(run_directories.test_repair_traces_dir),
            }
        )
        write_json_artifact(run_manifest_path, updated_manifest)

        output_update = {
            "test_execution_artifact": test_execution_artifact,
            "test_execution_report_path": str(run_directories.test_execution_report_path),
            "test_execution_manifest_path": str(run_directories.test_execution_manifest_path),
            "updated_manifest_path": str(run_manifest_path),
        }
        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="persist_test_execution",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="persist_test_execution",
            input_state=input_state,
            output_update=output_update,
            details={
                "attempt_count": len(attempts),
                "run_status": state.get("run_status", "unknown"),
                "node_duration_ms": duration_ms(node_started, monotonic_seconds()),
            },
        )
        return {**output_update, "trace_events": trace_events}

    def complete_test_execution(state: TestExecutionState) -> TestExecutionState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        output_update = {"run_status": "succeeded"}
        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="complete_test_execution",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="complete_test_execution",
            input_state=input_state,
            output_update=output_update,
            details={"node_duration_ms": duration_ms(node_started, monotonic_seconds())},
        )
        return {**output_update, "trace_events": trace_events}

    def fail_test_execution(state: TestExecutionState) -> TestExecutionState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        output_update = {
            "run_status": "failed",
            "failure_message": state["failure_message"],
        }
        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="fail_test_execution",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="fail_test_execution",
            input_state=input_state,
            output_update=output_update,
            details={"node_duration_ms": duration_ms(node_started, monotonic_seconds())},
        )
        return {**output_update, "trace_events": trace_events}

    return {
        "load_test_execution_context": load_test_execution_context,
        "execute_generated_test": execute_generated_test,
        "choose_next_step": choose_next_step,
        "repair_generated_test": repair_generated_test,
        "persist_test_execution": persist_test_execution,
        "complete_test_execution": complete_test_execution,
        "fail_test_execution": fail_test_execution,
    }


def _load_generated_test_plan(path: str | Path) -> GeneratedTestPlan:
    data = load_json_artifact(path)
    steps = [
        GeneratedTestStep(
            sequence=int(step["sequence"]),
            step_type=str(step["step_type"]),
            source=str(step["source"]),
            page_name=str(step["page_name"]),
            description=str(step["description"]),
            variable_name=_optional_string(step.get("variable_name")),
            url=_optional_string(step.get("url")),
            page_title=_optional_string(step.get("page_title")),
            class_name=_optional_string(step.get("class_name")),
            page_object_relative_path=_optional_string(step.get("page_object_relative_path")),
            method_name=_optional_string(step.get("method_name")),
            method_action=_optional_string(step.get("method_action")),
            args=list(step.get("args", [])),
            scroll_fraction=(
                float(step["scroll_fraction"])
                if step.get("scroll_fraction") is not None
                else None
            ),
        )
        for step in data.get("steps", [])
    ]
    return GeneratedTestPlan(
        test_name=str(data["test_name"]),
        page_count=int(data["page_count"]),
        step_count=int(data["step_count"]),
        steps=steps,
    )


def _normalize_execution_failure(run_result) -> str:
    combined = "\n".join(
        part for part in [run_result.stdout.strip(), run_result.stderr.strip()] if part
    ).strip()
    if not combined:
        return f"Pytest failed with exit code {run_result.exit_code} and produced no output."

    lines = combined.splitlines()
    interesting_lines = [
        line
        for line in lines
        if line.startswith("E   ")
        or line.startswith("FAILED ")
        or "Traceback" in line
        or "AssertionError" in line
        or "Exception" in line
        or "Error" in line
        or "No module named" in line
    ]
    excerpt = interesting_lines[-20:] if interesting_lines else lines[-40:]
    return (
        f"Pytest exit code: {run_result.exit_code}\n"
        f"Command: {' '.join(run_result.command)}\n"
        "Relevant output:\n"
        + "\n".join(excerpt)
    )


def _is_repairable_failure(failure_feedback: str) -> bool:
    if not failure_feedback.strip():
        return False
    lowered = failure_feedback.lower()
    if any(marker.lower() in lowered for marker in NON_REPAIRABLE_FAILURE_MARKERS):
        return False
    return True


def _optional_string(value) -> str | None:
    if value is None:
        return None
    return str(value)


def _get_llm_trace_metadata(text_generator: TextGenerator) -> dict[str, str]:
    get_trace_metadata = getattr(text_generator, "get_trace_metadata", None)
    if callable(get_trace_metadata):
        metadata = get_trace_metadata()
        if isinstance(metadata, dict):
            return {str(key): str(value) for key, value in metadata.items()}
    return {}
