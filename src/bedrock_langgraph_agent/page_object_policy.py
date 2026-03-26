from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
import re
from typing import TypedDict

INTERACTIVE_TAGS = {"input", "textarea", "select", "button"}
TEXT_INPUT_TYPES = {
    "",
    "email",
    "number",
    "password",
    "search",
    "tel",
    "text",
    "url",
}


@dataclass(frozen=True)
class PageObjectGenerationPolicy:
    class_suffix: str
    selector_priority: tuple[str, ...]
    planning_steps: tuple[str, ...]
    max_attempts: int


@dataclass(frozen=True)
class ElementSpec:
    label: str
    tag: str
    input_type: str
    locator_name: str
    by_member: str
    selector_value: str
    selector_source: str
    method_name: str
    action: str
    method_signature: str


@dataclass(frozen=True)
class PageSpec:
    source_path: Path
    class_name: str
    page_title: str
    elements: list[ElementSpec]


DEFAULT_PAGE_OBJECT_POLICY = PageObjectGenerationPolicy(
    class_suffix="Page",
    selector_priority=(
        "data-testid",
        "id",
        "name",
        "aria-label",
        "button-text",
    ),
    planning_steps=(
        "Use the exact class name from the deterministic planner.",
        "Import `By` from `selenium.webdriver.common.by`.",
        "Import `Select` from `selenium.webdriver.support.ui` when the planned elements include a `<select>`.",
        "Define one class-level locator constant for every planned element using the exact locator name and selector.",
        "Implement `__init__(self, driver)` and store `self.driver = driver`.",
        "Generate one method per planned element using the exact method name and signature from the plan.",
        "`fill_*` methods must clear the element before `send_keys`.",
        "`choose_*` methods must use `Select(...).select_by_visible_text(value)`.",
        "`set_*` methods must compare the checkbox state and click only when needed.",
        "`click_*` methods must click the element directly.",
        "Return only valid Python code with no Markdown fences.",
    ),
    max_attempts=3,
)


class RawElement(TypedDict):
    tag: str
    attrs: dict[str, str]
    text: str


class _InteractiveHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.elements: list[RawElement] = []
        self.label_for: dict[str, str] = {}
        self.title_text = ""
        self.heading_text = ""
        self._capture_stack: list[dict[str, object]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key: (value or "") for key, value in attrs}

        if tag in INTERACTIVE_TAGS:
            raw_element: RawElement = {
                "tag": tag,
                "attrs": attr_map,
                "text": "",
            }
            self.elements.append(raw_element)
            if tag in {"button", "textarea"}:
                self._capture_stack.append(
                    {
                        "kind": tag,
                        "element_index": len(self.elements) - 1,
                        "attrs": attr_map,
                        "text_parts": [],
                    }
                )
            return

        if tag in {"label", "title", "h1"}:
            self._capture_stack.append(
                {
                    "kind": tag,
                    "attrs": attr_map,
                    "text_parts": [],
                }
            )

    def handle_data(self, data: str) -> None:
        if not data.strip():
            return

        for capture in self._capture_stack:
            text_parts = capture.setdefault("text_parts", [])
            assert isinstance(text_parts, list)
            text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._capture_stack) - 1, -1, -1):
            capture = self._capture_stack[index]
            if capture.get("kind") != tag:
                continue

            self._capture_stack.pop(index)
            text = _normalize_text(" ".join(capture.get("text_parts", [])))
            attrs = capture.get("attrs", {})
            if not isinstance(attrs, dict):
                attrs = {}

            if tag == "label":
                target_id = attrs.get("for", "").strip()
                if target_id and text:
                    self.label_for[target_id] = text
            elif tag == "title" and text:
                self.title_text = text
            elif tag == "h1" and text and not self.heading_text:
                self.heading_text = text
            elif tag in {"button", "textarea"}:
                element_index = capture.get("element_index")
                if isinstance(element_index, int):
                    self.elements[element_index]["text"] = text
            break


def build_page_spec(
    html_source: str,
    source_path: Path,
    policy: PageObjectGenerationPolicy = DEFAULT_PAGE_OBJECT_POLICY,
    *,
    class_name_source: str | None = None,
) -> PageSpec:
    parser = _InteractiveHtmlParser()
    parser.feed(html_source)

    class_name = _build_class_name(
        class_name_source or source_path.stem,
        policy.class_suffix,
    )
    page_title = parser.title_text or parser.heading_text or class_name.removesuffix(policy.class_suffix)

    elements: list[ElementSpec] = []
    for raw_element in parser.elements:
        tag = raw_element["tag"]
        attrs = raw_element["attrs"]
        input_type = attrs.get("type", "").strip().lower()

        if tag == "input" and input_type == "hidden":
            continue

        label = _determine_label(tag, attrs, raw_element["text"], parser.label_for)
        if not label:
            raise ValueError(f"Unable to determine a stable label for element with attributes {attrs}")

        method_base = _slugify(label)
        if not method_base:
            raise ValueError(f"Unable to derive a method name from label {label!r}")

        action = _determine_action(tag, input_type)
        method_name, method_signature = _build_method_contract(action, method_base)
        by_member, selector_value, selector_source = _choose_selector(
            tag=tag,
            attrs=attrs,
            text=raw_element["text"],
            selector_priority=policy.selector_priority,
        )
        locator_name = _build_locator_name(method_base, tag, input_type)

        elements.append(
            ElementSpec(
                label=label,
                tag=tag,
                input_type=input_type,
                locator_name=locator_name,
                by_member=by_member,
                selector_value=selector_value,
                selector_source=selector_source,
                method_name=method_name,
                action=action,
                method_signature=method_signature,
            )
        )

    if not elements:
        raise ValueError(f"No interactive elements were found in HTML file {source_path}")

    return PageSpec(
        source_path=source_path,
        class_name=class_name,
        page_title=page_title,
        elements=elements,
    )


def render_policy_summary(
    policy: PageObjectGenerationPolicy = DEFAULT_PAGE_OBJECT_POLICY,
) -> str:
    lines = ["Deterministic planning policy:"]
    for index, step in enumerate(policy.planning_steps, start=1):
        lines.append(f"{index}. {step}")
    return "\n".join(lines)


def render_page_spec(page_spec: PageSpec) -> str:
    lines = [
        f"Source HTML: {page_spec.source_path}",
        f"Page title: {page_spec.page_title}",
        f"Required class name: {page_spec.class_name}",
        "Required elements and methods:",
    ]
    for element in page_spec.elements:
        lines.append(
            (
                f"- {element.locator_name} = (By.{element.by_member}, {element.selector_value!r}) "
                f"[from {element.selector_source}] -> {element.method_signature} ({element.action})"
            )
        )
    return "\n".join(lines)


def _determine_label(
    tag: str,
    attrs: dict[str, str],
    text: str,
    label_for_map: dict[str, str],
) -> str:
    element_id = attrs.get("id", "").strip()
    candidates = [
        label_for_map.get(element_id, ""),
        attrs.get("aria-label", ""),
        attrs.get("placeholder", ""),
        text,
        attrs.get("name", ""),
        attrs.get("id", ""),
        attrs.get("data-testid", ""),
    ]
    if tag == "button" and text:
        candidates.insert(0, text)

    for candidate in candidates:
        normalized = _normalize_text(candidate)
        if normalized:
            return normalized
    return ""


def _determine_action(tag: str, input_type: str) -> str:
    if tag == "select":
        return "choose"
    if tag == "button":
        return "click"
    if tag == "textarea":
        return "fill"
    if tag == "input" and input_type == "checkbox":
        return "set"
    if tag == "input" and input_type in {"submit", "button"}:
        return "click"
    if tag == "input" and input_type in TEXT_INPUT_TYPES:
        return "fill"
    raise ValueError(f"Unsupported interactive element: tag={tag!r}, input_type={input_type!r}")


def _choose_selector(
    *,
    tag: str,
    attrs: dict[str, str],
    text: str,
    selector_priority: list[str],
) -> tuple[str, str, str]:
    for selector_type in selector_priority:
        if selector_type == "data-testid" and attrs.get("data-testid", "").strip():
            return "CSS_SELECTOR", f'[data-testid="{attrs["data-testid"].strip()}"]', "data-testid"
        if selector_type == "id" and attrs.get("id", "").strip():
            return "ID", attrs["id"].strip(), "id"
        if selector_type == "name" and attrs.get("name", "").strip():
            return "NAME", attrs["name"].strip(), "name"
        if selector_type == "aria-label" and attrs.get("aria-label", "").strip():
            return "CSS_SELECTOR", f'[aria-label="{attrs["aria-label"].strip()}"]', "aria-label"
        if selector_type == "button-text" and tag == "button" and _normalize_text(text):
            button_text = _normalize_text(text)
            return "XPATH", f"//button[normalize-space()={button_text!r}]", "button-text"

    raise ValueError(f"Unable to choose a stable selector for element with attributes {attrs}")


def _build_class_name(stem: str, class_suffix: str) -> str:
    parts = [part for part in re.split(r"[^a-zA-Z0-9]+", stem) if part]
    base_name = "".join(part.capitalize() for part in parts) or "Generated"
    return f"{base_name}{class_suffix}"


def _build_locator_name(method_base: str, tag: str, input_type: str) -> str:
    suffix = {
        "button": "BUTTON",
        "select": "SELECT",
        "textarea": "TEXTAREA",
    }.get(tag, "INPUT")
    if tag == "input" and input_type == "checkbox":
        suffix = "CHECKBOX"
    return f"{method_base.upper()}_{suffix}"


def _build_method_contract(action: str, method_base: str) -> tuple[str, str]:
    if action == "fill":
        return f"fill_{method_base}", f"fill_{method_base}(self, value: str) -> None"
    if action == "choose":
        return f"choose_{method_base}", f"choose_{method_base}(self, value: str) -> None"
    if action == "set":
        return f"set_{method_base}", f"set_{method_base}(self, checked: bool) -> None"
    if action == "click":
        return f"click_{method_base}", f"click_{method_base}(self) -> None"
    raise ValueError(f"Unsupported action {action!r}")


def _normalize_text(value: str) -> str:
    return " ".join(value.split())


def _slugify(value: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower())
    return sanitized.strip("_")
