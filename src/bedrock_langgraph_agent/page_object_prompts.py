from __future__ import annotations

from .page_object_policy import (
    DEFAULT_PAGE_OBJECT_POLICY,
    PageObjectGenerationPolicy,
    PageSpec,
    render_page_spec,
    render_policy_summary,
)


PAGE_OBJECT_SYSTEM_PROMPT = """You generate Python Selenium page objects.
Follow the deterministic policy and element contract exactly.
Return only Python code. Do not include Markdown fences or explanations.
Do not invent new locators, methods, or class names.
"""


def build_generation_prompt(
    *,
    page_spec: PageSpec,
    verifier_feedback: str,
    policy: PageObjectGenerationPolicy = DEFAULT_PAGE_OBJECT_POLICY,
) -> str:
    sections = [
        render_policy_summary(policy),
        render_page_spec(page_spec),
        (
            "Required implementation style:\n"
            "- Use class-level locator constants exactly as specified.\n"
            "- Use `self.driver.find_element(*self.LOCATOR)` in methods.\n"
            "- `fill_*` methods must clear and send keys.\n"
            "- `choose_*` methods must use `Select(...).select_by_visible_text(value)`.\n"
            "- `set_*` methods must click only when the current checkbox state differs from `checked`.\n"
            "- `click_*` methods must click the element.\n"
            "- Return only Python code."
        ),
    ]

    if verifier_feedback:
        sections.append(
            "Repair instructions from the verifier:\n"
            f"{verifier_feedback}\n"
            "Produce a corrected full file, not a diff."
        )

    return "\n\n".join(sections)
