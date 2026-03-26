from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from bedrock_langgraph_agent.journey_planning.workflow import build_journey_planning_graph
from bedrock_langgraph_agent.shared.run_artifacts import RunDirectories


def _write_ndjson(path: Path, events: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )


class JourneyWorkflowTests(unittest.TestCase):
    def test_journey_workflow_creates_timestamped_run_outputs(self) -> None:
        events = [
            {
                "timestamp": "2026-03-25T15:00:00Z",
                "url": "https://shop.example.test/",
                "event_name": "page_view",
                "auth_required": False,
            },
            {
                "timestamp": "2026-03-25T15:00:05Z",
                "url": "https://shop.example.test/",
                "event_name": "click",
                "click_target": "Start checkout",
            },
            {
                "timestamp": "2026-03-25T15:00:10Z",
                "url": "https://shop.example.test/checkout",
                "event_name": "page_view",
                "navigation_source": "https://shop.example.test/",
            },
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            journey_path = tmp_path / "journey.ndjson"
            _write_ndjson(journey_path, events)

            graph = build_journey_planning_graph(
                output_root=tmp_path / "output",
                now_provider=lambda: datetime(2026, 3, 25, 16, 0, 0, tzinfo=timezone.utc),
            )

            result = graph.invoke({"journey_events_path": str(journey_path)})

            run_directories = result["run_directories"]
            self.assertIsInstance(run_directories, RunDirectories)
            self.assertEqual(run_directories.run_root.name, "20260325T160000Z")
            self.assertTrue((run_directories.input_dir / "journey.ndjson").exists())
            self.assertTrue(Path(result["normalized_events_path"]).exists())
            self.assertTrue(Path(result["journey_spec_path"]).exists())
            self.assertTrue(Path(result["manifest_path"]).exists())
            self.assertEqual(result["auth_checkpoint_status"], "skipped")
            self.assertEqual(result["run_status"], "succeeded")

            journey_spec = json.loads(
                Path(result["journey_spec_path"]).read_text(encoding="utf-8")
            )
            self.assertEqual(journey_spec["auth_requirement"], "not_required")
            self.assertEqual(
                journey_spec["unique_page_urls"],
                [
                    "https://shop.example.test/",
                    "https://shop.example.test/checkout",
                ],
            )

    def test_journey_workflow_records_auth_checkpoint_when_required(self) -> None:
        events = [
            {
                "timestamp": "2026-03-25T15:00:00Z",
                "url": "https://app.example.test/login",
                "event_name": "page_view",
                "auth_required": True,
            },
            {
                "timestamp": "2026-03-25T15:00:10Z",
                "url": "https://app.example.test/dashboard",
                "event_name": "page_view",
            },
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            journey_path = tmp_path / "journey.ndjson"
            _write_ndjson(journey_path, events)

            graph = build_journey_planning_graph(
                output_root=tmp_path / "output",
                now_provider=lambda: datetime(2026, 3, 25, 17, 30, 0, tzinfo=timezone.utc),
            )

            result = graph.invoke({"journey_events_path": str(journey_path)})

            self.assertEqual(result["auth_checkpoint_status"], "pending_manual_login")
            auth_checkpoint = json.loads(
                Path(result["auth_checkpoint_path"]).read_text(encoding="utf-8")
            )
            self.assertEqual(auth_checkpoint["auth_requirement"], "required")
            self.assertIn("Manual login", auth_checkpoint["auth_checkpoint_message"])
            transition_targets = [
                event["details"].get("to_node")
                for event in result["trace_events"]
                if event["event_type"] == "transition"
            ]
            self.assertIn("record_auth_checkpoint", transition_targets)


if __name__ == "__main__":
    unittest.main()
