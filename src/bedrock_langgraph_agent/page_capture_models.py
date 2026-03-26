from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ActionableElement:
    sequence: int
    tag_name: str
    text: str
    attributes: dict[str, str] = field(default_factory=dict)
    is_visible: bool = True
    is_enabled: bool = True


@dataclass(frozen=True)
class PageSnapshot:
    sequence: int
    journey_page_sequence: int
    page_name: str
    requested_url: str
    final_url: str
    title: str
    html_path: str
    screenshot_path: str
    elements_path: str
    actionable_elements: list[ActionableElement] = field(default_factory=list)
