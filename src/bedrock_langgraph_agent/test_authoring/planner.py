from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import re
from typing import Any

from ..shared.artifacts import load_json_artifact
from ..journey_planning.models import JourneyAction, JourneyPage, JourneySpec
from ..page_capture.models import PageSnapshot
from ..page_object_factory.models import PageObjectArtifact
from ..page_object_runtime.models import RuntimeVerificationArtifact
from .models import GeneratedTestPlan, GeneratedTestStep


def build_generated_test_plan(
    *,
    run_root: Path,
    journey_spec: JourneySpec,
    snapshots: list[PageSnapshot],
    page_object_artifacts: list[PageObjectArtifact],
    runtime_verification_artifacts: list[RuntimeVerificationArtifact],
) -> GeneratedTestPlan:
    snapshot_by_page_name = {snapshot.page_name: snapshot for snapshot in snapshots}
    page_object_by_page_name = {
        artifact.page_name: artifact for artifact in page_object_artifacts
    }
    runtime_artifact_by_page_name = {
        artifact.page_name: artifact for artifact in runtime_verification_artifacts
        if artifact.run_status == "succeeded"
    }

    draft_steps: list[GeneratedTestStep] = []

    for page in journey_spec.page_sequence:
        snapshot = snapshot_by_page_name.get(page.page_name)
        if snapshot is None:
            raise ValueError(f"Missing captured snapshot for page `{page.page_name}`.")

        page_object_artifact = page_object_by_page_name.get(page.page_name)
        if page_object_artifact is None:
            raise ValueError(f"Missing page object artifact for page `{page.page_name}`.")

        runtime_artifact = runtime_artifact_by_page_name.get(page.page_name)
        if runtime_artifact is None:
            raise ValueError(
                f"Missing successful runtime verification artifact for page `{page.page_name}`."
            )

        verification_report = load_json_artifact(runtime_artifact.verification_report_path)
        runtime_checks = [
            check
            for check in verification_report.get("checks", [])
            if str(check.get("status", "")).lower() == "passed"
        ]
        if not runtime_checks:
            raise ValueError(
                f"Runtime verification report for `{page.page_name}` has no successful checks."
            )

        page_object_relative_path = str(
            Path(page_object_artifact.output_path).resolve().relative_to(run_root)
        )
        page_variable = f"page_{page.sequence}"

        draft_steps.append(
            GeneratedTestStep(
                sequence=0,
                step_type="open_page",
                source="journey",
                page_name=page.page_name,
                description=f"Open `{page.url}` and instantiate `{page_object_artifact.class_name}`.",
                variable_name=page_variable,
                url=page.url,
                page_title=snapshot.title,
                class_name=page_object_artifact.class_name,
                page_object_relative_path=page_object_relative_path,
            )
        )

        page_steps = _build_page_steps(
            page=page,
            page_variable=page_variable,
            runtime_checks=runtime_checks,
        )
        draft_steps.extend(page_steps)

    steps = [
        replace(step, sequence=index)
        for index, step in enumerate(draft_steps, start=1)
    ]
    return GeneratedTestPlan(
        test_name="test_generated_journey",
        page_count=len(journey_spec.page_sequence),
        step_count=len(steps),
        steps=steps,
    )


def _build_page_steps(
    *,
    page: JourneyPage,
    page_variable: str,
    runtime_checks: list[dict[str, Any]],
) -> list[GeneratedTestStep]:
    journey_steps: list[GeneratedTestStep] = []

    for action in page.actions:
        if action.action_type == "navigation":
            continue
        if action.action_type == "scroll":
            journey_steps.append(
                GeneratedTestStep(
                    sequence=0,
                    step_type="scroll",
                    source="journey",
                    page_name=page.page_name,
                    description=action.description,
                    scroll_fraction=_scroll_fraction(action.scroll_depth),
                )
            )
            continue

        matched_check = _match_action_to_runtime_check(action, runtime_checks)
        if matched_check is None:
            continue

        journey_steps.append(
            GeneratedTestStep(
                sequence=0,
                step_type="page_object_call",
                source="journey",
                page_name=page.page_name,
                description=action.description,
                variable_name=page_variable,
                method_name=str(matched_check["method_name"]),
                method_action=str(matched_check["action"]),
                args=_resolve_call_args(action, matched_check),
            )
        )

    if journey_steps:
        return journey_steps

    return [
        GeneratedTestStep(
            sequence=0,
            step_type="page_object_call",
            source="runtime_fallback",
            page_name=page.page_name,
            description=(
                "Fallback smoke action derived from runtime verification: "
                f"{check['method_name']}."
            ),
            variable_name=page_variable,
            method_name=str(check["method_name"]),
            method_action=str(check["action"]),
            args=_sample_args_from_runtime_check(check),
        )
        for check in runtime_checks
    ]


def _match_action_to_runtime_check(
    action: JourneyAction,
    runtime_checks: list[dict[str, Any]],
) -> dict[str, Any] | None:
    candidate_checks = [
        check
        for check in runtime_checks
        if _action_type_matches_runtime_check(action.action_type, str(check.get("action", "")))
    ]
    if not candidate_checks:
        return None

    target_slug = _normalize_phrase(action.target or action.description)
    if not target_slug:
        return candidate_checks[0] if len(candidate_checks) == 1 else None

    scored_candidates: list[tuple[int, dict[str, Any]]] = []
    for check in candidate_checks:
        method_slug = _runtime_check_slug(str(check.get("method_name", "")))
        locator_slug = _normalize_phrase(str(check.get("locator_name", "")))
        score = _match_score(target_slug, method_slug) + _match_score(target_slug, locator_slug)
        if action.action_type == "text_input" and str(check.get("action", "")) == "fill":
            score += 1
        if action.action_type == "click" and str(check.get("action", "")) == "click":
            score += 1
        if score > 0:
            scored_candidates.append((score, check))

    if not scored_candidates:
        return candidate_checks[0] if len(candidate_checks) == 1 else None

    scored_candidates.sort(key=lambda item: item[0], reverse=True)
    return scored_candidates[0][1]


def _resolve_call_args(action: JourneyAction, runtime_check: dict[str, Any]) -> list[Any]:
    runtime_action = str(runtime_check.get("action", ""))
    if action.action_type == "text_input" and action.value is not None:
        return [action.value]
    if runtime_action == "set":
        return [True]
    return _sample_args_from_runtime_check(runtime_check)


def _sample_args_from_runtime_check(runtime_check: dict[str, Any]) -> list[Any]:
    action = str(runtime_check.get("action", ""))
    detail = str(runtime_check.get("detail", ""))
    if action in {"fill", "choose"}:
        match = re.search(r"`([^`]+)`", detail)
        if match:
            return [match.group(1)]
        return ["proofica"] if action == "fill" else [""]
    if action == "set":
        return [True]
    return []


def _scroll_fraction(scroll_depth: float | None) -> float:
    if scroll_depth is None:
        return 0.5
    return max(0.0, min(1.0, round(scroll_depth / 100.0, 3)))


def _action_type_matches_runtime_check(action_type: str, runtime_action: str) -> bool:
    if action_type == "text_input":
        return runtime_action in {"fill", "choose"}
    if action_type == "click":
        return runtime_action in {"click", "set"}
    return False


def _runtime_check_slug(method_name: str) -> str:
    slug = _normalize_phrase(method_name)
    for prefix in ("fill_", "choose_", "set_", "click_"):
        if slug.startswith(prefix):
            return slug.removeprefix(prefix)
    return slug


def _match_score(target_slug: str, candidate_slug: str) -> int:
    if not target_slug or not candidate_slug:
        return 0
    if target_slug == candidate_slug:
        return 10
    if target_slug in candidate_slug or candidate_slug in target_slug:
        return 6

    target_tokens = set(target_slug.split("_"))
    candidate_tokens = set(candidate_slug.split("_"))
    return len(target_tokens & candidate_tokens)


def _normalize_phrase(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower())
    normalized = re.sub(r"_+", "_", normalized)
    return normalized.strip("_")
