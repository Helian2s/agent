from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Callable

from .journey_artifacts import load_json_artifact, load_journey_spec, write_json_artifact
from .journey_models import JourneyPage, JourneySpec
from .page_capture_browser import BrowserSession
from .page_capture_models import ActionableElement, PageSnapshot
from .page_capture_state import PageCaptureState
from .run_artifacts import load_run_directories
from .workflow_tracing import (
    append_trace_event,
    duration_ms,
    monotonic_seconds,
    serialize_trace_value,
    snapshot_state,
)


LoginHandler = Callable[[BrowserSession, JourneySpec, dict[str, object]], None]


def build_page_capture_nodes(
    browser_session: BrowserSession,
    *,
    login_handler: LoginHandler | None = None,
) -> dict[str, object]:
    capture_login_handler = login_handler or prompt_for_manual_login

    def load_capture_context(state: PageCaptureState) -> PageCaptureState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        run_directories = load_run_directories(state["run_root"])
        journey_spec = load_journey_spec(run_directories.journey_dir / "journey_spec.json")
        auth_checkpoint = load_json_artifact(run_directories.journey_dir / "auth_checkpoint.json")
        output_update = {
            "run_directories": run_directories,
            "journey_spec": journey_spec,
            "auth_checkpoint": auth_checkpoint,
        }

        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="load_capture_context",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="load_capture_context",
            input_state=input_state,
            output_update=output_update,
            details={
                "run_root": str(run_directories.run_root),
                "unique_page_count": len(journey_spec.unique_page_urls),
                "auth_requirement": journey_spec.auth_requirement,
                "node_duration_ms": duration_ms(node_started, monotonic_seconds()),
            },
        )
        return {
            **output_update,
            "trace_events": trace_events,
        }

    def maybe_authenticate_session(state: PageCaptureState) -> PageCaptureState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        journey_spec = state["journey_spec"]
        auth_checkpoint = state["auth_checkpoint"]
        auth_status = str(auth_checkpoint.get("auth_checkpoint_status", "skipped"))

        if auth_status == "skipped":
            output_update = {
                "auth_session_status": "skipped",
                "auth_session_message": str(auth_checkpoint.get("auth_checkpoint_message", "")),
            }
        else:
            entry_url = journey_spec.page_sequence[0].url if journey_spec.page_sequence else None
            if entry_url:
                browser_session.open(entry_url)
            capture_login_handler(browser_session, journey_spec, auth_checkpoint)
            output_update = {
                "auth_session_status": "manual_login_confirmed",
                "auth_session_message": str(auth_checkpoint.get("auth_checkpoint_message", "")),
            }

        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="maybe_authenticate_session",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="maybe_authenticate_session",
            input_state=input_state,
            output_update=output_update,
            details={
                "auth_checkpoint_status": auth_status,
                "node_duration_ms": duration_ms(node_started, monotonic_seconds()),
            },
        )
        return {
            **output_update,
            "trace_events": trace_events,
        }

    def capture_pages(state: PageCaptureState) -> PageCaptureState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        run_directories = state["run_directories"]
        journey_spec = state["journey_spec"]
        page_snapshots: list[PageSnapshot] = []

        for capture_sequence, page in enumerate(_capture_targets(journey_spec), start=1):
            browser_session.open(page.url)
            page_dir = run_directories.pages_dir / f"{capture_sequence:02d}_{page.page_name}"
            page_dir.mkdir(parents=True, exist_ok=True)

            html_path = page_dir / "snapshot.html"
            screenshot_path = page_dir / "screenshot.png"
            elements_path = page_dir / "actionable_elements.json"

            html_path.write_text(browser_session.page_source(), encoding="utf-8")
            browser_session.save_screenshot(screenshot_path)
            actionable_elements = browser_session.list_actionable_elements()
            write_json_artifact(
                elements_path,
                serialize_trace_value(actionable_elements),
            )

            page_snapshots.append(
                PageSnapshot(
                    sequence=capture_sequence,
                    journey_page_sequence=page.sequence,
                    page_name=page.page_name,
                    requested_url=page.url,
                    final_url=browser_session.current_url(),
                    title=browser_session.title(),
                    html_path=str(html_path),
                    screenshot_path=str(screenshot_path),
                    elements_path=str(elements_path),
                    actionable_elements=actionable_elements,
                )
            )

        output_update = {"page_snapshots": page_snapshots}
        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="capture_pages",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="capture_pages",
            input_state=input_state,
            output_update=output_update,
            details={
                "captured_page_count": len(page_snapshots),
                "node_duration_ms": duration_ms(node_started, monotonic_seconds()),
            },
        )
        return {
            **output_update,
            "trace_events": trace_events,
        }

    def persist_capture_manifest(state: PageCaptureState) -> PageCaptureState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        run_directories = state["run_directories"]
        page_capture_manifest_path = run_directories.page_capture_manifest_path
        run_manifest_path = run_directories.run_root / "run_manifest.json"

        write_json_artifact(
            page_capture_manifest_path,
            {
                "auth_session_status": state["auth_session_status"],
                "snapshots": serialize_trace_value(state["page_snapshots"]),
            },
        )

        updated_manifest = {}
        if run_manifest_path.exists():
            updated_manifest = load_json_artifact(run_manifest_path)
        updated_manifest.update(
            {
                "page_capture_manifest_path": str(page_capture_manifest_path),
                "page_capture_trace_path": str(run_directories.page_capture_trace_path),
            }
        )
        write_json_artifact(run_manifest_path, updated_manifest)

        output_update = {
            "page_capture_manifest_path": page_capture_manifest_path,
            "updated_manifest_path": run_manifest_path,
        }
        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="persist_capture_manifest",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="persist_capture_manifest",
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

    def complete_page_capture(state: PageCaptureState) -> PageCaptureState:
        node_started = monotonic_seconds()
        input_state = snapshot_state(state)
        output_update = {"run_status": "succeeded"}
        trace_events = append_trace_event(
            state,
            event_type="node_enter",
            node="complete_page_capture",
            input_state=input_state,
        )
        trace_events = append_trace_event(
            {**state, "trace_events": trace_events},
            event_type="node_exit",
            node="complete_page_capture",
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
        "load_capture_context": load_capture_context,
        "maybe_authenticate_session": maybe_authenticate_session,
        "capture_pages": capture_pages,
        "persist_capture_manifest": persist_capture_manifest,
        "complete_page_capture": complete_page_capture,
    }


def prompt_for_manual_login(
    browser_session: BrowserSession,
    journey_spec: JourneySpec,
    auth_checkpoint: dict[str, object],
) -> None:
    message = str(
        auth_checkpoint.get(
            "auth_checkpoint_message",
            "Manual login is required before continuing.",
        )
    )
    prompt = (
        f"{message}\n"
        "Complete the login flow in the opened browser window, then press Enter to continue."
    )
    input(prompt)


def _capture_targets(journey_spec: JourneySpec) -> list[JourneyPage]:
    targets: list[JourneyPage] = []
    seen_urls: set[str] = set()
    for page in journey_spec.page_sequence:
        if page.url in seen_urls:
            continue
        seen_urls.add(page.url)
        targets.append(page)
    return targets
