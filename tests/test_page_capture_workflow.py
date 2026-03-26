from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import tempfile
import unittest

from bedrock_langgraph_agent.journey_workflow import build_journey_planning_graph
from bedrock_langgraph_agent.page_capture_models import ActionableElement
from bedrock_langgraph_agent.page_capture_workflow import build_page_capture_graph


class StubBrowserSession:
    def __init__(self, pages: dict[str, dict[str, object]]) -> None:
        self._pages = pages
        self._current_page: dict[str, object] | None = None
        self.opened_urls: list[str] = []

    def open(self, url: str) -> None:
        self.opened_urls.append(url)
        self._current_page = self._pages[url]

    def current_url(self) -> str:
        return str(self._current_page["final_url"])

    def title(self) -> str:
        return str(self._current_page["title"])

    def page_source(self) -> str:
        return str(self._current_page["html"])

    def save_screenshot(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"stub-screenshot")

    def list_actionable_elements(self) -> list[ActionableElement]:
        return list(self._current_page["elements"])

    def close(self) -> None:
        return None


def _create_phase1_run(
    *,
    tmp_path: Path,
    events: list[dict[str, object]],
    timestamp: datetime,
) -> Path:
    journey_path = tmp_path / "journey.ndjson"
    journey_path.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )
    graph = build_journey_planning_graph(
        output_root=tmp_path / "output",
        now_provider=lambda: timestamp,
    )
    result = graph.invoke({"journey_events_path": str(journey_path)})
    return result["run_directories"].run_root


class PageCaptureWorkflowTests(unittest.TestCase):
    def test_page_capture_workflow_captures_unique_pages_and_updates_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            run_root = _create_phase1_run(
                tmp_path=tmp_path,
                events=[
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
                    },
                ],
                timestamp=datetime(2026, 3, 25, 16, 0, 0, tzinfo=timezone.utc),
            )

            browser = StubBrowserSession(
                {
                    "https://shop.example.test/": {
                        "final_url": "https://shop.example.test/",
                        "title": "Home",
                        "html": "<html><body><button>Start checkout</button></body></html>",
                        "elements": [
                            ActionableElement(
                                sequence=1,
                                tag_name="button",
                                text="Start checkout",
                                attributes={"data-testid": "start-checkout"},
                            )
                        ],
                    },
                    "https://shop.example.test/checkout": {
                        "final_url": "https://shop.example.test/checkout",
                        "title": "Checkout",
                        "html": "<html><body><input id='email'/></body></html>",
                        "elements": [
                            ActionableElement(
                                sequence=1,
                                tag_name="input",
                                text="",
                                attributes={"id": "email", "type": "email"},
                            )
                        ],
                    },
                }
            )

            graph = build_page_capture_graph(browser)
            result = graph.invoke({"run_root": str(run_root)})

            self.assertEqual(result["auth_session_status"], "skipped")
            self.assertEqual(result["run_status"], "succeeded")
            self.assertEqual(
                browser.opened_urls,
                [
                    "https://shop.example.test/",
                    "https://shop.example.test/checkout",
                ],
            )

            manifest = json.loads(
                Path(result["page_capture_manifest_path"]).read_text(encoding="utf-8")
            )
            self.assertEqual(len(manifest["snapshots"]), 2)
            self.assertTrue(
                Path(manifest["snapshots"][0]["screenshot_path"]).exists()
            )

            run_manifest = json.loads(
                (run_root / "run_manifest.json").read_text(encoding="utf-8")
            )
            self.assertIn("page_capture_manifest_path", run_manifest)
            self.assertIn("page_capture_trace_path", run_manifest)

    def test_page_capture_workflow_requests_manual_login_when_auth_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            run_root = _create_phase1_run(
                tmp_path=tmp_path,
                events=[
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
                ],
                timestamp=datetime(2026, 3, 25, 17, 0, 0, tzinfo=timezone.utc),
            )

            browser = StubBrowserSession(
                {
                    "https://app.example.test/login": {
                        "final_url": "https://app.example.test/login",
                        "title": "Login",
                        "html": "<html><body><input id='username'/></body></html>",
                        "elements": [],
                    },
                    "https://app.example.test/dashboard": {
                        "final_url": "https://app.example.test/dashboard",
                        "title": "Dashboard",
                        "html": "<html><body><a href='/logout'>Logout</a></body></html>",
                        "elements": [],
                    },
                }
            )
            login_calls: list[str] = []

            def fake_login_handler(browser_session, journey_spec, auth_checkpoint) -> None:
                login_calls.append(str(auth_checkpoint["auth_checkpoint_status"]))

            graph = build_page_capture_graph(browser, login_handler=fake_login_handler)
            result = graph.invoke({"run_root": str(run_root)})

            self.assertEqual(result["auth_session_status"], "manual_login_confirmed")
            self.assertEqual(login_calls, ["pending_manual_login"])
            self.assertEqual(
                browser.opened_urls,
                [
                    "https://app.example.test/login",
                    "https://app.example.test/login",
                    "https://app.example.test/dashboard",
                ],
            )


if __name__ == "__main__":
    unittest.main()
