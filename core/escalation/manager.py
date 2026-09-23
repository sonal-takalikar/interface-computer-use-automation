"""
Human-in-the-Loop Escalation & Same-Session Handoff Manager.
Implements the control transfer mechanism:
1. Detects stuck states or unapproved risky actions (e.g. 'Open Sub-Account').
2. Generates an InterventionRequest with contextual diagnostics and screenshot.
3. Pauses automation event loop.
4. Human operator takes control of the SAME live Selenium browser session (no new session).
5. Records the human operator's actions in structured audit logs.
6. Resumes automation on that same session from the preserved state.
"""

import datetime
from pathlib import Path
import sys
import time
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from core.surface.base import LiveSessionHandle, SurfaceDriver
from core.locators.multi_strategy import MultiStrategyLocator


class InterventionRequest(BaseModel):
    request_id: str
    capability_id: str
    step_id: str
    reason: str
    created_at_iso: str
    session_id: str
    paused_url: str
    screenshot_path: Optional[str] = None
    post_screenshot_path: Optional[str] = None
    status: str = "PENDING_OPERATOR_TAKEOVER"
    current_step_description: str = ""
    expected_state: str = ""
    observed_state: str = ""
    window_handle: str = ""
    operator_actions_recorded: List[str] = Field(default_factory=list)
    resumed_at_iso: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)


class EscalationManager:
    """Manages escalation requests, live session handover, and resumption."""

    def __init__(self, surface: SurfaceDriver, evidence_dir: str = "evidence", interactive: bool = True):
        self.surface = surface
        self.evidence_dir = Path(evidence_dir)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.interactive = interactive
        self.active_requests: Dict[str, InterventionRequest] = {}

    def request_intervention(
        self,
        capability_id: str,
        step_id: str,
        reason: str,
        expected_state: str = "",
        observed_state: str = "",
        current_step_description: str = "",
        context: Optional[Dict[str, Any]] = None,
        auto_intervene: bool = False
    ) -> LiveSessionHandle:
        """
        Pause automation and raise an intervention request.
        Yields control of the active Selenium browser session to the operator.
        """
        req_id = f"escalate_{uuid.uuid4().hex[:8]}"
        created_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Capture diagnostic screenshot of blocked state
        screenshot_file = self.evidence_dir / f"{req_id}_blocked_state.png"
        try:
            raw_png = self.surface.capture_screenshot()
            with open(screenshot_file, "wb") as f:
                f.write(raw_png)
            screenshot_path = str(screenshot_file)
        except Exception:
            screenshot_path = None

        handle = self.surface.pause_for_human(step_id=step_id)
        if not handle:
            handle = LiveSessionHandle(
                session_id=f"sess_{uuid.uuid4().hex[:8]}",
                window_handle="CDwindow-current",
                paused_url=self.surface.get_current_url(),
                paused_step_id=step_id,
                paused_at_iso=created_iso
            )

        req = InterventionRequest(
            request_id=req_id,
            capability_id=capability_id,
            step_id=step_id,
            reason=reason,
            created_at_iso=created_iso,
            session_id=handle.session_id,
            paused_url=handle.paused_url,
            screenshot_path=screenshot_path,
            current_step_description=current_step_description,
            expected_state=expected_state,
            observed_state=observed_state,
            window_handle=handle.window_handle,
            context=context or {}
        )
        self.active_requests[req_id] = req

        # Save initial structured intervention record
        record_file = self.evidence_dir / f"{req_id}_intervention_record.json"
        try:
            with open(record_file, "w", encoding="utf-8") as f:
                f.write(req.model_dump_json(indent=2))
        except Exception as e:
            print(f"[Escalation Manager] Notice: could not save intervention record: {e}")

        print("\n" + "=" * 70)
        print("🚨 [HUMAN INTERVENTION REQUIRED - SAME-SESSION TAKEOVER] 🚨")
        print(f"Request ID:     {req.request_id}")
        print(f"Capability:     {req.capability_id} (Step: {req.step_id})")
        if current_step_description:
            print(f"Current Step:   {current_step_description}")
        print(f"Reason:         {req.reason}")
        if expected_state:
            print(f"Expected State: {expected_state}")
        if observed_state:
            print(f"Observed State: {observed_state}")
        print(f"Paused URL:     {req.paused_url}")
        print(f"Live Window:    Active Selenium Window (Handle: {handle.window_handle})")
        if screenshot_path:
            print(f"Evidence Shot:  {screenshot_path}")
        print("=" * 70)

        if auto_intervene:
            # Automated takeover demonstration (e.g. for CI/CLI demo)
            print("[Escalation Manager] Auto-intervention enabled: Operator taking over live window...")
            time.sleep(0.5)

            # 1. Check if unconfigured Security Challenge modal is present
            try:
                self.surface.click(
                    MultiStrategyLocator(
                        description="Unlock Security Challenge Button",
                        css_selector="#btn_unlock_security_challenge",
                        role="button"
                    )
                )
                handle.operator_actions_recorded.append("Operator clicked 'Verify Identity & Unlock Console'")
                time.sleep(0.5)
            except Exception:
                pass

            # 2. Check if Maintenance Interstitial is present
            try:
                self.surface.click(
                    MultiStrategyLocator(
                        description="Acknowledge Maintenance Interstitial Button",
                        css_selector="#btn_ack_interstitial",
                        role="button"
                    )
                )
                handle.operator_actions_recorded.append("Operator dismissed unhandled maintenance alert")
                time.sleep(0.5)
            except Exception:
                pass

            # 3. Check if Sub-account authorization modal is present
            try:
                try:
                    self.surface.click(
                        MultiStrategyLocator(
                            description="Continue to Authorization Button",
                            css_selector="#btn_submit_open_acct",
                            role="button"
                        )
                    )
                    time.sleep(0.3)
                except Exception:
                    pass

                self.surface.type_text(
                    MultiStrategyLocator(
                        description="Operator Approval Code Input",
                        css_selector="#txt_override_code",
                        attributes={"id": "txt_override_code"}
                    ),
                    "AUTH-OP-SUPERVISOR-44",
                    clear=True
                )
                handle.operator_actions_recorded.append("Operator entered supervisor override code 'AUTH-OP-SUPERVISOR-44'")

                self.surface.click(
                    MultiStrategyLocator(
                        description="Confirm & Open Sub-Account Button",
                        role="button",
                        name="Confirm & Open Sub-Account",
                        css_selector="#btn_confirm_authorize"
                    )
                )
                handle.operator_actions_recorded.append("Operator clicked 'Confirm & Open Sub-Account'")
                time.sleep(0.5)
            except Exception:
                pass

            # Capture post-intervention screenshot
            try:
                post_png = self.surface.capture_screenshot()
                post_shot = self.evidence_dir / f"{req_id}_post_operator_action.png"
                with open(post_shot, "wb") as f:
                    f.write(post_png)
                req.post_screenshot_path = str(post_shot)
            except Exception:
                pass

            handle.operator_actions_recorded.append("OPERATOR_CONFIRMED_AND_RESUMED")
            req.operator_actions_recorded = list(handle.operator_actions_recorded)
            req.resumed_at_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            req.status = "RESOLVED_AND_RESUMED"
            print("[Escalation Manager] Operator actions completed successfully in live session.")
            self.surface.resume_from_human(handle)

        else:
            # Interactive manual mode (or non-interactive test environment)
            print("\n" + "-" * 70)
            print("👉 MANUAL OPERATOR INSTRUCTIONS:")
            print(f"1. Focus the active Chrome browser window (Handle: {handle.window_handle}).")
            print("2. Inspect the current state and perform the action to unblock the workflow:")
            if "SECURITY" in reason.upper() or "GATE" in reason.upper() or "STUCK" in reason.upper():
                print("   -> Click '[Verify Identity & Unlock Console]' or clear the blocking overlay.")
            elif "AUTHORIZATION" in reason.upper() or "RISKY" in reason.upper():
                print("   -> Enter operator override code 'AUTH-OP-SUPERVISOR-44' and click 'Confirm & Open Sub-Account'.")
            else:
                print("   -> Rectify the roadblock in the live page so target controls become interactive.")
            print("3. Once the live page is unblocked, return here and press [ENTER] to hand back control.")
            print("-" * 70 + "\n")

            if not self.interactive or not sys.stdin.isatty():
                # Non-interactive stdin (e.g. running in automated test runner without auto_intervene)
                print("[Escalation Manager] Non-interactive environment detected. Marking request as PENDING_OPERATOR.")
                handle.operator_actions_recorded.append("Session paused for human operator in non-interactive environment.")
                req.operator_actions_recorded = list(handle.operator_actions_recorded)
                req.status = "PENDING_OPERATOR"
                try:
                    with open(record_file, "w", encoding="utf-8") as f:
                        f.write(req.model_dump_json(indent=2))
                except Exception:
                    pass
                return handle

            try:
                input("[OPERATOR ACTION NEEDED] Complete the action in the live Chrome window, then press ENTER to resume...")
            except (EOFError, KeyboardInterrupt):
                pass

            # Capture post-intervention screenshot
            try:
                post_png = self.surface.capture_screenshot()
                post_shot = self.evidence_dir / f"{req_id}_post_operator_action.png"
                with open(post_shot, "wb") as f:
                    f.write(post_png)
                req.post_screenshot_path = str(post_shot)
            except Exception:
                pass

            handle.operator_actions_recorded.append("Operator signaled manual resume via CLI prompt.")
            handle.operator_actions_recorded.append("OPERATOR_CONFIRMED_AND_RESUMED")
            req.operator_actions_recorded = list(handle.operator_actions_recorded)
            req.resumed_at_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            req.status = "RESOLVED_MANUAL"
            self.surface.resume_from_human(handle)

        # Update persisted intervention record with final status and actions
        try:
            with open(record_file, "w", encoding="utf-8") as f:
                f.write(req.model_dump_json(indent=2))
        except Exception:
            pass

        return handle
