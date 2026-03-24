from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, TypedDict


TRACE_STATE_KEY = "trace_events"
TRACE_EXCLUDED_STATE_KEYS = {TRACE_STATE_KEY}


class TraceEvent(TypedDict, total=False):
    sequence: int
    timestamp: str
    event_type: str
    node: str
    input_state: dict[str, Any]
    output_update: dict[str, Any]
    details: dict[str, Any]


def append_trace_event(
    state: Mapping[str, Any],
    *,
    event_type: str,
    node: str,
    input_state: Mapping[str, Any] | None = None,
    output_update: Mapping[str, Any] | None = None,
    details: Mapping[str, Any] | None = None,
) -> list[TraceEvent]:
    trace_events = list(state.get(TRACE_STATE_KEY, []))
    trace_events.append(
        TraceEvent(
            sequence=len(trace_events) + 1,
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type=event_type,
            node=node,
            input_state=serialize_trace_value(input_state or {}),
            output_update=serialize_trace_value(output_update or {}),
            details=serialize_trace_value(details or {}),
        )
    )
    return trace_events


def snapshot_state(state: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: serialize_trace_value(value)
        for key, value in state.items()
        if key not in TRACE_EXCLUDED_STATE_KEYS
    }


def serialize_trace_value(value: Any) -> Any:
    if is_dataclass(value):
        return serialize_trace_value(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {
            str(key): serialize_trace_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [serialize_trace_value(item) for item in value]
    if isinstance(value, tuple):
        return [serialize_trace_value(item) for item in value]
    if isinstance(value, set):
        return [serialize_trace_value(item) for item in sorted(value)]
    return value
