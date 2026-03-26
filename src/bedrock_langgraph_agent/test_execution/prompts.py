from __future__ import annotations

import json

from ..journey_planning.models import JourneySpec
from ..page_object_factory.models import PageObjectArtifact
from ..test_authoring.models import GeneratedTestPlan
from ..shared.workflow_tracing import serialize_trace_value


TEST_REPAIR_SYSTEM_PROMPT = """You repair Python pytest Selenium end-to-end tests.
Return only valid Python code with no Markdown fences or explanations.
Keep the pytest fixture structure intact unless the failure requires a safe correction.
Use only the page object classes and methods that are provided.
Do not invent new page object files, class names, or methods.
"""


def build_test_repair_prompt(
    *,
    current_test_code: str,
    failure_feedback: str,
    generated_test_plan: GeneratedTestPlan,
    journey_spec: JourneySpec,
    page_object_artifacts: list[PageObjectArtifact],
    page_object_sources: list[tuple[PageObjectArtifact, str]],
) -> str:
    plan_json = json.dumps(serialize_trace_value(generated_test_plan), indent=2)
    journey_json = json.dumps(serialize_trace_value(journey_spec), indent=2)
    artifact_lines = [
        f"- {artifact.class_name} from {artifact.output_path}"
        for artifact in page_object_artifacts
    ]
    page_object_sections = []
    for artifact, source in page_object_sources:
        page_object_sections.append(
            f"Page object `{artifact.class_name}` from `{artifact.output_path}`:\n{source}"
        )

    sections = [
        "Available page objects:\n" + "\n".join(artifact_lines),
        "Journey spec:\n" + journey_json,
        "Generated test plan:\n" + plan_json,
        "Current test code:\n" + current_test_code,
        "Execution failure report:\n" + failure_feedback,
        (
            "Repair instructions:\n"
            "- Produce a corrected full test file, not a diff.\n"
            "- Preserve the run-relative page object loading approach.\n"
            "- Keep the driver fixture compatible with Selenium Chrome.\n"
            "- Use only methods that exist in the provided page objects.\n"
            "- Return only Python code."
        ),
        "\n\n".join(page_object_sections),
    ]
    return "\n\n".join(section for section in sections if section.strip())
