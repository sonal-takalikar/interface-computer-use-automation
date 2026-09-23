"""
Tests for Business Outcome vs System Failure Separation.
Verifies that legitimate domain states (such as "Member Not Found")
produce a BUSINESS_OUTCOME result status rather than a crash or failure.
"""

import unittest
from core.artifact.schema import (
    ActionType,
    BusinessOutcomeRule,
    CapabilityArtifact,
    CapabilityMetadata,
    CapabilityStep,
    InputDefinition,
    OutputDefinition,
    ReviewStatus,
    SafetyPolicy,
)
from core.locators.multi_strategy import MultiStrategyLocator
from core.replay.engine import DeterministicReplayEngine, ResultStatus
from core.surface.base import SurfaceDriver, SurfaceState


class MockSurfaceForBusinessOutcome(SurfaceDriver):
    def __init__(self):
        self.url = "http://127.0.0.1:8080/member_search"
        self.page_text = "Member Search Query Form"

    def navigate(self, url: str) -> None:
        self.url = url

    def get_current_url(self) -> str:
        return self.url

    def get_title(self) -> str:
        return "Member Search"

    def get_state(self) -> SurfaceState:
        return SurfaceState(url=self.url, title="Member Search", page_text=self.page_text)

    def click(self, locator) -> bool:
        # Simulate that submitting search for M-99999 displays warning banner
        self.page_text = "Warning: Member record M-99999 does not exist in institution partition 4."
        return True

    def type_text(self, locator, text: str, clear: bool = True) -> bool:
        return True

    def select_option(self, locator, value: str) -> bool:
        return True

    def extract_text(self, locator) -> str:
        return ""

    def capture_screenshot(self) -> bytes:
        return b""

    def pause_for_human(self, step_id=None):
        pass

    def resume_from_human(self, handle):
        pass

    def close(self) -> None:
        pass


class TestBusinessOutcomes(unittest.TestCase):

    def test_missing_member_yields_business_outcome_not_failure(self):
        surface = MockSurfaceForBusinessOutcome()
        artifact = CapabilityArtifact(
            metadata=CapabilityMetadata(
                id="cap_test_bo",
                name="BO Test",
                created_at_iso="2026-09-09T12:00:00Z"
            ),
            inputs={"member_id": InputDefinition(type="string", default="M-99999")},
            outputs={},
            policy=SafetyPolicy(),
            steps=[
                CapabilityStep(
                    step_id="step_01_fill",
                    description="Fill Member ID",
                    action_type=ActionType.FILL,
                    target=MultiStrategyLocator(description="Member Input", css_selector="#txt_id"),
                    value_template="{{inputs.member_id}}"
                ),
                CapabilityStep(
                    step_id="step_02_click_search",
                    description="Click Search",
                    action_type=ActionType.CLICK,
                    target=MultiStrategyLocator(description="Search Button", css_selector="#btn_search")
                )
            ],
            business_outcomes=[
                BusinessOutcomeRule(
                    outcome_code="MEMBER_NOT_FOUND",
                    signal_text="does not exist in institution partition",
                    description="Member record not located in core database"
                )
            ]
        )

        engine = DeterministicReplayEngine(surface=surface)
        result = engine.replay(artifact, input_params={"member_id": "M-99999"})

        # Crucial evaluation check: Must be BUSINESS_OUTCOME, NOT HARD_FAILURE
        self.assertEqual(result.status, ResultStatus.BUSINESS_OUTCOME)
        self.assertIsNotNone(result.business_outcome)
        self.assertEqual(result.business_outcome["outcome_code"], "MEMBER_NOT_FOUND")
        self.assertIsNone(result.error)


if __name__ == "__main__":
    unittest.main()
