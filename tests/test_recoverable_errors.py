"""
Tests for Recoverable Error Semantics.
Verifies the refined taxonomy:
- SUCCESS = workflow completed successfully, including cases where an expected recoverable
            interstitial was automatically handled and resolved.
- RECOVERABLE_ERROR = a recoverable condition occurred but automatic recovery failed or was exhausted.
"""

import unittest
from core.artifact.schema import (
    ActionType,
    CapabilityArtifact,
    CapabilityMetadata,
    CapabilityStep,
    ExtractionRule,
    InputDefinition,
    OutputDefinition,
    RecoverableRule,
    SafetyPolicy,
)
from core.locators.multi_strategy import MultiStrategyLocator
from core.replay.engine import DeterministicReplayEngine, ResultStatus
from core.surface.base import SurfaceDriver, SurfaceState


class MockSurfaceWithRecoverableNotice(SurfaceDriver):
    def __init__(self, dismiss_succeeds: bool = True):
        self.dismiss_succeeds = dismiss_succeeds
        self.interstitial_active = True
        self.current_url = "http://127.0.0.1:8080/member_detail?id=M-10928"

    def navigate(self, url: str) -> None:
        self.current_url = url

    def get_current_url(self) -> str:
        return self.current_url

    def get_title(self) -> str:
        return "Member Detail"

    def get_state(self) -> SurfaceState:
        text = "Account Summary & Ledger Balances. Savings balance: $18,430.50"
        if self.interstitial_active:
            text = "SYSTEM NOTICE: CORE HOST MAINTENANCE WINDOW\nAlert Msg 7104: Maintenance active.\n" + text
        return SurfaceState(url=self.current_url, title="Member Detail", page_text=text)

    def click(self, locator: MultiStrategyLocator) -> bool:
        if "Acknowledge" in locator.name or "ack" in (locator.css_selector or ""):
            if self.dismiss_succeeds:
                self.interstitial_active = False
                return True
            else:
                raise RuntimeError("Dismiss click timed out: modal stuck")
        return True

    def type_text(self, locator, text, clear=True) -> bool:
        return True

    def select_option(self, locator, value) -> bool:
        return True

    def extract_text(self, locator) -> str:
        return "$18,430.50"

    def capture_screenshot(self) -> bytes:
        return b""

    def pause_for_human(self, step_id=None):
        pass

    def resume_from_human(self, handle):
        pass

    def close(self) -> None:
        pass


class TestRecoverableErrors(unittest.TestCase):

    def _build_artifact(self):
        return CapabilityArtifact(
            metadata=CapabilityMetadata(
                id="cap_rec_test",
                name="Recoverable Test",
                created_at_iso="2026-09-09T12:00:00Z"
            ),
            inputs={},
            outputs={"savings_balance": OutputDefinition(type="string")},
            policy=SafetyPolicy(),
            steps=[
                CapabilityStep(
                    step_id="step_01_read_balance",
                    description="Read Balance",
                    action_type=ActionType.EXTRACT,
                    target=MultiStrategyLocator(description="Savings Cell", css_selector="#acct_balance_1"),
                    extraction=ExtractionRule(variable_name="savings_balance", target_type="string"),
                    recoverable_rules=[
                        RecoverableRule(
                            name="Maintenance Window Notice",
                            trigger_text="SYSTEM NOTICE: CORE HOST MAINTENANCE WINDOW",
                            dismiss_locator=MultiStrategyLocator(
                                description="Acknowledge Button",
                                role="button",
                                name="Acknowledge & Proceed",
                                css_selector="#btn_ack_interstitial"
                            )
                        )
                    ]
                )
            ]
        )

    def test_interstitial_auto_dismissed_yields_success(self):
        """Case 1: Interstitial dismissed -> workflow continues -> Result is SUCCESS with recovery recorded."""
        surface = MockSurfaceWithRecoverableNotice(dismiss_succeeds=True)
        engine = DeterministicReplayEngine(surface=surface)
        artifact = self._build_artifact()

        result = engine.replay(artifact)

        self.assertEqual(result.status, ResultStatus.SUCCESS)
        self.assertEqual(result.outputs["savings_balance"], "$18,430.50")
        self.assertEqual(len(result.recoveries_handled), 1)
        self.assertEqual(result.recoveries_handled[0]["name"], "Maintenance Window Notice")
        self.assertEqual(result.recoveries_handled[0]["status"], "DISMISSED_AND_RESUMED")

    def test_interstitial_dismiss_failure_yields_recoverable_error(self):
        """Case 2: Interstitial dismissal fails -> Result is RECOVERABLE_ERROR."""
        surface = MockSurfaceWithRecoverableNotice(dismiss_succeeds=False)
        engine = DeterministicReplayEngine(surface=surface)
        artifact = self._build_artifact()

        result = engine.replay(artifact)

        self.assertEqual(result.status, ResultStatus.RECOVERABLE_ERROR)
        self.assertIn("Recoverable interstitial failed to resolve", result.error["message"])


if __name__ == "__main__":
    unittest.main()
