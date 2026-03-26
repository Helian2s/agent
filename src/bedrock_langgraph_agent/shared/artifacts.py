from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..journey_planning.models import JourneyAction, JourneyPage, JourneySpec
from ..page_capture.models import ActionableElement, PageSnapshot
from ..page_object_factory.models import PageObjectArtifact
from ..page_object_runtime.models import RuntimeVerificationArtifact
from ..test_authoring.models import GeneratedTestArtifact


def load_json_artifact(path: str | Path) -> dict[str, Any]:
    artifact_path = Path(path).expanduser().resolve()
    with artifact_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object in {artifact_path}.")

    return data


def load_journey_spec(path: str | Path) -> JourneySpec:
    data = load_json_artifact(path)
    page_sequence = [
        JourneyPage(
            sequence=int(page["sequence"]),
            url=str(page["url"]),
            page_name=str(page["page_name"]),
            entry_timestamp=str(page["entry_timestamp"]),
            exit_timestamp=str(page["exit_timestamp"]),
            event_count=int(page["event_count"]),
            actions=[
                JourneyAction(
                    source_event_sequence=int(action["source_event_sequence"]),
                    timestamp=str(action["timestamp"]),
                    action_type=str(action["action_type"]),
                    description=str(action["description"]),
                    target=_optional_string(action.get("target")),
                    value=_optional_string(action.get("value")),
                    navigation_source=_optional_string(action.get("navigation_source")),
                    scroll_depth=(
                        float(action["scroll_depth"])
                        if action.get("scroll_depth") is not None
                        else None
                    ),
                )
                for action in page.get("actions", [])
            ],
        )
        for page in data.get("page_sequence", [])
    ]

    return JourneySpec(
        source_path=str(data["source_path"]),
        site_host=str(data["site_host"]),
        total_events=int(data["total_events"]),
        started_at=str(data["started_at"]),
        ended_at=str(data["ended_at"]),
        auth_requirement=str(data["auth_requirement"]),
        auth_reason=str(data["auth_reason"]),
        page_sequence=page_sequence,
        unique_page_urls=[str(url) for url in data.get("unique_page_urls", [])],
    )


def write_json_artifact(path: str | Path, value: Any) -> Path:
    artifact_path = Path(path)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(value, indent=2), encoding="utf-8")
    return artifact_path


def load_page_capture_manifest(path: str | Path) -> dict[str, Any]:
    data = load_json_artifact(path)
    snapshots = [
        PageSnapshot(
            sequence=int(snapshot["sequence"]),
            journey_page_sequence=int(snapshot["journey_page_sequence"]),
            page_name=str(snapshot["page_name"]),
            requested_url=str(snapshot["requested_url"]),
            final_url=str(snapshot["final_url"]),
            title=str(snapshot["title"]),
            html_path=str(snapshot["html_path"]),
            screenshot_path=str(snapshot["screenshot_path"]),
            elements_path=str(snapshot["elements_path"]),
            actionable_elements=[
                ActionableElement(
                    sequence=int(element["sequence"]),
                    tag_name=str(element["tag_name"]),
                    text=str(element["text"]),
                    attributes={
                        str(key): str(value)
                        for key, value in element.get("attributes", {}).items()
                    },
                    is_visible=bool(element.get("is_visible", True)),
                    is_enabled=bool(element.get("is_enabled", True)),
                )
                for element in snapshot.get("actionable_elements", [])
            ],
        )
        for snapshot in data.get("snapshots", [])
    ]
    return {
        "auth_session_status": str(data.get("auth_session_status", "")),
        "snapshots": snapshots,
    }


def load_page_object_manifest(path: str | Path) -> dict[str, Any]:
    data = load_json_artifact(path)
    artifacts = [
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
        for artifact in data.get("artifacts", [])
    ]
    return {"artifacts": artifacts}


def load_runtime_verification_manifest(path: str | Path) -> dict[str, Any]:
    data = load_json_artifact(path)
    artifacts = [
        RuntimeVerificationArtifact(
            sequence=int(artifact["sequence"]),
            page_name=str(artifact["page_name"]),
            output_path=str(artifact["output_path"]),
            trace_path=str(artifact["trace_path"]),
            verification_report_path=str(artifact["verification_report_path"]),
            runtime_attempt_count=int(artifact["runtime_attempt_count"]),
            run_status=str(artifact["run_status"]),
            errors=[str(error) for error in artifact.get("errors", [])],
        )
        for artifact in data.get("artifacts", [])
    ]
    return {"artifacts": artifacts}


def load_test_authoring_manifest(path: str | Path) -> dict[str, Any]:
    data = load_json_artifact(path)
    artifacts = [
        GeneratedTestArtifact(
            test_name=str(artifact["test_name"]),
            output_path=str(artifact["output_path"]),
            test_plan_path=str(artifact["test_plan_path"]),
            trace_path=str(artifact["trace_path"]),
            page_count=int(artifact["page_count"]),
            step_count=int(artifact["step_count"]),
            run_status=str(artifact["run_status"]),
        )
        for artifact in data.get("artifacts", [])
    ]
    return {"artifacts": artifacts}


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
