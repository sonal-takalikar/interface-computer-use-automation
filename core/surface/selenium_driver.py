"""
Selenium Surface Driver Implementation.
Implements the SurfaceDriver abstraction using Selenium WebDriver (Chrome).
Operates in visible/headful mode for operator takeover and inspection,
and supports full DOM/accessibility extraction and same-session handoff.
"""

import datetime
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import WebDriverException

from core.surface.base import (
    BoundingBox,
    InteractiveControl,
    LiveSessionHandle,
    SurfaceDriver,
    SurfaceState,
)
from core.locators.multi_strategy import (
    MultiStrategyLocator,
    MultiStrategyResolver,
    ResolutionResult,
)


class SeleniumSurfaceDriver(SurfaceDriver):
    """Selenium WebDriver implementation of SurfaceDriver."""

    def __init__(self, headless: Optional[bool] = None, implicit_wait: float = 0.0):
        if headless is None:
            # Check env var, default to False for visible headful demo
            headless = os.environ.get("SELENIUM_HEADLESS", "false").lower() == "true"
        self.headless = headless

        chrome_options = Options()
        if self.headless:
            chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1280,850")

        self.driver = webdriver.Chrome(options=chrome_options)
        self.driver.implicitly_wait(implicit_wait)
        self.session_id = str(uuid.uuid4())[:8]

    def navigate(self, url: str) -> None:
        self.driver.get(url)
        time.sleep(0.3)  # Brief settle time for legacy page rendering

    def get_current_url(self) -> str:
        return self.driver.current_url

    def get_title(self) -> str:
        return self.driver.title

    def get_state(self) -> SurfaceState:
        """Inspect the current page and extract interactive controls and textual context."""
        js_extract_script = """
        return (function() {
            var controls = [];
            var elements = document.querySelectorAll('input, button, select, a, [role="button"], [role="alert"], [role="status"]');
            var idx = 0;

            elements.forEach(function(el) {
                var rect = el.getBoundingClientRect();
                // Filter out elements that are completely hidden
                var isVisible = (rect.width > 0 && rect.height > 0 && window.getComputedStyle(el).visibility !== 'hidden' && window.getComputedStyle(el).display !== 'none');
                if (!isVisible && el.type !== 'hidden') return;

                var role = el.getAttribute('role') || el.tagName.toLowerCase();
                if (el.tagName === 'INPUT') {
                    var t = (el.type || 'text').toLowerCase();
                    if (t === 'submit' || t === 'button') role = 'button';
                    else role = 'textbox';
                }

                // Accessible name resolution
                var accName = el.getAttribute('aria-label') || '';
                if (!accName && el.placeholder) accName = el.placeholder;
                if (!accName && (el.type === 'submit' || el.type === 'button')) accName = el.value || '';
                if (!accName && el.innerText) accName = el.innerText.trim();

                // Detect table label anchor in preceding TD
                var anchorText = '';
                var td = el.closest('td');
                if (td) {
                    var prevTd = td.previousElementSibling;
                    if (prevTd) {
                        anchorText = prevTd.innerText.trim();
                    }
                }
                if (!anchorText) {
                    var label = document.querySelector('label[for="' + el.id + '"]');
                    if (label) anchorText = label.innerText.trim();
                }

                var attrs = {};
                if (el.id) attrs['id'] = el.id;
                if (el.name) attrs['name'] = el.name;
                if (el.type) attrs['type'] = el.type;
                if (el.value && el.type !== 'password') attrs['value'] = el.value;

                controls.push({
                    control_id: 'ctrl_' + (++idx),
                    tag_name: el.tagName.toLowerCase(),
                    role: role,
                    accessible_name: accName,
                    text_content: (el.innerText || el.value || '').trim().substring(0, 100),
                    control_type: el.type || el.tagName.toLowerCase(),
                    rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
                    xpath: '',
                    css_selector: el.id ? '#' + el.id : (el.name ? el.tagName.toLowerCase() + '[name="' + el.name + '"]' : ''),
                    attributes: attrs,
                    anchor_text: anchorText
                });
            });

            return {
                title: document.title,
                url: window.location.href,
                page_text: document.body ? document.body.innerText.substring(0, 3000) : '',
                controls: controls
            };
        })();
        """
        raw_data = self.driver.execute_script(js_extract_script)
        
        controls = []
        for c in raw_data.get("controls", []):
            controls.append(
                InteractiveControl(
                    control_id=c["control_id"],
                    tag_name=c["tag_name"],
                    role=c["role"],
                    accessible_name=c["accessible_name"],
                    text_content=c["text_content"],
                    control_type=c["control_type"],
                    rect=BoundingBox(
                        x=c["rect"]["x"],
                        y=c["rect"]["y"],
                        width=c["rect"]["width"],
                        height=c["rect"]["height"],
                    ),
                    xpath=c["xpath"],
                    css_selector=c["css_selector"],
                    attributes=c["attributes"],
                    anchor_text=c["anchor_text"] or None,
                )
            )

        return SurfaceState(
            url=raw_data.get("url", self.driver.current_url),
            title=raw_data.get("title", self.driver.title),
            controls=controls,
            page_text=raw_data.get("page_text", ""),
            screenshot_bytes=None,
        )

    def click(self, locator: MultiStrategyLocator) -> bool:
        res: ResolutionResult = MultiStrategyResolver.resolve(self.driver, locator)
        elem = res.element
        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elem)
        time.sleep(0.1)
        try:
            elem.click()
        except Exception:
            self.driver.execute_script("arguments[0].click();", elem)
        time.sleep(0.3)  # Settle time
        return True

    def type_text(self, locator: MultiStrategyLocator, text: str, clear: bool = True) -> bool:
        res: ResolutionResult = MultiStrategyResolver.resolve(self.driver, locator)
        elem = res.element
        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elem)
        time.sleep(0.1)
        if clear:
            elem.clear()
        elem.send_keys(text)
        time.sleep(0.1)
        return True

    def select_option(self, locator: MultiStrategyLocator, value: str) -> bool:
        res: ResolutionResult = MultiStrategyResolver.resolve(self.driver, locator)
        elem = res.element
        select = Select(elem)
        try:
            select.select_by_value(value)
        except Exception:
            select.select_by_visible_text(value)
        time.sleep(0.2)
        return True

    def extract_text(self, locator: MultiStrategyLocator) -> str:
        res: ResolutionResult = MultiStrategyResolver.resolve(self.driver, locator)
        elem = res.element
        if elem.tag_name == "input" or elem.tag_name == "textarea":
            val = elem.get_attribute("value") or ""
            return val.strip()
        return (elem.text or "").strip()

    def capture_screenshot(self) -> bytes:
        return self.driver.get_screenshot_as_png()

    def pause_for_human(self, step_id: Optional[str] = None) -> LiveSessionHandle:
        """Pause automation and yield control of the live Selenium window to the human operator."""
        handle = LiveSessionHandle(
            session_id=self.session_id,
            window_handle=self.driver.current_window_handle,
            paused_url=self.driver.current_url,
            paused_step_id=step_id,
            paused_at_iso=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            operator_actions_recorded=[],
        )
        return handle

    def resume_from_human(self, handle: LiveSessionHandle) -> None:
        """Resume automation on the same live session after human operator handoff."""
        try:
            self.driver.switch_to.window(handle.window_handle)
            current_url = self.driver.current_url
            handle.operator_actions_recorded.append(f"Resumed at URL: {current_url}")
        except WebDriverException as e:
            raise RuntimeError(f"Failed to resume live session {handle.session_id}: browser window lost: {e}")

    def close(self) -> None:
        try:
            self.driver.quit()
        except Exception:
            pass
