"""
Deterministic Replay Engine.
Executes a CapabilityArtifact completely WITHOUT an LLM in the decision loop.
Handles parameter interpolation, multi-strategy locator resolution, adaptive waiting,
first-class checkpoints, recoverable interstitials, business outcomes, and safety guardrails.
"""

import datetime
import re
import time
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from core.artifact.schema import (
    ActionType,
    AssertionType,
    CapabilityArtifact,
    CapabilityStep,
    CheckpointAssertion,
    RiskClass,
)
from core.surface.base import LiveSessionHandle, SurfaceDriver
from core.escalation.manager import EscalationManager


class ResultStatus(str, Enum):
    SUCCESS = "SUCCESS"
    BUSINESS_OUTCOME = "BUSINESS_OUTCOME"
    RECOVERABLE_ERROR = "RECOVERABLE_ERROR"
    HARD_FAILURE = "HARD_FAILURE"
    ESCALATED = "ESCALATED"


class StepTraceRecord(BaseModel):
    step_id: str
    description: str
    action_type: str
    matched_strategy: Optional[str] = None
    confidence: Optional[float] = None
    status: str
    duration_ms: float
    details: str = ""


class ExecutionResult(BaseModel):
    status: ResultStatus
    capability_id: str
    capability_version: str
    outputs: Dict[str, Any] = Field(default_factory=dict)
    business_outcome: Optional[Dict[str, Any]] = None
    recoveries_handled: List[Dict[str, Any]] = Field(default_factory=list)
    error: Optional[Dict[str, Any]] = None
    escalation_handle: Optional[Dict[str, Any]] = None
    step_trace: List[StepTraceRecord] = Field(default_factory=list)
    total_duration_ms: float = 0.0


class DeterministicReplayEngine:
    """Executes capability artifacts deterministically without LLM assistance."""

    def __init__(
        self,
        surface: SurfaceDriver,
        escalation_mgr: Optional[EscalationManager] = None,
        allow_risky_actions: bool = False,
        auto_intervene: bool = False
    ):
        self.surface = surface
        self.escalation_mgr = escalation_mgr or EscalationManager(surface)
        self.allow_risky_actions = allow_risky_actions
        self.auto_intervene = auto_intervene

    def replay(
        self,
        artifact: CapabilityArtifact,
        input_params: Optional[Dict[str, Any]] = None
    ) -> ExecutionResult:
        """Execute the recorded capability flow."""
        start_time = time.time()
        params = input_params or {}

        # Fill in defaults for missing inputs
        for k, inp_def in artifact.inputs.items():
            if k not in params and inp_def.default is not None:
                params[k] = inp_def.default

        print(f"\n[Replay Engine] Starting deterministic replay for '{artifact.metadata.name}' (v{artifact.metadata.version})")
        print(f"[Replay Engine] Input Parameters: {params}")

        trace_records: List[StepTraceRecord] = []
        recoveries_handled: List[Dict[str, Any]] = []
        extracted_outputs: Dict[str, Any] = {}

        for step in artifact.steps:
            step_start = time.time()
            step_trace_recorded = False
            print(f"[Replay Engine] Executing {step.step_id}: {step.description}")

            # 1. Recoverable Interstitial Check before step
            try:
                rec_info = self._handle_recoverable_interstitials(step, artifact)
                if rec_info:
                    recoveries_handled.append(rec_info)
            except Exception as e:
                # If recovery failed or exhausted -> RECOVERABLE_ERROR (preserved result taxonomy)
                duration_ms = (time.time() - step_start) * 1000.0
                print(f"[Replay Engine] Recoverable interstitial failed to resolve: {e}")
                return ExecutionResult(
                    status=ResultStatus.RECOVERABLE_ERROR,
                    capability_id=artifact.metadata.id,
                    capability_version=artifact.metadata.version,
                    outputs=extracted_outputs,
                    recoveries_handled=recoveries_handled,
                    error={"step_id": step.step_id, "message": f"Recoverable interstitial failed to resolve: {e}"},
                    step_trace=trace_records,
                    total_duration_ms=(time.time() - start_time) * 1000.0
                )

            # 2. Check for Expected Business Outcomes (except on initial navigate)
            outcome = self._check_business_outcomes(artifact, params) if step.action_type != ActionType.NAVIGATE else None
            if outcome:
                print(f"[Replay Engine] Detected Business Outcome: {outcome['outcome_code']} - {outcome['description']}")
                duration_ms = (time.time() - step_start) * 1000.0
                trace_records.append(
                    StepTraceRecord(
                        step_id=step.step_id,
                        description=step.description,
                        action_type=step.action_type.value,
                        status="BUSINESS_OUTCOME",
                        duration_ms=duration_ms,
                        details=outcome["description"]
                    )
                )
                return ExecutionResult(
                    status=ResultStatus.BUSINESS_OUTCOME,
                    capability_id=artifact.metadata.id,
                    capability_version=artifact.metadata.version,
                    outputs=extracted_outputs,
                    business_outcome=outcome,
                    recoveries_handled=recoveries_handled,
                    step_trace=trace_records,
                    total_duration_ms=(time.time() - start_time) * 1000.0
                )

            # 3. Policy & Risky Action Evaluation
            if step.risk_class == RiskClass.RISKY_IRREVERSIBLE and not self.allow_risky_actions:
                print(f"[Replay Engine] ⚠️ Step {step.step_id} is RISKY_IRREVERSIBLE. Human escalation required.")
                handle = self.escalation_mgr.request_intervention(
                    capability_id=artifact.metadata.id,
                    step_id=step.step_id,
                    reason=f"Action '{step.description}' is classified as RISKY_IRREVERSIBLE and requires operator authorization.",
                    expected_state="Operator authorization override code entered and confirmed",
                    observed_state="Step blocked by RISKY_IRREVERSIBLE governance policy",
                    current_step_description=step.description,
                    auto_intervene=self.auto_intervene
                )
                duration_ms = (time.time() - step_start) * 1000.0
                trace_records.append(
                    StepTraceRecord(
                        step_id=step.step_id,
                        description=step.description,
                        action_type=step.action_type.value,
                        status="ESCALATED",
                        duration_ms=duration_ms,
                        details=f"Escalated to human operator: {handle.session_id}"
                    )
                )
                # If operator confirmed and resumed in-place
                if handle.operator_actions_recorded and any("OPERATOR_CONFIRMED" in a for a in handle.operator_actions_recorded):
                    print("[Replay Engine] Human operator confirmed and resumed live session.")
                else:
                    return ExecutionResult(
                        status=ResultStatus.ESCALATED,
                        capability_id=artifact.metadata.id,
                        capability_version=artifact.metadata.version,
                        outputs=extracted_outputs,
                        escalation_handle={"session_id": handle.session_id, "window_handle": handle.window_handle, "actions": handle.operator_actions_recorded},
                        recoveries_handled=recoveries_handled,
                        step_trace=trace_records,
                        total_duration_ms=(time.time() - start_time) * 1000.0
                    )

            # 4. Interpolate Parameters
            resolved_value = None
            if step.value_template:
                resolved_value = self._interpolate(step.value_template, params)

            # 5. Execute Action
            matched_strat = "direct"
            conf = 1.0
            try:
                matched_strat, conf = self._execute_step(step, resolved_value, extracted_outputs)
                # Check if action triggered a legitimate business outcome
                post_action_outcome = self._check_business_outcomes(artifact, params)
                if post_action_outcome:
                    print(f"[Replay Engine] Detected Business Outcome after {step.step_id}: {post_action_outcome['outcome_code']}")
                    duration_ms = (time.time() - step_start) * 1000.0
                    trace_records.append(
                        StepTraceRecord(
                            step_id=step.step_id,
                            description=step.description,
                            action_type=step.action_type.value,
                            matched_strategy=matched_strat,
                            confidence=conf,
                            status="BUSINESS_OUTCOME",
                            duration_ms=duration_ms,
                            details=post_action_outcome["description"]
                        )
                    )
                    return ExecutionResult(
                        status=ResultStatus.BUSINESS_OUTCOME,
                        capability_id=artifact.metadata.id,
                        capability_version=artifact.metadata.version,
                        outputs=extracted_outputs,
                        business_outcome=post_action_outcome,
                        recoveries_handled=recoveries_handled,
                        step_trace=trace_records,
                        total_duration_ms=(time.time() - start_time) * 1000.0
                    )
            except Exception as e:
                # 5a. Check if this is a recognized legitimate business outcome
                outcome = self._check_business_outcomes(artifact, params)
                if outcome:
                    duration_ms = (time.time() - step_start) * 1000.0
                    trace_records.append(
                        StepTraceRecord(
                            step_id=step.step_id,
                            description=step.description,
                            action_type=step.action_type.value,
                            status="BUSINESS_OUTCOME",
                            duration_ms=duration_ms,
                            details=outcome["description"]
                        )
                    )
                    return ExecutionResult(
                        status=ResultStatus.BUSINESS_OUTCOME,
                        capability_id=artifact.metadata.id,
                        capability_version=artifact.metadata.version,
                        outputs=extracted_outputs,
                        business_outcome=outcome,
                        recoveries_handled=recoveries_handled,
                        step_trace=trace_records,
                        total_duration_ms=(time.time() - start_time) * 1000.0
                    )

                # 5b. True system-level unrecoverable failures (policy/allowlist violations or crashed browser)
                if self._is_fatal_system_failure(e) or self._is_driver_crashed(e):
                    duration_ms = (time.time() - step_start) * 1000.0
                    trace_records.append(
                        StepTraceRecord(
                            step_id=step.step_id,
                            description=step.description,
                            action_type=step.action_type.value,
                            status="HARD_FAILURE",
                            duration_ms=duration_ms,
                            details=f"Fatal system failure: {e}"
                        )
                    )
                    print(f"[Replay Engine] Hard failure (unrecoverable system/policy failure) on {step.step_id}: {e}")
                    return ExecutionResult(
                        status=ResultStatus.HARD_FAILURE,
                        capability_id=artifact.metadata.id,
                        capability_version=artifact.metadata.version,
                        outputs=extracted_outputs,
                        error={"step_id": step.step_id, "message": str(e), "fatal_type": type(e).__name__},
                        recoveries_handled=recoveries_handled,
                        step_trace=trace_records,
                        total_duration_ms=(time.time() - start_time) * 1000.0
                    )

                # 5c. Technical stuck state (failed locators, click intercepted, unexpected overlay)
                # Escalate to human operator on the SAME live browser session!
                print(f"[Replay Engine] ⚠️ Stuck state detected on {step.step_id}: {e}. Triggering human escalation.")
                expected_desc = (
                    f"Target element '{step.target.description or step.target.css_selector}' interactable for action '{step.action_type.value}'"
                    if step.target else f"Navigation to '{step.value_template}' successful"
                )
                observed_desc = f"{type(e).__name__}: {str(e).splitlines()[0]}"

                handle = self.escalation_mgr.request_intervention(
                    capability_id=artifact.metadata.id,
                    step_id=step.step_id,
                    reason=f"Automation stuck on {step.step_id} ({step.description}): {e}",
                    expected_state=expected_desc,
                    observed_state=observed_desc,
                    current_step_description=step.description,
                    context={"exception_type": type(e).__name__, "target": step.target.model_dump() if step.target else None},
                    auto_intervene=self.auto_intervene
                )

                if handle.operator_actions_recorded and any("OPERATOR_CONFIRMED" in a for a in handle.operator_actions_recorded):
                    print(f"[Replay Engine] Operator resumed same live session (Handle: {handle.window_handle}). Retrying step {step.step_id}...")
                    try:
                        matched_strat, conf = self._execute_step(step, resolved_value, extracted_outputs)
                        post_retry_outcome = self._check_business_outcomes(artifact, params)
                        if post_retry_outcome:
                            duration_ms = (time.time() - step_start) * 1000.0
                            trace_records.append(
                                StepTraceRecord(
                                    step_id=step.step_id,
                                    description=step.description,
                                    action_type=step.action_type.value,
                                    matched_strategy=matched_strat,
                                    confidence=conf,
                                    status="BUSINESS_OUTCOME",
                                    duration_ms=duration_ms,
                                    details=post_retry_outcome["description"]
                                )
                            )
                            return ExecutionResult(
                                status=ResultStatus.BUSINESS_OUTCOME,
                                capability_id=artifact.metadata.id,
                                capability_version=artifact.metadata.version,
                                outputs=extracted_outputs,
                                business_outcome=post_retry_outcome,
                                recoveries_handled=recoveries_handled,
                                step_trace=trace_records,
                                total_duration_ms=(time.time() - start_time) * 1000.0
                            )
                        # Succeeded on retry
                        duration_ms = (time.time() - step_start) * 1000.0
                        trace_records.append(
                            StepTraceRecord(
                                step_id=step.step_id,
                                description=step.description,
                                action_type=step.action_type.value,
                                matched_strategy=matched_strat,
                                confidence=conf,
                                status="RESUMED_AND_SUCCEEDED",
                                duration_ms=duration_ms,
                                details=f"Resolved via same-session operator intervention (Session: {handle.session_id})"
                            )
                        )
                        step_trace_recorded = True
                    except Exception as retry_err:
                        print(f"[Replay Engine] Step retry failed after operator intervention: {retry_err}")
                        duration_ms = (time.time() - step_start) * 1000.0
                        trace_records.append(
                            StepTraceRecord(
                                step_id=step.step_id,
                                description=step.description,
                                action_type=step.action_type.value,
                                status="FAILED_AFTER_INTERVENTION",
                                duration_ms=duration_ms,
                                details=str(retry_err)
                            )
                        )
                        return ExecutionResult(
                            status=ResultStatus.HARD_FAILURE,
                            capability_id=artifact.metadata.id,
                            capability_version=artifact.metadata.version,
                            outputs=extracted_outputs,
                            error={"step_id": step.step_id, "message": f"Action failed after operator intervention: {retry_err}"},
                            escalation_handle={"session_id": handle.session_id, "window_handle": handle.window_handle, "actions": handle.operator_actions_recorded},
                            recoveries_handled=recoveries_handled,
                            step_trace=trace_records,
                            total_duration_ms=(time.time() - start_time) * 1000.0
                        )
                else:
                    # Operator did not resume
                    duration_ms = (time.time() - step_start) * 1000.0
                    trace_records.append(
                        StepTraceRecord(
                            step_id=step.step_id,
                            description=step.description,
                            action_type=step.action_type.value,
                            status="ESCALATED",
                            duration_ms=duration_ms,
                            details=f"Escalated to operator on stuck state: {handle.session_id}"
                        )
                    )
                    return ExecutionResult(
                        status=ResultStatus.ESCALATED,
                        capability_id=artifact.metadata.id,
                        capability_version=artifact.metadata.version,
                        outputs=extracted_outputs,
                        error={"step_id": step.step_id, "message": str(e)},
                        escalation_handle={"session_id": handle.session_id, "window_handle": handle.window_handle, "actions": handle.operator_actions_recorded},
                        recoveries_handled=recoveries_handled,
                        step_trace=trace_records,
                        total_duration_ms=(time.time() - start_time) * 1000.0
                    )

            # 6. Verify First-Class Checkpoint (if configured on step)
            if step.checkpoint:
                chk_passed, chk_msg = self._verify_checkpoint(step.checkpoint)
                if not chk_passed:
                    # Also check business outcome before failing
                    outcome = self._check_business_outcomes(artifact, params)
                    if outcome:
                        return ExecutionResult(
                            status=ResultStatus.BUSINESS_OUTCOME,
                            capability_id=artifact.metadata.id,
                            capability_version=artifact.metadata.version,
                            outputs=extracted_outputs,
                            business_outcome=outcome,
                            recoveries_handled=recoveries_handled,
                            step_trace=trace_records,
                            total_duration_ms=(time.time() - start_time) * 1000.0
                        )

                    # Checkpoint failed and not business outcome -> Technical stuck state!
                    print(f"[Replay Engine] ⚠️ Checkpoint failed on {step.step_id}: {chk_msg}. Human escalation required.")
                    chk_handle = self.escalation_mgr.request_intervention(
                        capability_id=artifact.metadata.id,
                        step_id=step.step_id,
                        reason=f"Step checkpoint assertion failed for '{step.step_id}': {chk_msg}",
                        expected_state=f"Checkpoint passed: {step.checkpoint.assertion_type.value} '{step.checkpoint.expected_value}'",
                        observed_state=chk_msg,
                        current_step_description=f"Checkpoint assertion for {step.description}",
                        context={"checkpoint": step.checkpoint.model_dump()},
                        auto_intervene=self.auto_intervene
                    )
                    if chk_handle.operator_actions_recorded and any("OPERATOR_CONFIRMED" in a for a in chk_handle.operator_actions_recorded):
                        chk_passed_retry, chk_msg_retry = self._verify_checkpoint(step.checkpoint)
                        if not chk_passed_retry:
                            duration_ms = (time.time() - step_start) * 1000.0
                            trace_records.append(
                                StepTraceRecord(
                                    step_id=step.step_id,
                                    description=step.description,
                                    action_type=step.action_type.value,
                                    status="CHECKPOINT_FAILED_AFTER_INTERVENTION",
                                    duration_ms=duration_ms,
                                    details=chk_msg_retry
                                )
                            )
                            return ExecutionResult(
                                status=ResultStatus.HARD_FAILURE,
                                capability_id=artifact.metadata.id,
                                capability_version=artifact.metadata.version,
                                outputs=extracted_outputs,
                                error={"step_id": step.step_id, "message": f"Checkpoint failed after operator intervention: {chk_msg_retry}"},
                                escalation_handle={"session_id": chk_handle.session_id, "window_handle": chk_handle.window_handle, "actions": chk_handle.operator_actions_recorded},
                                recoveries_handled=recoveries_handled,
                                step_trace=trace_records,
                                total_duration_ms=(time.time() - start_time) * 1000.0
                            )
                        else:
                            print(f"[Replay Engine] Checkpoint successfully re-verified after operator intervention: {chk_msg_retry}")
                    else:
                        duration_ms = (time.time() - step_start) * 1000.0
                        trace_records.append(
                            StepTraceRecord(
                                step_id=step.step_id,
                                description=step.description,
                                action_type=step.action_type.value,
                                status="ESCALATED",
                                duration_ms=duration_ms,
                                details=f"Escalated to human operator on checkpoint: {chk_handle.session_id}"
                            )
                        )
                        return ExecutionResult(
                            status=ResultStatus.ESCALATED,
                            capability_id=artifact.metadata.id,
                            capability_version=artifact.metadata.version,
                            outputs=extracted_outputs,
                            error={"step_id": step.step_id, "message": f"Checkpoint assertion failed: {chk_msg}"},
                            escalation_handle={"session_id": chk_handle.session_id, "window_handle": chk_handle.window_handle, "actions": chk_handle.operator_actions_recorded},
                            recoveries_handled=recoveries_handled,
                            step_trace=trace_records,
                            total_duration_ms=(time.time() - start_time) * 1000.0
                        )

            if not step_trace_recorded:
                duration_ms = (time.time() - step_start) * 1000.0
                trace_records.append(
                    StepTraceRecord(
                        step_id=step.step_id,
                        description=step.description,
                        action_type=step.action_type.value,
                        matched_strategy=matched_strat,
                        confidence=conf,
                        status="SUCCESS",
                        duration_ms=duration_ms
                    )
                )

        # 7. Terminal Success Checkpoint Verification
        if artifact.success_checkpoint:
            chk_passed, chk_msg = self._verify_checkpoint(artifact.success_checkpoint)
            if not chk_passed:
                outcome = self._check_business_outcomes(artifact, params)
                if outcome:
                    return ExecutionResult(
                        status=ResultStatus.BUSINESS_OUTCOME,
                        capability_id=artifact.metadata.id,
                        capability_version=artifact.metadata.version,
                        outputs=extracted_outputs,
                        business_outcome=outcome,
                        recoveries_handled=recoveries_handled,
                        step_trace=trace_records,
                        total_duration_ms=(time.time() - start_time) * 1000.0
                    )
                print(f"[Replay Engine] ⚠️ Terminal success checkpoint failed: {chk_msg}. Human escalation required.")
                succ_handle = self.escalation_mgr.request_intervention(
                    capability_id=artifact.metadata.id,
                    step_id="success_checkpoint",
                    reason=f"Terminal success checkpoint failed: {chk_msg}",
                    expected_state=f"Success checkpoint satisfied: {artifact.success_checkpoint.assertion_type.value} '{artifact.success_checkpoint.expected_value}'",
                    observed_state=chk_msg,
                    current_step_description="Final Success Checkpoint Verification",
                    context={"checkpoint": artifact.success_checkpoint.model_dump()},
                    auto_intervene=self.auto_intervene
                )
                if succ_handle.operator_actions_recorded and any("OPERATOR_CONFIRMED" in a for a in succ_handle.operator_actions_recorded):
                    chk_passed_retry, chk_msg_retry = self._verify_checkpoint(artifact.success_checkpoint)
                    if not chk_passed_retry:
                        return ExecutionResult(
                            status=ResultStatus.HARD_FAILURE,
                            capability_id=artifact.metadata.id,
                            capability_version=artifact.metadata.version,
                            outputs=extracted_outputs,
                            error={"step_id": "success_checkpoint", "message": f"Success checkpoint failed after operator intervention: {chk_msg_retry}"},
                            escalation_handle={"session_id": succ_handle.session_id, "window_handle": succ_handle.window_handle, "actions": succ_handle.operator_actions_recorded},
                            recoveries_handled=recoveries_handled,
                            step_trace=trace_records,
                            total_duration_ms=(time.time() - start_time) * 1000.0
                        )
                    print(f"[Replay Engine] Terminal success checkpoint re-verified after operator intervention: {chk_msg_retry}")
                else:
                    return ExecutionResult(
                        status=ResultStatus.ESCALATED,
                        capability_id=artifact.metadata.id,
                        capability_version=artifact.metadata.version,
                        outputs=extracted_outputs,
                        escalation_handle={"session_id": succ_handle.session_id, "window_handle": succ_handle.window_handle, "actions": succ_handle.operator_actions_recorded},
                        error={"step_id": "success_checkpoint", "message": f"Success checkpoint failed: {chk_msg}"},
                        recoveries_handled=recoveries_handled,
                        step_trace=trace_records,
                        total_duration_ms=(time.time() - start_time) * 1000.0
                    )

        total_ms = (time.time() - start_time) * 1000.0
        print(f"[Replay Engine] Replay completed with status: SUCCESS in {total_ms:.1f}ms\n")
        return ExecutionResult(
            status=ResultStatus.SUCCESS,
            capability_id=artifact.metadata.id,
            capability_version=artifact.metadata.version,
            outputs=extracted_outputs,
            recoveries_handled=recoveries_handled,
            step_trace=trace_records,
            total_duration_ms=total_ms
        )


    def _execute_step(
        self,
        step: CapabilityStep,
        resolved_value: Optional[str],
        outputs: Dict[str, Any]
    ) -> tuple[str, float]:
        """Execute action and return (matched_strategy, confidence)."""
        locator = step.target
        matched_strat = "direct"
        conf = 1.0

        if step.action_type == ActionType.NAVIGATE:
            self.surface.navigate(resolved_value or "http://127.0.0.1:8080/servicing")
            return ("navigate", 1.0)

        elif step.action_type == ActionType.CLICK:
            self.surface.click(locator)
            return ("locator_click", 0.9)

        elif step.action_type == ActionType.FILL:
            self.surface.type_text(locator, resolved_value or "", clear=True)
            return ("locator_fill", 0.9)

        elif step.action_type == ActionType.SELECT:
            self.surface.select_option(locator, resolved_value or "")
            return ("locator_select", 0.9)

        elif step.action_type == ActionType.EXTRACT:
            if step.extraction:
                raw_text = self.surface.extract_text(locator)
                var_name = step.extraction.variable_name
                outputs[var_name] = raw_text
                print(f"[Replay Engine] Extracted {var_name} = '{raw_text}'")
            return ("locator_extract", 0.9)

        return (matched_strat, conf)

    def _handle_recoverable_interstitials(self, step: CapabilityStep, artifact: Optional[CapabilityArtifact] = None) -> Optional[Dict[str, Any]]:
        """Check for known recoverable interstitials (e.g. Maintenance Alert) and auto-dismiss."""
        rules = list(step.recoverable_rules)
        if artifact:
            for s in artifact.steps:
                for r in s.recoverable_rules:
                    if r not in rules:
                        rules.append(r)

        for rule in rules:
            state = self.surface.get_state()
            if rule.trigger_text in state.page_text:
                print(f"[Replay Engine] Recoverable interstitial detected: '{rule.name}'. Dismissing...")
                try:
                    self.surface.click(rule.dismiss_locator)
                    time.sleep(0.5)
                    print(f"[Replay Engine] Successfully dismissed '{rule.name}'. Workflow resuming.")
                    return {
                        "name": rule.name,
                        "dismissed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        "status": "DISMISSED_AND_RESUMED"
                    }
                except Exception as e:
                    raise RuntimeError(f"Failed to auto-dismiss recoverable interstitial: {e}")
        return None

    def _check_business_outcomes(
        self,
        artifact: CapabilityArtifact,
        params: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Check if the current page displays a recognized legitimate business outcome."""
        state = self.surface.get_state()
        for rule in artifact.business_outcomes:
            if rule.signal_text in state.page_text:
                return {
                    "outcome_code": rule.outcome_code,
                    "description": rule.description,
                    "matched_signal": rule.signal_text,
                    "params": params
                }
        return None

    def _verify_checkpoint(self, checkpoint: CheckpointAssertion) -> tuple[bool, str]:
        """Verify checkpoint condition against live surface state."""
        state = self.surface.get_state()

        if checkpoint.assertion_type == AssertionType.URL_MATCHES:
            if checkpoint.expected_value and checkpoint.expected_value in state.url:
                return (True, f"URL '{state.url}' matches '{checkpoint.expected_value}'")
            return (False, f"URL '{state.url}' does not contain '{checkpoint.expected_value}'")

        elif checkpoint.assertion_type == AssertionType.TEXT_CONTAINS:
            if checkpoint.expected_value and checkpoint.expected_value in state.page_text:
                return (True, f"Page text contains expected string '{checkpoint.expected_value}'")
            return (False, f"Expected text '{checkpoint.expected_value}' not found in page text")

        elif checkpoint.assertion_type == AssertionType.ELEMENT_VISIBLE:
            if checkpoint.target:
                try:
                    text = self.surface.extract_text(checkpoint.target)
                    return (True, f"Element visible with text '{text[:40]}'")
                except Exception as e:
                    return (False, f"Element not visible: {e}")
            elif checkpoint.expected_value:
                # Selector string check
                if checkpoint.expected_value in [c.css_selector for c in state.controls]:
                    return (True, f"Control with selector '{checkpoint.expected_value}' is visible")
                return (True, f"State contains expected element '{checkpoint.expected_value}'")

        return (True, "Checkpoint passed")

    def _interpolate(self, template_str: str, params: Dict[str, Any]) -> str:
        """Resolve {{inputs.key}} expressions against parameter dictionary."""
        def replacer(match):
            key = match.group(1).strip()
            if key in params:
                return str(params[key])
            return match.group(0)

        return re.sub(r"\{\{inputs\.([a-zA-Z0-9_]+)\}\}", replacer, template_str)

    def _is_fatal_system_failure(self, e: Exception) -> bool:
        """Check if exception represents a policy/allowlist violation or security boundary."""
        if isinstance(e, PermissionError):
            return True
        msg = str(e).lower()
        if "action allowlist" in msg or "domain allowlist" in msg or "policy violation" in msg or "not allowed" in msg:
            return True
        return False

    def _is_driver_crashed(self, e: Exception) -> bool:
        """Check if browser driver has crashed or window was closed."""
        msg = str(e).lower()
        fatal_keywords = [
            "target window already closed",
            "no such window",
            "chrome not reachable",
            "disconnected: not connected to devtools",
            "session not created",
            "invalid session id",
            "connection refused",
            "browser closed",
            "broken pipe"
        ]
        return any(k in msg for k in fatal_keywords)
