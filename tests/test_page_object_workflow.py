from __future__ import annotations

import unittest

from bedrock_langgraph_agent.config import PROJECT_ROOT
from bedrock_langgraph_agent.page_object_policy import (
    DEFAULT_PAGE_OBJECT_POLICY,
    build_page_spec,
)
from bedrock_langgraph_agent.page_object_verifier import verify_page_object
from bedrock_langgraph_agent.page_object_workflow import build_page_object_graph


EXAMPLE_HTML_PATH = PROJECT_ROOT / "examples" / "checkout_form.html"


VALID_PAGE_OBJECT = """from selenium.webdriver.common.by import By
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


INVALID_PAGE_OBJECT = """from selenium.webdriver.common.by import By


class CheckoutFormPage:
    FIRST_NAME_INPUT = (By.CSS_SELECTOR, '[data-testid="first-name-input"]')

    def __init__(self, driver):
        self.driver = driver

    def fill_first_name(self, value: str) -> None:
        element = self.driver.find_element(*self.FIRST_NAME_INPUT)
        element.send_keys(value)
"""


class StubTextGenerator:
    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.prompts: list[str] = []

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        self.prompts.append(user_prompt)
        if not self._responses:
            raise AssertionError("No stubbed responses left for the text generator.")
        return self._responses.pop(0)

    def get_trace_metadata(self) -> dict[str, str]:
        return {
            "provider": "bedrock",
            "modelId": "stub.model",
        }


class PageObjectWorkflowTests(unittest.TestCase):
    def test_build_page_spec_from_example(self) -> None:
        html_source = EXAMPLE_HTML_PATH.read_text(encoding="utf-8")

        page_spec = build_page_spec(
            html_source,
            EXAMPLE_HTML_PATH,
            DEFAULT_PAGE_OBJECT_POLICY,
        )

        self.assertEqual(page_spec.class_name, "CheckoutFormPage")
        self.assertEqual(
            [element.method_name for element in page_spec.elements],
            [
                "fill_first_name",
                "fill_email",
                "choose_country",
                "fill_delivery_notes",
                "set_i_accept_the_terms",
                "click_place_order",
            ],
        )

    def test_verifier_accepts_valid_page_object(self) -> None:
        html_source = EXAMPLE_HTML_PATH.read_text(encoding="utf-8")
        page_spec = build_page_spec(
            html_source,
            EXAMPLE_HTML_PATH,
            DEFAULT_PAGE_OBJECT_POLICY,
        )

        result = verify_page_object(VALID_PAGE_OBJECT, page_spec)

        self.assertTrue(result.is_valid)
        self.assertEqual(result.errors, [])

    def test_workflow_retries_after_verifier_feedback(self) -> None:
        text_generator = StubTextGenerator(
            responses=[INVALID_PAGE_OBJECT, VALID_PAGE_OBJECT]
        )
        graph = build_page_object_graph(text_generator)

        result = graph.invoke({"html_path": str(EXAMPLE_HTML_PATH), "max_attempts": 2})

        self.assertEqual(result["final_page_object"].strip(), VALID_PAGE_OBJECT.strip())
        self.assertEqual(result["attempt_count"], 2)
        self.assertIn("Verifier rejected the page object", text_generator.prompts[1])
        trace_event_types = [event["event_type"] for event in result["trace_events"]]
        self.assertIn("llm_call", trace_event_types)
        self.assertIn("transition", trace_event_types)
        self.assertEqual(result["run_status"], "succeeded")
        llm_events = [
            event for event in result["trace_events"] if event["event_type"] == "llm_call"
        ]
        self.assertEqual(llm_events[0]["details"]["provider"], "bedrock")
        self.assertEqual(llm_events[0]["details"]["modelId"], "stub.model")
        self.assertIn("llm_wait_ms", llm_events[0]["details"])
        self.assertIn("llm_started_at", llm_events[0]["details"])
        self.assertIn("llm_finished_at", llm_events[0]["details"])
        node_exit_events = [
            event for event in result["trace_events"] if event["event_type"] == "node_exit"
        ]
        self.assertTrue(
            all("node_duration_ms" in event["details"] for event in node_exit_events)
        )

    def test_workflow_records_failure_trace_when_attempts_are_exhausted(self) -> None:
        text_generator = StubTextGenerator(responses=[INVALID_PAGE_OBJECT])
        graph = build_page_object_graph(text_generator)

        result = graph.invoke({"html_path": str(EXAMPLE_HTML_PATH), "max_attempts": 1})

        self.assertEqual(result["run_status"], "failed")
        self.assertIn("Page object verification failed after 1 attempts", result["failure_message"])
        transition_targets = [
            event["details"].get("to_node")
            for event in result["trace_events"]
            if event["event_type"] == "transition"
        ]
        self.assertIn("fail_generation", transition_targets)


if __name__ == "__main__":
    unittest.main()
