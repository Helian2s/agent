from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


AuthRequirement = Literal["required", "not_required", "unknown"]
AuthCheckpointStatus = Literal[
    "pending_manual_login",
    "needs_manual_decision",
    "skipped",
]


@dataclass(frozen=True)
class NormalizedJourneyEvent:
    sequence: int
    timestamp: str
    url: str
    event_name: str
    action_type: str
    click_target: str | None = None
    text_input: str | None = None
    scroll_depth: float | None = None
    navigation_source: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class JourneyAction:
    source_event_sequence: int
    timestamp: str
    action_type: str
    description: str
    target: str | None = None
    value: str | None = None
    navigation_source: str | None = None
    scroll_depth: float | None = None


@dataclass(frozen=True)
class JourneyPage:
    sequence: int
    url: str
    page_name: str
    entry_timestamp: str
    exit_timestamp: str
    event_count: int
    actions: list[JourneyAction] = field(default_factory=list)


@dataclass(frozen=True)
class JourneySpec:
    source_path: str
    site_host: str
    total_events: int
    started_at: str
    ended_at: str
    auth_requirement: AuthRequirement
    auth_reason: str
    page_sequence: list[JourneyPage]
    unique_page_urls: list[str]
