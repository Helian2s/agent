from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from bedrock_langgraph_agent.journey_workflow import build_journey_planning_graph
from bedrock_langgraph_agent.page_capture_models import ActionableElement
from bedrock_langgraph_agent.page_capture_workflow import build_page_capture_graph
from bedrock_langgraph_agent.page_object_factory_workflow import build_page_object_factory_graph


VALID_CHECKOUT_FORM_PAGE_OBJECT = """from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select


class CheckoutFormPage:
    FIRST_NAME_INPUT = (By.CSS_SELECTOR, '[data-testid="first-name-input"]')
    EMAIL_INPUT = (By.ID, 'email')
    COUNTRY_SELECT = (By.CSS_SELECTOR, '[data-testid="country-select"]')
    DELIVERY_NOTES_TEXTAREA = (By.ID, 'notes')
    I_ACCEPT_THE_TERMS_CHECKBOX = (By.ID, 'terms')
    PLACE_ORDER_BUTTON = (By.CSS_SELECTOR, '[data-testid="submit-order"]')

    def __init__(self, driver):
        self.driver = driver

    def fill_first_name(self, value: str) -> None:
        element = self.driver.find_element(*self.FIRST_NAME_INPUT)
        element.clear()
        element.send_keys(value)

    def fill_email(self, value: str) -> None:
        element = self.driver.find_element(*self.EMAIL_INPUT)
        element.clear()
        element.send_keys(value)

    def choose_country(self, value: str) -> None:
        element = self.driver.find_element(*self.COUNTRY_SELECT)
        Select(element).select_by_visible_text(value)

    def fill_delivery_notes(self, value: str) -> None:
        element = self.driver.find_element(*self.DELIVERY_NOTES_TEXTAREA)
        element.clear()
        element.send_keys(value)

    def set_i_accept_the_terms(self, checked: bool) -> None:
        element = self.driver.find_element(*self.I_ACCEPT_THE_TERMS_CHECKBOX)
        if element.is_selected() != checked:
            element.click()

    def click_place_order(self) -> None:
        self.driver.find_element(*self.PLACE_ORDER_BUTTON).click()
"""


class StubBrowserSession:
    def __init__(self, pages: dict[str, dict[str, object]]) -> None:
        self._pages = pages
        self._current_page: dict[str, object] | None = None

    def open(self, url: str) -> None:
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


class StubTextGenerator:
    def __init__(self, response: str) -> None:
        self._response = response

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        return self._response

    def get_trace_metadata(self) -> dict[str, str]:
        return {"provider": "bedrock", "modelId": "stub.model"}


def _create_phase1_run(tmp_path: Path) -> Path:
    journey_path = tmp_path / "journey.ndjson"
    journey_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-03-25T15:00:00Z",
                        "url": "https://shop.example.test/checkout",
                        "event_name": "page_view",
                        "auth_required": False,
                    }
                )
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    graph = build_journey_planning_graph(
        output_root=tmp_path / "output",
        now_provider=lambda: datetime(2026, 3, 25, 18, 0, 0, tzinfo=timezone.utc),
    )
    result = graph.invoke({"journey_events_path": str(journey_path)})
    return result["run_directories"].run_root


class PageObjectFactoryWorkflowTests(unittest.TestCase):
    def test_factory_generates_page_objects_from_captured_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            run_root = _create_phase1_run(tmp_path)
            example_html = (
                Path(__file__).resolve().parents[1]
                / "examples"
                / "checkout_form.html"
            ).read_text(encoding="utf-8")

            capture_graph = build_page_capture_graph(
                StubBrowserSession(
                    {
                        "https://shop.example.test/checkout": {
                            "final_url": "https://shop.example.test/checkout",
                            "title": "Checkout Form",
                            "html": example_html,
                            "elements": [
                                ActionableElement(
                                    sequence=1,
                                    tag_name="input",
                                    text="",
                                    attributes={
                                        "id": "first-name",
                                        "data-testid": "first-name-input",
                                    },
                                )
                            ],
                        }
                    }
                )
            )
            capture_graph.invoke({"run_root": str(run_root)})

            factory_graph = build_page_object_factory_graph(
                StubTextGenerator(VALID_CHECKOUT_FORM_PAGE_OBJECT)
            )
            result = factory_graph.invoke({"run_root": str(run_root), "max_attempts": 2})

            self.assertEqual(result["run_status"], "succeeded")
            self.assertEqual(len(result["page_object_artifacts"]), 1)
            artifact = result["page_object_artifacts"][0]
            self.assertEqual(artifact.class_name, "CheckoutFormPage")
            self.assertTrue(Path(artifact.output_path).exists())
            self.assertTrue(Path(artifact.trace_path).exists())

            manifest = json.loads(
                Path(result["page_object_manifest_path"]).read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["artifacts"][0]["class_name"], "CheckoutFormPage")

            run_manifest = json.loads((run_root / "run_manifest.json").read_text(encoding="utf-8"))
            self.assertIn("page_object_manifest_path", run_manifest)
            self.assertIn("page_object_factory_trace_path", run_manifest)


if __name__ == "__main__":
    unittest.main()
