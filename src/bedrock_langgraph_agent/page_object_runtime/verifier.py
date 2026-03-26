from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..page_capture.browser import BrowserSession
from ..page_capture.models import PageSnapshot
from ..page_object_generation.policy import build_page_spec
from ..page_object_generation.verifier import (
    VerificationResult,
    collect_page_object_locators,
    verify_page_object,
)


@dataclass(frozen=True)
class RuntimeVerificationCheck:
    locator_name: str
    method_name: str
    action: str
    status: str
    detail: str


@dataclass(frozen=True)
class RuntimeVerificationResult:
    is_valid: bool
    errors: list[str]
    checks: list[RuntimeVerificationCheck]


def verify_page_object_runtime(
    code: str,
    snapshot: PageSnapshot,
    browser_session: BrowserSession,
    *,
    class_name_source: str | None = None,
) -> RuntimeVerificationResult:
    html_path = Path(snapshot.html_path).expanduser().resolve()
    html_source = html_path.read_text(encoding="utf-8")
    page_spec = build_page_spec(
        html_source,
        html_path,
        class_name_source=class_name_source or snapshot.page_name,
    )

    static_result = verify_page_object(code, page_spec)
    if not static_result.is_valid:
        return RuntimeVerificationResult(
            is_valid=False,
            errors=[f"Static verifier rejected the page object: {error}" for error in static_result.errors],
            checks=[],
        )

    locator_map = collect_page_object_locators(code, page_spec.class_name)
    snapshot_uri = html_path.as_uri()

    errors: list[str] = []
    checks: list[RuntimeVerificationCheck] = []

    for element in page_spec.elements:
        locator = locator_map.get(element.locator_name)
        if locator is None:
            errors.append(f"Runtime verifier could not find locator `{element.locator_name}` in the generated code.")
            checks.append(
                RuntimeVerificationCheck(
                    locator_name=element.locator_name,
                    method_name=element.method_name,
                    action=element.action,
                    status="failed",
                    detail="Locator constant missing from generated code.",
                )
            )
            continue

        browser_session.open(snapshot_uri)
        try:
            target = browser_session.find_element(locator[0], locator[1])
            if not target.is_displayed():
                raise RuntimeError("Element was located but is not visible.")

            if element.action in {"fill", "choose", "set", "click"} and not target.is_enabled():
                raise RuntimeError("Element was located but is disabled.")

            detail = _perform_action_check(
                browser_session=browser_session,
                target=target,
                action=element.action,
                label=element.label,
            )
            checks.append(
                RuntimeVerificationCheck(
                    locator_name=element.locator_name,
                    method_name=element.method_name,
                    action=element.action,
                    status="passed",
                    detail=detail,
                )
            )
        except Exception as exc:
            message = (
                f"Runtime verification failed for `{element.method_name}` using "
                f"`{element.locator_name}` ({locator[0]}={locator[1]!r}): {exc}"
            )
            errors.append(message)
            checks.append(
                RuntimeVerificationCheck(
                    locator_name=element.locator_name,
                    method_name=element.method_name,
                    action=element.action,
                    status="failed",
                    detail=str(exc),
                )
            )

    return RuntimeVerificationResult(is_valid=not errors, errors=errors, checks=checks)


def render_runtime_verification_feedback(result: RuntimeVerificationResult) -> str:
    if result.is_valid:
        return "Runtime verifier accepted the page object."

    lines = ["Runtime verifier rejected the page object for these reasons:"]
    for error in result.errors:
        lines.append(f"- {error}")
    return "\n".join(lines)


def _perform_action_check(
    *,
    browser_session: BrowserSession,
    target,
    action: str,
    label: str,
) -> str:
    if action == "fill":
        sample_value = _sample_text_value(label)
        target.clear()
        target.send_keys(sample_value)
        actual_value = str(target.get_attribute("value") or "")
        if actual_value != sample_value:
            raise RuntimeError(
                f"Expected filled value `{sample_value}` but the element value is `{actual_value}`."
            )
        return f"Filled value `{sample_value}`."

    if action == "choose":
        options = [
            option
            for option in browser_session.option_texts(target)
            if option and not option.lower().startswith("select ")
        ]
        if not options:
            raise RuntimeError("No selectable option text was available.")
        choice = options[0]
        browser_session.select_by_visible_text(target, choice)
        selected = browser_session.selected_text(target)
        if selected != choice:
            raise RuntimeError(
                f"Expected selected option `{choice}` but found `{selected}`."
            )
        return f"Selected option `{choice}`."

    if action == "set":
        if not target.is_selected():
            target.click()
        if not target.is_selected():
            raise RuntimeError("Checkbox remained unchecked after click.")
        return "Checkbox toggled to checked."

    if action == "click":
        target.click()
        return "Click executed without error."

    raise RuntimeError(f"Unsupported runtime action `{action}`.")


def _sample_text_value(label: str) -> str:
    lowered = label.lower()
    if "email" in lowered:
        return "proofica@example.test"
    if "name" in lowered:
        return "Proofica"
    if "note" in lowered:
        return "Generated by runtime verifier."
    return "proofica"
