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
from bedrock_langgraph_agent.page_object_runtime_workflow import build_page_object_runtime_graph
from bedrock_langgraph_agent.test_authoring_workflow import build_test_authoring_graph


VALID_CHECKOUT_EXAMPLE_PAGE_OBJECT = """from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select


class CheckoutExamplePage:
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


class StubTextGenerator:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        if not self._responses:
            raise AssertionError("No stub responses left.")
        return self._responses.pop(0)

    def get_trace_metadata(self) -> dict[str, str]:
        return {"provider": "bedrock", "modelId": "stub.model"}


class FakeElement:
    def __init__(
        self,
        *,
        tag_name: str,
        attributes: dict[str, str] | None = None,
        text: str = "",
        displayed: bool = True,
        enabled: bool = True,
        selected: bool = False,
        options: list[str] | None = None,
    ) -> None:
        self.tag_name = tag_name
        self._attributes = dict(attributes or {})
        self._text = text
        self._displayed = displayed
        self._enabled = enabled
        self._selected = selected
        self._options = list(options or [])
        self._selected_text = self._options[0] if self._options else ""

    def clear(self) -> None:
        self._attributes["value"] = ""

    def send_keys(self, value: str) -> None:
        self._attributes["value"] = value

    def get_attribute(self, name: str) -> str | None:
        return self._attributes.get(name)

    def is_selected(self) -> bool:
        return self._selected

    def click(self) -> None:
        if self._attributes.get("type") == "checkbox":
            self._selected = not self._selected

    def is_displayed(self) -> bool:
        return self._displayed

    def is_enabled(self) -> bool:
        return self._enabled

    def select_by_visible_text(self, value: str) -> None:
        if value not in self._options:
            raise ValueError(f"Unknown option {value}")
        self._selected_text = value
        self._attributes["value"] = value

    @property
    def selected_text(self) -> str:
        return self._selected_text

    @property
    def option_texts(self) -> list[str]:
        return list(self._options)


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

    def find_element(self, by_member: str, selector_value: str):
        return self._current_page["locators"][(by_member, selector_value)]

    def select_by_visible_text(self, element: FakeElement, value: str) -> None:
        element.select_by_visible_text(value)

    def selected_text(self, element: FakeElement) -> str:
        return element.selected_text

    def option_texts(self, element: FakeElement) -> list[str]:
        return element.option_texts

    def close(self) -> None:
        return None


class TestAuthoringWorkflowTests(unittest.TestCase):
    def test_test_authoring_generates_pytest_file_from_journey_actions(self) -> None:
        events = [
            {
                "timestamp": "2026-03-25T15:00:00Z",
                "url": "https://shop.example.test/checkout",
                "event_name": "page_view",
                "auth_required": False,
            },
            {
                "timestamp": "2026-03-25T15:00:01Z",
                "url": "https://shop.example.test/checkout",
                "event_name": "text_input",
                "click_target": "First Name",
                "text_input": "Val",
            },
            {
                "timestamp": "2026-03-25T15:00:02Z",
                "url": "https://shop.example.test/checkout",
                "event_name": "text_input",
                "click_target": "Email",
                "text_input": "val@example.test",
            },
            {
                "timestamp": "2026-03-25T15:00:03Z",
                "url": "https://shop.example.test/checkout",
                "event_name": "click",
                "click_target": "I accept the terms",
            },
            {
                "timestamp": "2026-03-25T15:00:04Z",
                "url": "https://shop.example.test/checkout",
                "event_name": "click",
                "click_target": "Place order",
            },
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            run_root = _create_verified_run(tmp_path, events)

            graph = build_test_authoring_graph()
            result = graph.invoke({"run_root": str(run_root)})

            self.assertEqual(result["run_status"], "succeeded")
            generated_test_path = Path(result["generated_test_path"])
            self.assertTrue(generated_test_path.exists())

            generated_test_code = generated_test_path.read_text(encoding="utf-8")
            self.assertIn("def test_generated_journey(driver):", generated_test_code)
            self.assertIn("page_1.fill_first_name('Val')", generated_test_code)
            self.assertIn(
                "page_1.fill_email('val@example.test')",
                generated_test_code,
            )
            self.assertIn("page_1.set_i_accept_the_terms(True)", generated_test_code)
            self.assertIn("page_1.click_place_order()", generated_test_code)

            manifest = json.loads(
                Path(result["test_authoring_manifest_path"]).read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["artifacts"][0]["test_name"], "test_generated_journey")

            run_manifest = json.loads((run_root / "run_manifest.json").read_text(encoding="utf-8"))
            self.assertIn("generated_test_path", run_manifest)
            self.assertIn("test_authoring_trace_path", run_manifest)

    def test_test_authoring_falls_back_to_runtime_smoke_actions_when_journey_has_none(self) -> None:
        events = [
            {
                "timestamp": "2026-03-25T15:00:00Z",
                "url": "https://shop.example.test/checkout",
                "event_name": "page_view",
                "auth_required": False,
            }
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            run_root = _create_verified_run(tmp_path, events)

            graph = build_test_authoring_graph()
            result = graph.invoke({"run_root": str(run_root)})

            generated_test_code = Path(result["generated_test_path"]).read_text(
                encoding="utf-8"
            )
            self.assertIn("page_1.fill_first_name('Proofica')", generated_test_code)
            self.assertIn(
                "page_1.choose_country('United States')",
                generated_test_code,
            )
            self.assertIn("page_1.click_place_order()", generated_test_code)


def _create_verified_run(tmp_path: Path, events: list[dict[str, object]]) -> Path:
    journey_path = tmp_path / "journey.ndjson"
    journey_path.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )

    journey_graph = build_journey_planning_graph(
        output_root=tmp_path / "output",
        now_provider=lambda: datetime(2026, 3, 25, 21, 0, 0, tzinfo=timezone.utc),
    )
    journey_result = journey_graph.invoke({"journey_events_path": str(journey_path)})
    run_root = journey_result["run_directories"].run_root

    example_html = (
        Path(__file__).resolve().parents[1] / "examples" / "checkout_form.html"
    ).read_text(encoding="utf-8")

    capture_browser = StubBrowserSession(
        {
            "https://shop.example.test/checkout": {
                "final_url": "https://shop.example.test/checkout",
                "title": "Checkout Example",
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
                "locators": {},
            }
        }
    )
    capture_graph = build_page_capture_graph(capture_browser)
    capture_graph.invoke({"run_root": str(run_root)})

    page_capture_manifest = json.loads(
        (run_root / "pages" / "page_capture_manifest.json").read_text(encoding="utf-8")
    )
    snapshot_uri = Path(
        page_capture_manifest["snapshots"][0]["html_path"]
    ).resolve().as_uri()

    runtime_browser = StubBrowserSession(
        {
            snapshot_uri: {
                "final_url": snapshot_uri,
                "title": "Checkout Example",
                "html": example_html,
                "elements": [],
                "locators": {
                    ("CSS_SELECTOR", '[data-testid="first-name-input"]'): FakeElement(
                        tag_name="input",
                        attributes={"value": "", "type": "text"},
                    ),
                    ("ID", "email"): FakeElement(
                        tag_name="input",
                        attributes={"value": "", "type": "email"},
                    ),
                    ("CSS_SELECTOR", '[data-testid="country-select"]'): FakeElement(
                        tag_name="select",
                        attributes={"value": ""},
                        options=["Select a country", "United States", "Canada"],
                    ),
                    ("ID", "notes"): FakeElement(
                        tag_name="textarea",
                        attributes={"value": ""},
                    ),
                    ("ID", "terms"): FakeElement(
                        tag_name="input",
                        attributes={"type": "checkbox"},
                        selected=False,
                    ),
                    ("CSS_SELECTOR", '[data-testid="submit-order"]'): FakeElement(
                        tag_name="button",
                        text="Place Order",
                    ),
                },
            }
        }
    )

    factory_graph = build_page_object_factory_graph(
        StubTextGenerator([VALID_CHECKOUT_EXAMPLE_PAGE_OBJECT])
    )
    factory_graph.invoke({"run_root": str(run_root), "max_attempts": 2})

    runtime_graph = build_page_object_runtime_graph(
        StubTextGenerator([]),
        runtime_browser,
    )
    runtime_graph.invoke({"run_root": str(run_root), "max_attempts": 2})

    return run_root


if __name__ == "__main__":
    unittest.main()
