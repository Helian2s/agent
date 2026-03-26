from __future__ import annotations

from json import JSONDecodeError
import json
from pathlib import Path
from typing import Any


def load_ndjson_events(path: str | Path) -> list[dict[str, Any]]:
    source_path = Path(path).expanduser().resolve()
    events: list[dict[str, Any]] = []

    with source_path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid NDJSON in {source_path} at line {line_number}: {exc.msg}"
                ) from exc
            if not isinstance(parsed, dict):
                raise ValueError(
                    f"Expected a JSON object per NDJSON line in {source_path} at line {line_number}."
                )
            events.append(parsed)

    if not events:
        raise ValueError(f"No journey events found in {source_path}.")

    return events
