from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any, Protocol

from .page_capture_models import ActionableElement


class BrowserElement(Protocol):
    def clear(self) -> None:
        """Clear the element value."""

    def send_keys(self, value: str) -> None:
        """Send keys to the element."""

    def get_attribute(self, name: str) -> str | None:
        """Return a single attribute value."""

    def is_selected(self) -> bool:
        """Return whether the element is selected."""

    def click(self) -> None:
        """Click the element."""

    def is_displayed(self) -> bool:
        """Return whether the element is visible."""

    def is_enabled(self) -> bool:
        """Return whether the element is enabled."""


class BrowserSession(Protocol):
    def open(self, url: str) -> None:
        """Navigate the browser to the supplied URL."""

    def current_url(self) -> str:
        """Return the browser's current URL."""

    def title(self) -> str:
        """Return the current page title."""

    def page_source(self) -> str:
        """Return the rendered page source."""

    def save_screenshot(self, path: Path) -> None:
        """Save a screenshot to the supplied path."""

    def list_actionable_elements(self) -> list[ActionableElement]:
        """Return actionable elements discovered on the current page."""

    def find_element(self, by_member: str, selector_value: str) -> BrowserElement:
        """Return the first element that matches the supplied selector."""

    def select_by_visible_text(self, element: BrowserElement, value: str) -> None:
        """Select an option by visible text."""

    def selected_text(self, element: BrowserElement) -> str:
        """Return the selected option text for a `<select>` element."""

    def option_texts(self, element: BrowserElement) -> list[str]:
        """Return the visible texts of options for a `<select>` element."""

    def close(self) -> None:
        """Close the browser session."""


class SeleniumChromeBrowserSession:
    def __init__(
        self,
        *,
        headless: bool = False,
        page_load_timeout_seconds: int = 30,
    ) -> None:
        try:
            from selenium import webdriver
            from selenium.common.exceptions import SessionNotCreatedException
            from selenium.common.exceptions import StaleElementReferenceException
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
        except ImportError as exc:
            raise RuntimeError(
                "Selenium is required for page capture. Run `pip install -e .` again to install it."
            ) from exc

        options = Options()
        if headless:
            options.add_argument("--headless=new")
        self._profile_dir = Path(
            tempfile.mkdtemp(prefix="proofica-chrome-profile-")
        )
        options.add_argument("--window-size=1440,1400")
        options.add_argument(f"--user-data-dir={self._profile_dir}")
        options.add_argument("--remote-debugging-pipe")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-background-networking")
        options.add_argument("--no-sandbox")

        try:
            self._driver = webdriver.Chrome(options=options)
        except SessionNotCreatedException as exc:
            shutil.rmtree(self._profile_dir, ignore_errors=True)
            raise RuntimeError(
                "Chrome started but Selenium could not establish a DevTools session. "
                "This often means the local Chrome/ChromeDriver startup flags or desktop "
                "environment need adjustment."
            ) from exc
        self._driver.set_page_load_timeout(page_load_timeout_seconds)
        self._by = By
        self._wait_cls = WebDriverWait
        self._stale_element_error = StaleElementReferenceException

    def open(self, url: str) -> None:
        self._driver.get(url)
        self._wait_cls(self._driver, 30).until(
            lambda driver: driver.execute_script("return document.readyState") == "complete"
        )

    def current_url(self) -> str:
        return str(self._driver.current_url)

    def title(self) -> str:
        return str(self._driver.title)

    def page_source(self) -> str:
        return str(self._driver.page_source)

    def save_screenshot(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._driver.save_screenshot(str(path))

    def list_actionable_elements(self) -> list[ActionableElement]:
        selector = (
            "a[href], button, input:not([type='hidden']), select, textarea, "
            "[role='button'], [role='link'], [data-testid], [aria-label]"
        )
        elements = self._driver.find_elements(self._by.CSS_SELECTOR, selector)
        actionable_elements: list[ActionableElement] = []

        for sequence, element in enumerate(elements, start=1):
            try:
                actionable_elements.append(
                    ActionableElement(
                        sequence=sequence,
                        tag_name=(element.tag_name or "").lower(),
                        text=(element.text or "").strip(),
                        attributes=_extract_attributes(element),
                        is_visible=bool(element.is_displayed()),
                        is_enabled=bool(element.is_enabled()),
                    )
                )
            except self._stale_element_error:
                continue

        return actionable_elements

    def find_element(self, by_member: str, selector_value: str) -> BrowserElement:
        by_strategy = getattr(self._by, by_member)
        return self._driver.find_element(by_strategy, selector_value)

    def select_by_visible_text(self, element: BrowserElement, value: str) -> None:
        from selenium.webdriver.support.ui import Select

        Select(element).select_by_visible_text(value)

    def selected_text(self, element: BrowserElement) -> str:
        from selenium.webdriver.support.ui import Select

        return str(Select(element).first_selected_option.text).strip()

    def option_texts(self, element: BrowserElement) -> list[str]:
        from selenium.webdriver.support.ui import Select

        return [
            str(option.text).strip()
            for option in Select(element).options
            if str(option.text).strip()
        ]

    def close(self) -> None:
        self._driver.quit()
        shutil.rmtree(self._profile_dir, ignore_errors=True)


def _extract_attributes(element: Any) -> dict[str, str]:
    attributes: dict[str, str] = {}
    for key in (
        "id",
        "name",
        "type",
        "role",
        "data-testid",
        "aria-label",
        "placeholder",
        "href",
        "value",
    ):
        value = element.get_attribute(key)
        if value:
            attributes[key] = str(value)
    return attributes
