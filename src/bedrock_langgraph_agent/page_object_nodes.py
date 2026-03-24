from __future__ import annotations

from pathlib import Path

from .llm import TextGenerator
from .page_object_policy import (
    DEFAULT_PAGE_OBJECT_POLICY,
    PageObjectGenerationPolicy,
    build_page_spec,
)
from .page_object_prompts import PAGE_OBJECT_SYSTEM_PROMPT, build_generation_prompt
from .page_object_state import PageObjectState
from .page_object_tracing import append_trace_event, snapshot_state
from .page_object_verifier import render_verification_feedback, verify_page_object


def build_page_object_nodes(
    text_generator: TextGenerator,
    policy: PageObjectGenerationPolicy = DEFAULT_PAGE_OBJECT_POLICY,
) -> dict[str, object]:
    def plan_page_object(state: PageObjectState) -> PageObjectState:
        input_state = snapshot_state(state)
        html_path = Path(state["html_path"]).expanduser().resolve()
        html_source = html_path.read_text(encoding="utf-8")
        page_spec = build_page_spec(html_source, html_path, policy)
        output_update = {
            "page_spec": page_spec,
            "attempt_count": 0,
            "max_attempts": int(state.get("max_attempts", policy.max_attempts)),
            "verification_feedback": "",
            "verification_errors": [],
            "run_status": "running",
        }
        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="plan_page_object",
            input_state=input_state,
            details={"policy": policy},
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="plan_page_object",
            input_state=input_state,
            output_update=output_update,
            details={
                "html_path": str(html_path),
                "html_length": len(html_source),
            },
        )
        return {
            **output_update,
            "trace_events": trace_events,
        }

    def generate_page_object(state: PageObjectState) -> PageObjectState:
        input_state = snapshot_state(state)
        user_prompt = build_generation_prompt(
            page_spec=state["page_spec"],
            verifier_feedback=state.get("verification_feedback", ""),
            policy=policy,
        )
        generated_text = text_generator.generate(
            system_prompt=PAGE_OBJECT_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
        generated_code = extract_python_code(generated_text)
        output_update = {
            "generated_code": generated_code,
            "attempt_count": int(state.get("attempt_count", 0)) + 1,
        }
        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="generate_page_object",
            input_state=input_state,
            details={
                "attempt_number": int(state.get("attempt_count", 0)) + 1,
            },
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="llm_call",
            node="generate_page_object",
            input_state=input_state,
            output_update=output_update,
            details={
                "system_prompt": PAGE_OBJECT_SYSTEM_PROMPT,
                "user_prompt": user_prompt,
                "raw_response_text": generated_text,
                "normalized_code": generated_code,
            },
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="generate_page_object",
            input_state=input_state,
            output_update=output_update,
        )
        return {
            **output_update,
            "trace_events": trace_events,
        }

    def verify_generated_page_object(state: PageObjectState) -> PageObjectState:
        input_state = snapshot_state(state)
        result = verify_page_object(state["generated_code"], state["page_spec"])
        feedback = render_verification_feedback(result)
        if result.is_valid:
            output_update = {
                "verification_passed": True,
                "verification_feedback": feedback,
                "verification_errors": [],
                "final_page_object": state["generated_code"],
            }
        else:
            output_update = {
                "verification_passed": False,
                "verification_feedback": feedback,
                "verification_errors": result.errors,
            }
        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="verify_generated_page_object",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="verify_generated_page_object",
            input_state=input_state,
            output_update=output_update,
            details={
                "verification_passed": result.is_valid,
                "verification_errors": result.errors,
            },
        )
        return {
            **output_update,
            "trace_events": trace_events,
        }

    def choose_next_step(state: PageObjectState) -> PageObjectState:
        input_state = snapshot_state(state)
        if state.get("verification_passed"):
            next_node = "complete_page_object"
            reason = "verification_passed"
        elif int(state.get("attempt_count", 0)) >= int(state.get("max_attempts", 0)):
            next_node = "fail_generation"
            reason = "max_attempts_reached"
        else:
            next_node = "generate_page_object"
            reason = "retry_after_verifier_feedback"

        output_update = {"next_node": next_node}
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
                "from_node": "verify_generated_page_object",
                "to_node": next_node,
            },
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="choose_next_step",
            input_state=input_state,
            output_update=output_update,
        )
        return {
            **output_update,
            "trace_events": trace_events,
        }

    def complete_page_object(state: PageObjectState) -> PageObjectState:
        input_state = snapshot_state(state)
        output_update = {"run_status": "succeeded"}
        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="complete_page_object",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="complete_page_object",
            input_state=input_state,
            output_update=output_update,
            details={
                "final_page_object_length": len(state.get("final_page_object", "")),
            },
        )
        return {
            **output_update,
            "trace_events": trace_events,
        }

    def fail_generation(state: PageObjectState) -> PageObjectState:
        input_state = snapshot_state(state)
        failure_message = (
            "Page object verification failed after "
            f"{state['attempt_count']} attempts.\n{state['verification_feedback']}"
        )
        output_update = {
            "run_status": "failed",
            "failure_message": failure_message,
        }
        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="fail_generation",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="fail_generation",
            input_state=input_state,
            output_update=output_update,
            details={"failure_message": failure_message},
        )
        return {
            **output_update,
            "trace_events": trace_events,
        }

    return {
        "plan_page_object": plan_page_object,
        "generate_page_object": generate_page_object,
        "verify_generated_page_object": verify_generated_page_object,
        "choose_next_step": choose_next_step,
        "complete_page_object": complete_page_object,
        "fail_generation": fail_generation,
    }


def extract_python_code(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return stripped
