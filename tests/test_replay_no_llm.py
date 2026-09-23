"""
Test Proving Deterministic Replay Works with LLM Completely Disabled.
Ensures zero LLM dependencies exist in the production execution path.
"""

import os
import unittest
from unittest.mock import patch

from core.artifact.schema import (
    ActionType,
    AssertionType,
    CapabilityArtifact,
    CapabilityMetadata,
    CapabilityStep,
    CheckpointAssertion,
    ExtractionRule,
    InputDefinition,
    OutputDefinition,
    ReviewStatus,
    RiskClass,
    SafetyPolicy,
)
from core.locators.multi_strategy import MultiStrategyLocator
from core.replay.engine import DeterministicReplayEngine, ResultStatus
from core.surface.base import SurfaceDriver, SurfaceState


class MockSurfaceForReplay(SurfaceDriver):
    """In-memory mock surface simulating the legacy banking application."""

    def __init__(self):
        self.current_url = "http://127.0.0.1:8080/servicing"
        self.typed_values = {}
        self.clicked_steps = []

    def navigate(self, url: str) -> None:
        self.current_url = url

    def get_current_url(self) -> str:
        return self.current_url

    def get_title(self) -> str:
        return "Mock ApexCore"

    def get_state(self) -> SurfaceState:
        return SurfaceState(
            url=self.current_url,
            title="ApexCore Servicing",
            page_text="Account Summary & Ledger Balances for Johnathan Doe. Savings balance: $18,430.50"
        )

    def click(self, locator: MultiStrategyLocator) -> bool:
        self.clicked_steps.append(locator.description)
        if "Search" in locator.description:
            self.current_url = "http://127.0.0.1:8080/member_detail?id=M-10928"
        return True

    def type_text(self, locator: MultiStrategyLocator, text: str, clear: bool = True) -> bool:
        self.typed_values[locator.description] = text
        return True

    def select_option(self, locator: MultiStrategyLocator, value: str) -> bool:
        return True

    def extract_text(self, locator: MultiStrategyLocator) -> str:
        return "$18,430.50"

    def capture_screenshot(self) -> bytes:
        return b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"

    def pause_for_human(self, step_id=None):
        raise NotImplementedError("Not triggered in happy path")

    def resume_from_human(self, handle):
        pass

    def close(self) -> None:
        pass


class TestReplayNoLLM(unittest.TestCase):

    def setUp(self):
        # 1. Completely remove or invalidate any LLM API key
        if "GEMINI_API_KEY" in os.environ:
            del os.environ["GEMINI_API_KEY"]

        self.mock_surface = MockSurfaceForReplay()

        # Build a valid capability artifact
        self.artifact = CapabilityArtifact(
            metadata=CapabilityMetadata(
                id="cap_offline_test",
                name="Offline Member Balance Lookup",
                version="1.0.0",
                schema_version="1.0.0",
                description="Testing replay with zero LLM in the loop",
                created_at_iso="2026-09-09T12:00:00Z",
                review_status=ReviewStatus.APPROVED
            ),
            inputs={
                "member_id": InputDefinition(
                    type="string",
                    description="Member ID",
                    default="M-10928",
                    required=True
                )
            },
            outputs={
                "savings_balance": OutputDefinition(
                    type="string",
                    description="Extracted balance"
                )
            },
            policy=SafetyPolicy(),
            steps=[
                CapabilityStep(
                    step_id="step_01_navigate",
                    description="Navigate to Search",
                    action_type=ActionType.NAVIGATE,
                    value_template="http://127.0.0.1:8080/member_search"
                ),
                CapabilityStep(
                    step_id="step_02_fill",
                    description="Fill Member ID Input",
                    action_type=ActionType.FILL,
                    target=MultiStrategyLocator(
                        description="Member Number Input",
                        role="textbox",
                        anchor_text="Member Number:"
                    ),
                    value_template="{{inputs.member_id}}"
                ),
                CapabilityStep(
                    step_id="step_03_click_search",
                    description="Click Search Button",
                    action_type=ActionType.CLICK,
                    target=MultiStrategyLocator(
                        description="Search Button",
                        role="button",
                        name="Search Member"
                    ),
                    checkpoint=CheckpointAssertion(
                        assertion_type=AssertionType.URL_MATCHES,
                        description="Verify navigated to member detail",
                        expected_value="member_detail"
                    )
                ),
                CapabilityStep(
                    step_id="step_04_extract",
                    description="Extract Savings Balance",
                    action_type=ActionType.EXTRACT,
                    target=MultiStrategyLocator(
                        description="Savings Cell",
                        css_selector="#acct_balance_1"
                    ),
                    extraction=ExtractionRule(
                        variable_name="savings_balance",
                        target_type="string"
                    )
                )
            ],
            success_checkpoint=CheckpointAssertion(
                assertion_type=AssertionType.TEXT_CONTAINS,
                description="Verify account balances header",
                expected_value="Account Summary & Ledger Balances"
            )
        )

    def test_replay_succeeds_with_llm_disabled(self):
        """
        Verify that replay executes and extracts data without calling any LLM.
        We patch the LLM provider to raise an exception if invoked.
        """
        with patch("core.llm.gemini_client.GeminiClient.decide") as mock_gemini:
            mock_gemini.side_effect = RuntimeError("FATAL: LLM was invoked during deterministic replay!")

            engine = DeterministicReplayEngine(surface=self.mock_surface)
            result = engine.replay(self.artifact, input_params={"member_id": "M-10928"})

            # Verify Replay Status
            self.assertEqual(result.status, ResultStatus.SUCCESS)
            self.assertEqual(result.outputs["savings_balance"], "$18,430.50")
            self.assertEqual(self.mock_surface.typed_values["Member Number Input"], "M-10928")
            self.assertIn("Search Button", self.mock_surface.clicked_steps)

            # Assert Gemini LLM was NEVER called
            mock_gemini.assert_not_called()


if __name__ == "__main__":
    unittest.main()
