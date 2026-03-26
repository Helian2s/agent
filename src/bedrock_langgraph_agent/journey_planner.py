from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from .journey_models import (
    AuthRequirement,
    JourneyAction,
    JourneyPage,
    JourneySpec,
    NormalizedJourneyEvent,
)


URL_KEYS = ("url", "page_url", "page_location", "location", "href")
TIMESTAMP_KEYS = ("timestamp", "event_timestamp", "time", "ts", "occurred_at")
EVENT_NAME_KEYS = ("event_name", "event", "type", "name", "action")
CLICK_TARGET_KEYS = (
    "click_target",
    "target",
    "element",
    "selector",
    "element_text",
    "button_text",
    "link_text",
)
TEXT_INPUT_KEYS = ("text_input", "input_value", "entered_text")
SCROLL_DEPTH_KEYS = ("scroll_depth", "scroll_percent", "percent_scrolled")
NAVIGATION_SOURCE_KEYS = ("navigation_source", "referrer", "source", "from_url")
AUTH_HINT_KEYS = (
    "auth_required",
    "requires_auth",
    "login_required",
    "authentication_required",
    "needs_authentication",
)

PAGE_VIEW_EVENT_NAMES = {"page_view", "page_open", "screen_view", "view_page"}
CLICK_EVENT_KEYWORDS = ("click", "tap", "press", "submit")
LOGIN_KEYWORDS = ("login", "log_in", "signin", "sign_in", "authenticate", "auth")
TRUE_VALUES = {"1", "true", "required", "yes", "y"}
FALSE_VALUES = {"0", "false", "not_required", "optional", "no", "n", "skip"}


def build_journey_spec(
    raw_events: list[dict[str, Any]],
    source_path: str | Path,
) -> tuple[list[NormalizedJourneyEvent], JourneySpec]:
    normalized_events = [
        normalize_journey_event(raw_event, sequence=index)
        for index, raw_event in enumerate(raw_events, start=1)
    ]

    auth_requirement, auth_reason = detect_auth_requirement(raw_events, normalized_events)
    pages = build_page_sequence(normalized_events)
    unique_page_urls = _ordered_unique(event.url for event in normalized_events)
    first_url = normalized_events[0].url
    site_host = urlparse(first_url).netloc or "unknown-host"

    journey_spec = JourneySpec(
        source_path=str(Path(source_path).expanduser().resolve()),
        site_host=site_host,
        total_events=len(normalized_events),
        started_at=normalized_events[0].timestamp,
        ended_at=normalized_events[-1].timestamp,
        auth_requirement=auth_requirement,
        auth_reason=auth_reason,
        page_sequence=pages,
        unique_page_urls=unique_page_urls,
    )
    return normalized_events, journey_spec


def normalize_journey_event(
    raw_event: dict[str, Any],
    *,
    sequence: int,
) -> NormalizedJourneyEvent:
    url = _first_string(raw_event, URL_KEYS)
    if not url:
        raise ValueError(f"Journey event {sequence} is missing a URL field.")

    timestamp = _first_string(raw_event, TIMESTAMP_KEYS) or f"event-{sequence}"
    event_name = _normalize_token(_first_string(raw_event, EVENT_NAME_KEYS) or "interaction")
    click_target = _first_string(raw_event, CLICK_TARGET_KEYS)
    text_input = _first_string(raw_event, TEXT_INPUT_KEYS)
    scroll_depth = _first_number(raw_event, SCROLL_DEPTH_KEYS)
    navigation_source = _first_string(raw_event, NAVIGATION_SOURCE_KEYS)
    action_type = _determine_action_type(
        event_name=event_name,
        click_target=click_target,
        text_input=text_input,
        scroll_depth=scroll_depth,
    )

    consumed_keys = set(URL_KEYS)
    consumed_keys.update(TIMESTAMP_KEYS)
    consumed_keys.update(EVENT_NAME_KEYS)
    consumed_keys.update(CLICK_TARGET_KEYS)
    consumed_keys.update(TEXT_INPUT_KEYS)
    consumed_keys.update(SCROLL_DEPTH_KEYS)
    consumed_keys.update(NAVIGATION_SOURCE_KEYS)
    metadata = {
        key: value
        for key, value in raw_event.items()
        if key not in consumed_keys
    }

    return NormalizedJourneyEvent(
        sequence=sequence,
        timestamp=timestamp,
        url=url,
        event_name=event_name,
        action_type=action_type,
        click_target=click_target,
        text_input=text_input,
        scroll_depth=scroll_depth,
        navigation_source=navigation_source,
        metadata=metadata,
    )


def detect_auth_requirement(
    raw_events: list[dict[str, Any]],
    normalized_events: list[NormalizedJourneyEvent],
) -> tuple[AuthRequirement, str]:
    explicit_false_event: int | None = None

    for index, raw_event in enumerate(raw_events, start=1):
        for key in AUTH_HINT_KEYS:
            if key not in raw_event or raw_event[key] is None:
                continue
            parsed_value = _parse_boolish(raw_event[key])
            if parsed_value is True:
                return "required", f"Explicit `{key}` flag was true on event {index}."
            if parsed_value is False and explicit_false_event is None:
                explicit_false_event = index

        event = normalized_events[index - 1]
        combined_text = " ".join(
            filter(
                None,
                [
                    event.event_name,
                    event.url,
                    event.click_target,
                    event.navigation_source,
                ],
            )
        ).lower()
        if any(keyword in combined_text for keyword in LOGIN_KEYWORDS):
            return "required", f"Login/authentication keyword detected on event {index}."

    if explicit_false_event is not None:
        return "not_required", (
            "Explicit authentication flag indicated the journey does not require login "
            f"on event {explicit_false_event}."
        )

    return (
        "unknown",
        "No explicit authentication signal was found in the journey events.",
    )


def build_page_sequence(normalized_events: list[NormalizedJourneyEvent]) -> list[JourneyPage]:
    pages: list[JourneyPage] = []
    current_events: list[NormalizedJourneyEvent] = []
    current_url: str | None = None

    for event in normalized_events:
        if current_url is None or event.url == current_url:
            current_events.append(event)
            current_url = event.url
            continue

        pages.append(_build_page(sequence=len(pages) + 1, events=current_events))
        current_events = [event]
        current_url = event.url

    if current_events:
        pages.append(_build_page(sequence=len(pages) + 1, events=current_events))

    return pages


def _build_page(*, sequence: int, events: list[NormalizedJourneyEvent]) -> JourneyPage:
    first_event = events[0]
    last_event = events[-1]

    actions = [
        _build_action(event)
        for event in events
        if not (
            event.action_type == "navigation"
            and event.event_name in PAGE_VIEW_EVENT_NAMES
            and not event.click_target
            and not event.text_input
            and event.scroll_depth is None
        )
    ]

    return JourneyPage(
        sequence=sequence,
        url=first_event.url,
        page_name=derive_page_name(first_event.url),
        entry_timestamp=first_event.timestamp,
        exit_timestamp=last_event.timestamp,
        event_count=len(events),
        actions=actions,
    )


def _build_action(event: NormalizedJourneyEvent) -> JourneyAction:
    if event.action_type == "click":
        description = f"Click `{event.click_target or 'unknown target'}`."
    elif event.action_type == "text_input":
        description = f"Enter text into `{event.click_target or 'unknown field'}`."
    elif event.action_type == "scroll":
        description = f"Scroll to {event.scroll_depth}%."
    elif event.action_type == "navigation":
        description = f"Navigate to `{event.url}`."
    else:
        description = f"Recorded `{event.event_name}` interaction."

    return JourneyAction(
        source_event_sequence=event.sequence,
        timestamp=event.timestamp,
        action_type=event.action_type,
        description=description,
        target=event.click_target,
        value=event.text_input,
        navigation_source=event.navigation_source,
        scroll_depth=event.scroll_depth,
    )


def derive_page_name(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        return "home"
    return _normalize_token(path.replace("/", "_"))


def _determine_action_type(
    *,
    event_name: str,
    click_target: str | None,
    text_input: str | None,
    scroll_depth: float | None,
) -> str:
    if scroll_depth is not None:
        return "scroll"
    if text_input:
        return "text_input"
    if click_target or any(keyword in event_name for keyword in CLICK_EVENT_KEYWORDS):
        return "click"
    if event_name in PAGE_VIEW_EVENT_NAMES or "navigation" in event_name:
        return "navigation"
    return event_name or "interaction"


def _first_string(raw_event: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = raw_event.get(key)
        if value is None:
            continue
        if isinstance(value, str) and value.strip():
            return value.strip()
        if not isinstance(value, (dict, list)):
            string_value = str(value).strip()
            if string_value:
                return string_value
    return None


def _first_number(raw_event: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = raw_event.get(key)
        if value is None:
            continue
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            stripped = value.strip().rstrip("%")
            if not stripped:
                continue
            try:
                return float(stripped)
            except ValueError:
                continue
    return None


def _parse_boolish(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = _normalize_token(str(value))
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    return None


def _normalize_token(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower())
    normalized = re.sub(r"_+", "_", normalized)
    return normalized.strip("_")


def _ordered_unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered
