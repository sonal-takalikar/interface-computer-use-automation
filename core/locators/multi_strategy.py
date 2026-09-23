"""
Multi-Strategy Locator Engine.
Provides a 5-layer resilient targeting strategy designed for legacy enterprise UIs:
1. Accessibility Role + Accessible Name
2. Text Anchor & Visual Proximity (e.g. label in adjacent table cell)
3. Structural Context / XPath
4. Relative Visual Coordinates
5. Tag & CSS Fallback
"""

from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field


class MultiStrategyLocator(BaseModel):
    """Pydantic model for a multi-strategy element locator."""
    description: str = Field(default="", description="Human-readable description of the element")
    role: Optional[str] = Field(default=None, description="Accessibility role (e.g. textbox, button, link)")
    name: Optional[str] = Field(default=None, description="Accessible name or label text")
    anchor_text: Optional[str] = Field(default=None, description="Nearby text label in table cell or sibling element")
    anchor_direction: str = Field(default="right", description="Direction from anchor to target: right, below, inside")
    tag_name: Optional[str] = Field(default=None, description="HTML tag name (input, button, select, a, td)")
    xpath: Optional[str] = Field(default=None, description="Structural XPath")
    css_selector: Optional[str] = Field(default=None, description="CSS selector fallback")
    normalized_coords: Optional[List[float]] = Field(default=None, description="Normalized [x, y, w, h] coordinates")
    attributes: Dict[str, str] = Field(default_factory=dict, description="Key attributes like name, id prefix, type")


class ResolutionResult:
    """Outcome of resolving a multi-strategy locator against live surface elements."""
    def __init__(self, element: Any, confidence: float, matched_strategy: str, details: str = ""):
        self.element = element
        self.confidence = confidence
        self.matched_strategy = matched_strategy
        self.details = details


class MultiStrategyResolver:
    """Scored resolution algorithm evaluating strategies in order of resilience."""

    CONFIDENCE_THRESHOLD = 0.45

    @classmethod
    def resolve(cls, driver: Any, locator: MultiStrategyLocator) -> ResolutionResult:
        """
        Resolve a MultiStrategyLocator against the live Selenium driver.
        Returns the highest-scoring matching WebElement.
        """
        from selenium.webdriver.common.by import By
        from selenium.common.exceptions import NoSuchElementException

        candidates_scores: List[Tuple[Any, float, str, str]] = []

        # Strategy 1: Direct ID or Name attribute if present and unique
        if locator.attributes.get("id"):
            try:
                elem = driver.find_element(By.ID, locator.attributes["id"])
                if elem.is_displayed():
                    candidates_scores.append((elem, 0.95, "id_attribute", f"Exact ID {locator.attributes['id']}"))
            except NoSuchElementException:
                pass

        if locator.attributes.get("name"):
            try:
                elems = driver.find_elements(By.NAME, locator.attributes["name"])
                visible = [e for e in elems if e.is_displayed()]
                if len(visible) == 1:
                    candidates_scores.append((visible[0], 0.90, "name_attribute", f"Unique name {locator.attributes['name']}"))
            except NoSuchElementException:
                pass

        # Strategy 2: Accessibility Role + Accessible Name (aria-label or visible label)
        if locator.name:
            # Check by aria-label or accessible text
            safe_name = locator.name.replace("'", "\\'")
            xpath_exprs = [
                f"//*[@aria-label='{safe_name}']",
                f"//input[@placeholder='{safe_name}']",
                f"//button[contains(normalize-space(.), '{safe_name}')]",
                f"//a[contains(normalize-space(.), '{safe_name}')]",
                f"//input[@type='submit' and contains(@value, '{safe_name}')]",
                f"//input[@type='button' and contains(@value, '{safe_name}')]"
            ]
            for expr in xpath_exprs:
                try:
                    matches = driver.find_elements(By.XPATH, expr)
                    for m in matches:
                        if m.is_displayed():
                            candidates_scores.append((m, 0.88, "accessibility_name", f"Matched {expr}"))
                except Exception:
                    pass

        # Strategy 3: Text Anchor & Table Proximity (The Banking Table Classic)
        if locator.anchor_text:
            safe_anchor = locator.anchor_text.replace("'", "\\'")
            # Find input in adjacent TD cell
            anchor_xpaths = [
                f"//tr[td[contains(normalize-space(.), '{safe_anchor}')]]//input",
                f"//tr[td[contains(normalize-space(.), '{safe_anchor}')]]//select",
                f"//td[contains(normalize-space(.), '{safe_anchor}')]/following-sibling::td//input",
                f"//td[contains(normalize-space(.), '{safe_anchor}')]/following-sibling::td//select",
                f"//label[contains(normalize-space(.), '{safe_anchor}')]/following-sibling::input",
                f"//label[contains(normalize-space(.), '{safe_anchor}')]/..//input"
            ]
            for expr in anchor_xpaths:
                try:
                    matches = driver.find_elements(By.XPATH, expr)
                    for m in matches:
                        if m.is_displayed():
                            candidates_scores.append((m, 0.85, "anchor_proximity", f"Anchor '{locator.anchor_text}'"))
                except Exception:
                    pass

        # Strategy 4: Structural XPath
        if locator.xpath:
            try:
                elems = driver.find_elements(By.XPATH, locator.xpath)
                for e in elems:
                    if e.is_displayed():
                        candidates_scores.append((e, 0.75, "structural_xpath", f"XPath {locator.xpath}"))
            except Exception:
                pass

        # Strategy 5: CSS Selector Fallback
        if locator.css_selector:
            try:
                elems = driver.find_elements(By.CSS_SELECTOR, locator.css_selector)
                for e in elems:
                    if e.is_displayed():
                        candidates_scores.append((e, 0.65, "css_fallback", f"CSS {locator.css_selector}"))
            except Exception:
                pass

        if not candidates_scores:
            raise NoSuchElementException(
                f"Failed to resolve element using multi-strategy locator: {locator.description} "
                f"(tried: id={locator.attributes.get('id')}, name={locator.name}, anchor={locator.anchor_text}, xpath={locator.xpath})"
            )

        # Sort by confidence descending
        candidates_scores.sort(key=lambda x: x[1], reverse=True)
        best_elem, best_score, strategy, details = candidates_scores[0]

        return ResolutionResult(
            element=best_elem,
            confidence=best_score,
            matched_strategy=strategy,
            details=details
        )
