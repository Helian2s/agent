from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import tempfile
import unittest

from bedrock_langgraph_agent.page_object_generation.tracing import (
    DEFAULT_TRACE_DIR,
    resolve_trace_log_path,
    write_trace_log,
)


class PageObjectTracingTests(unittest.TestCase):
    def test_resolve_trace_log_path_uses_default_logs_directory(self) -> None:
        trace_path = resolve_trace_log_path(
            html_path="examples/checkout_form.html",
            run_status="failed",
            now=datetime(2026, 3, 24, 18, 30, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(
            trace_path,
            DEFAULT_TRACE_DIR / "checkout_form_20260324T183000Z_failed.json",
        )

    def test_write_trace_log_persists_json_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            trace_path = Path(tmp_dir) / "trace.json"

            write_trace_log(
                [
                    {
                        "sequence": 1,
                        "event_type": "node_enter",
                        "node": "plan_page_object",
                    }
                ],
                trace_path,
            )

            saved = json.loads(trace_path.read_text(encoding="utf-8"))
            self.assertEqual(saved[0]["node"], "plan_page_object")


if __name__ == "__main__":
    unittest.main()
