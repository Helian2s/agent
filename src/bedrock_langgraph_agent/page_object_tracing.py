from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping, TypedDict

from .config import PROJECT_ROOT


TRACE_STATE_KEY = "trace_events"
TRACE_EXCLUDED_STATE_KEYS = {TRACE_STATE_KEY}
DEFAULT_TRACE_DIR = PROJECT_ROOT / "logs" / "page_object_traces"


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


def resolve_trace_log_path(
    *,
    html_path: str | Path,
    trace_output: str | Path | None = None,
    run_status: str = "unknown",
    now: datetime | None = None,
) -> Path:
    if trace_output:
        return Path(trace_output)

    source_path = Path(html_path)
    timestamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    status_suffix = run_status or "unknown"
    filename = f"{source_path.stem}_{timestamp}_{status_suffix}.json"
    return DEFAULT_TRACE_DIR / filename


def write_trace_log(trace_events: list[TraceEvent] | list[dict[str, Any]], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(serialize_trace_value(trace_events), indent=2), encoding="utf-8")
    return path


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def monotonic_seconds() -> float:
    return perf_counter()


def duration_ms(start_seconds: float, end_seconds: float) -> float:
    return round((end_seconds - start_seconds) * 1000, 3)
