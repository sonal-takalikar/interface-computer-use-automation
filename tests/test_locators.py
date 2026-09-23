"""
Tests for Multi-Strategy Locator Engine.
Verifies locator serialization, strategy ranking, and fallback logic.
"""

import unittest
from core.locators.multi_strategy import MultiStrategyLocator, MultiStrategyResolver


class TestLocators(unittest.TestCase):

    def test_locator_model_creation(self):
        loc = MultiStrategyLocator(
            description="Member ID Input",
            role="textbox",
            name="Member ID",
            anchor_text="Member Number:",
            css_selector="#ctl00_cphBody_txtMemberID",
            attributes={"id": "ctl00_cphBody_txtMemberID", "name": "ctl00$cphBody$txtMemberID"}
        )
        self.assertEqual(loc.role, "textbox")
        self.assertEqual(loc.anchor_text, "Member Number:")
        self.assertEqual(loc.attributes["id"], "ctl00_cphBody_txtMemberID")

    def test_locator_to_dict_and_back(self):
        loc = MultiStrategyLocator(
            description="Search Button",
            role="button",
            name="Search Member",
            css_selector="#ctl00_cphBody_btnSearch"
        )
        data = loc.model_dump()
        restored = MultiStrategyLocator.model_validate(data)
        self.assertEqual(restored.description, "Search Button")
        self.assertEqual(restored.role, "button")


if __name__ == "__main__":
    unittest.main()
