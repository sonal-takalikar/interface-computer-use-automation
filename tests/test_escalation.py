"""
Tests for Human-in-the-Loop Escalation & Same-Session Live Handoff.
Verifies:
- Taxonomy enforcement (BUSINESS_OUTCOME, RECOVERABLE_ERROR, ESCALATED, HARD_FAILURE)
- Genuine stuck-state detection and same-session handoff
- Non-interactive escalation return
- Policy/allowlist violations bypass escalation directly to HARD_FAILURE
- Normal business outcomes bypass escalation directly to BUSINESS_OUTCOME
- Checkpoint failure escalation and post-intervention re-verification
"""

import unittest
from typing import Optional
from core.artifact.schema import (
    ActionType,
    AssertionType,
    BusinessOutcomeRule,
    CapabilityArtifact,
    CapabilityMetadata,
    CapabilityStep,
    CheckpointAssertion,
    RiskClass,
    SafetyPolicy,
)
from core.escalation.manager import EscalationManager
from core.locators.multi_strategy import MultiStrategyLocator
from core.replay.engine import DeterministicReplayEngine, ResultStatus
from core.surface.base import LiveSessionHandle, SurfaceDriver, SurfaceState


class MockSurfaceForEscalation(SurfaceDriver):
    def __init__(self):
        self.session_id = "sess_live_123"
        self.url = "http://127.0.0.1:8080/servicing"
        self.window_handle = "CDwindow-449102"
        self.paused = False
        self.resumed = False
        self.clicks = []
        self.typed = {}
        self.fail_next_click_with: Optional[Exception] = None
        self.fail_always_click_with: Optional[Exception] = None
        self.page_text = "Welcome to Servicing Console"
        self.controls = []

    def navigate(self, url: str) -> None:
        self.url = url

    def get_current_url(self) -> str:
        return self.url

    def get_title(self) -> str:
        return "ApexCore Servicing"

    def get_state(self) -> SurfaceState:
        return SurfaceState(url=self.url, title="ApexCore Servicing", page_text=self.page_text, controls=self.controls)

    def click(self, locator: MultiStrategyLocator) -> bool:
        if self.fail_always_click_with:
            raise self.fail_always_click_with
        if self.fail_next_click_with:
            err = self.fail_next_click_with
            self.fail_next_click_with = None  # Clear so retry succeeds
            raise err
        self.clicks.append(locator.description)
        return True

    def type_text(self, locator: MultiStrategyLocator, text: str, clear=True) -> bool:
        self.typed[locator.description] = text
        return True

    def select_option(self, locator, value) -> bool:
        return True

    def extract_text(self, locator) -> str:
        return "$12,450.00"

    def capture_screenshot(self) -> bytes:
        return b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"

    def pause_for_human(self, step_id=None) -> LiveSessionHandle:
        self.paused = True
        return LiveSessionHandle(
            session_id=self.session_id,
            window_handle=self.window_handle,
            paused_url=self.url,
            paused_step_id=step_id,
            paused_at_iso="2026-09-19T12:00:00Z"
        )

    def resume_from_human(self, handle: LiveSessionHandle) -> None:
        # Asserts resuming on the SAME window handle
        if handle.window_handle != self.window_handle:
            raise RuntimeError("CRITICAL: Resumed on a different browser window!")
        self.resumed = True
        handle.operator_actions_recorded.append("Resumed on same window handle")

    def close(self) -> None:
        pass


class TestEscalation(unittest.TestCase):

    def setUp(self):
        self.surface = MockSurfaceForEscalation()
        self.esc_mgr = EscalationManager(surface=self.surface, evidence_dir="tests/test_evidence")

    def test_risky_action_open_subaccount_triggers_same_session_handoff(self):
        """Risky irreversible action triggers escalation and resumes in the same session."""
        artifact = CapabilityArtifact(
            metadata=CapabilityMetadata(
                id="cap_subacct_test",
                name="SubAcct Test",
                created_at_iso="2026-09-09T12:00:00Z"
            ),
            inputs={},
            outputs={},
            policy=SafetyPolicy(),
            steps=[
                CapabilityStep(
                    step_id="step_01_open_subaccount",
                    description="Open Sub-Account and Debit Funds",
                    action_type=ActionType.CLICK,
                    target=MultiStrategyLocator(description="Open Sub-Account Button", css_selector="#btn_open"),
                    risk_class=RiskClass.RISKY_IRREVERSIBLE
                )
            ]
        )

        engine = DeterministicReplayEngine(
            surface=self.surface,
            escalation_mgr=self.esc_mgr,
            allow_risky_actions=False,
            auto_intervene=True
        )

        result = engine.replay(artifact)

        self.assertTrue(self.surface.paused)
        self.assertTrue(self.surface.resumed)
        self.assertEqual(len(self.esc_mgr.active_requests), 1)

        req = list(self.esc_mgr.active_requests.values())[0]
        self.assertEqual(req.step_id, "step_01_open_subaccount")
        self.assertIn("RISKY_IRREVERSIBLE", req.reason)
        self.assertEqual(req.status, "RESOLVED_AND_RESUMED")
        self.assertEqual(result.status, ResultStatus.SUCCESS)

    def test_stuck_locator_triggers_escalation_and_resumes_to_success(self):
        """Technical stuck state (click intercepted) triggers human escalation, unblocks, and succeeds on retry."""
        artifact = CapabilityArtifact(
            metadata=CapabilityMetadata(id="cap_stuck_test", name="Stuck Test", created_at_iso="2026-09-19T12:00:00Z"),
            inputs={},
            outputs={},
            policy=SafetyPolicy(),
            steps=[
                CapabilityStep(
                    step_id="step_01_search",
                    description="Click Search Member Link",
                    action_type=ActionType.CLICK,
                    target=MultiStrategyLocator(description="Search Link", css_selector="#lnk_search"),
                    risk_class=RiskClass.SAFE_REVERSIBLE
                )
            ]
        )

        # Simulate click intercepted by modal on first attempt
        self.surface.fail_next_click_with = RuntimeError(
            "ElementClickInterceptedException: Element is not clickable at point. Other element would receive the click: #modal_security_challenge"
        )

        engine = DeterministicReplayEngine(
            surface=self.surface,
            escalation_mgr=self.esc_mgr,
            auto_intervene=True
        )

        result = engine.replay(artifact)

        self.assertEqual(result.status, ResultStatus.SUCCESS)
        self.assertTrue(self.surface.paused)
        self.assertTrue(self.surface.resumed)
        self.assertEqual(len(self.esc_mgr.active_requests), 1)

        req = list(self.esc_mgr.active_requests.values())[0]
        self.assertEqual(req.step_id, "step_01_search")
        self.assertIn("ElementClickInterceptedException", req.reason)
        self.assertEqual(req.window_handle, self.surface.window_handle)
        self.assertEqual(req.status, "RESOLVED_AND_RESUMED")

        # Trace should reflect the successful resumption
        self.assertEqual(len(result.step_trace), 1)
        self.assertEqual(result.step_trace[0].status, "RESUMED_AND_SUCCEEDED")

    def test_stuck_state_in_non_interactive_env_returns_escalated(self):
        """Technical stuck state without auto-intervene returns ESCALATED status with session handle."""
        artifact = CapabilityArtifact(
            metadata=CapabilityMetadata(id="cap_stuck_escalate", name="Stuck Escalate", created_at_iso="2026-09-19T12:00:00Z"),
            inputs={},
            outputs={},
            policy=SafetyPolicy(),
            steps=[
                CapabilityStep(
                    step_id="step_01_search",
                    description="Click Search Member Link",
                    action_type=ActionType.CLICK,
                    target=MultiStrategyLocator(description="Search Link", css_selector="#lnk_search"),
                    risk_class=RiskClass.SAFE_REVERSIBLE
                )
            ]
        )

        self.surface.fail_next_click_with = RuntimeError("TimeoutException: Locator not found")

        non_interactive_esc_mgr = EscalationManager(surface=self.surface, evidence_dir="tests/test_evidence", interactive=False)
        engine = DeterministicReplayEngine(
            surface=self.surface,
            escalation_mgr=non_interactive_esc_mgr,
            auto_intervene=False  # Simulates operator pending in non-interactive environment
        )

        result = engine.replay(artifact)

        self.assertEqual(result.status, ResultStatus.ESCALATED)
        self.assertIsNotNone(result.escalation_handle)
        self.assertEqual(result.escalation_handle["window_handle"], self.surface.window_handle)
        self.assertTrue(self.surface.paused)
        self.assertFalse(self.surface.resumed)

    def test_policy_allowlist_violation_returns_hard_failure_without_escalation(self):
        """Action/domain allowlist policy violation returns HARD_FAILURE immediately without human escalation."""
        artifact = CapabilityArtifact(
            metadata=CapabilityMetadata(id="cap_policy_test", name="Policy Test", created_at_iso="2026-09-19T12:00:00Z"),
            inputs={},
            outputs={},
            policy=SafetyPolicy(),
            steps=[
                CapabilityStep(
                    step_id="step_01_disallowed",
                    description="Disallowed System Action",
                    action_type=ActionType.CLICK,
                    target=MultiStrategyLocator(description="Forbidden Button", css_selector="#btn_forbidden"),
                    risk_class=RiskClass.SAFE_REVERSIBLE
                )
            ]
        )

        self.surface.fail_always_click_with = PermissionError("Action allowlist violation: CLICK is not permitted")

        engine = DeterministicReplayEngine(
            surface=self.surface,
            escalation_mgr=self.esc_mgr,
            auto_intervene=True
        )

        result = engine.replay(artifact)

        self.assertEqual(result.status, ResultStatus.HARD_FAILURE)
        self.assertEqual(len(self.esc_mgr.active_requests), 0)  # Must NOT escalate policy violations
        self.assertFalse(self.surface.paused)

    def test_business_outcome_returns_business_outcome_without_escalation(self):
        """Recognized business outcomes (e.g. MEMBER_NOT_FOUND) return BUSINESS_OUTCOME without escalation."""
        artifact = CapabilityArtifact(
            metadata=CapabilityMetadata(id="cap_bo_test", name="Business Outcome Test", created_at_iso="2026-09-19T12:00:00Z"),
            inputs={},
            outputs={},
            policy=SafetyPolicy(),
            steps=[
                CapabilityStep(
                    step_id="step_01_search",
                    description="Click Search Member Link",
                    action_type=ActionType.CLICK,
                    target=MultiStrategyLocator(description="Search Link", css_selector="#lnk_search"),
                    risk_class=RiskClass.SAFE_REVERSIBLE
                )
            ],
            business_outcomes=[
                BusinessOutcomeRule(
                    outcome_code="MEMBER_NOT_FOUND",
                    signal_text="Member record not found in system partition",
                    description="Member does not exist"
                )
            ]
        )

        # Page text contains the business outcome signal
        self.surface.page_text = "ERROR: Member record not found in system partition."

        engine = DeterministicReplayEngine(
            surface=self.surface,
            escalation_mgr=self.esc_mgr,
            auto_intervene=True
        )

        result = engine.replay(artifact)

        self.assertEqual(result.status, ResultStatus.BUSINESS_OUTCOME)
        self.assertIsNotNone(result.business_outcome)
        self.assertEqual(result.business_outcome["outcome_code"], "MEMBER_NOT_FOUND")
        self.assertEqual(len(self.esc_mgr.active_requests), 0)  # Must NOT escalate business outcomes

    def test_terminal_checkpoint_failure_triggers_escalation_and_reverifies(self):
        """Failing checkpoint escalates to human operator and re-verifies successfully upon resume."""
        artifact = CapabilityArtifact(
            metadata=CapabilityMetadata(id="cap_chk_test", name="Checkpoint Test", created_at_iso="2026-09-19T12:00:00Z"),
            inputs={},
            outputs={},
            policy=SafetyPolicy(),
            steps=[
                CapabilityStep(
                    step_id="step_01_navigate",
                    description="Navigate to dashboard",
                    action_type=ActionType.NAVIGATE,
                    value_template="http://127.0.0.1:8080/servicing",
                    risk_class=RiskClass.SAFE_REVERSIBLE
                )
            ],
            success_checkpoint=CheckpointAssertion(
                assertion_type=AssertionType.TEXT_CONTAINS,
                expected_value="Verified Terminal State",
                description="Verify completed terminal state"
            )
        )

        # Initially, page text does not contain expected string
        self.surface.page_text = "Pending Loading..."

        # Subclass / hook EscalationManager to modify state during takeover
        class StateModifyingEscalationManager(EscalationManager):
            def __init__(self, surface):
                super().__init__(surface=surface, evidence_dir="tests/test_evidence")

            def request_intervention(self, *args, **kwargs):
                handle = super().request_intervention(*args, **kwargs)
                # Operator fixes the state in the live browser
                self.surface.page_text = "Verified Terminal State - Completed"
                return handle

        mod_esc_mgr = StateModifyingEscalationManager(self.surface)
        engine = DeterministicReplayEngine(
            surface=self.surface,
            escalation_mgr=mod_esc_mgr,
            auto_intervene=True
        )

        result = engine.replay(artifact)

        self.assertEqual(result.status, ResultStatus.SUCCESS)
        self.assertTrue(self.surface.paused)
        self.assertTrue(self.surface.resumed)
        self.assertEqual(len(mod_esc_mgr.active_requests), 1)

    def test_failed_retry_after_intervention_returns_hard_failure(self):
        """If action still fails after operator intervention, it records HARD_FAILURE."""
        artifact = CapabilityArtifact(
            metadata=CapabilityMetadata(id="cap_unresolved_test", name="Unresolved Test", created_at_iso="2026-09-19T12:00:00Z"),
            inputs={},
            outputs={},
            policy=SafetyPolicy(),
            steps=[
                CapabilityStep(
                    step_id="step_01_broken",
                    description="Permanently broken button",
                    action_type=ActionType.CLICK,
                    target=MultiStrategyLocator(description="Broken Button", css_selector="#btn_broken"),
                    risk_class=RiskClass.SAFE_REVERSIBLE
                )
            ]
        )

        # Action consistently fails even after takeover
        self.surface.fail_always_click_with = RuntimeError("Hardware fault: input device disabled")

        engine = DeterministicReplayEngine(
            surface=self.surface,
            escalation_mgr=self.esc_mgr,
            auto_intervene=True
        )

        result = engine.replay(artifact)

        self.assertEqual(result.status, ResultStatus.HARD_FAILURE)
        self.assertTrue(self.surface.paused)
        self.assertTrue(self.surface.resumed)
        self.assertIn("Action failed after operator intervention", result.error["message"])


if __name__ == "__main__":
    unittest.main()
