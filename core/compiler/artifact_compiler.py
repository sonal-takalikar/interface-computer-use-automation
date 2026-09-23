"""
Explicit Artifact Compiler.
Decouples the raw LLM Discovery Trace from the executable Capability Artifact.
Compiles concrete steps into parameterized, typed, versioned, and reviewable
CapabilityArtifacts with robust locators, first-class checkpoints, and error rules.
"""

import datetime
from typing import Dict, List, Optional
import uuid

from core.agent.discovery import DiscoveryTrace, TraceStep
from core.artifact.schema import (
    ActionType,
    AssertionType,
    BusinessOutcomeRule,
    CapabilityArtifact,
    CapabilityMetadata,
    CapabilityStep,
    CheckpointAssertion,
    ExtractionRule,
    InputDefinition,
    OutputDefinition,
    RecoverableRule,
    ReviewStatus,
    RiskClass,
    SafetyPolicy,
)
from core.locators.multi_strategy import MultiStrategyLocator


class ArtifactCompiler:
    """Compiles a DiscoveryTrace into an agent-invocable CapabilityArtifact."""

    @classmethod
    def compile(
        cls,
        trace: DiscoveryTrace,
        capability_id: Optional[str] = None,
        capability_name: Optional[str] = None,
        version: str = "1.0.0"
    ) -> CapabilityArtifact:
        """Transform a raw discovery trace into a structured capability artifact."""
        cap_id = capability_id or f"cap_{uuid.uuid4().hex[:8]}"
        name = capability_name or f"Capability: {trace.goal[:40]}"

        # 1. Parameterization & Input Schema Derivation
        inputs: Dict[str, InputDefinition] = {}
        steps: List[CapabilityStep] = []
        outputs: Dict[str, OutputDefinition] = {}

        # Standard recoverable rules (e.g. ApexCore Maintenance Interstitial)
        standard_recoverables = [
            RecoverableRule(
                name="Maintenance Interstitial Notice",
                trigger_text="SYSTEM NOTICE: CORE HOST MAINTENANCE WINDOW",
                dismiss_locator=MultiStrategyLocator(
                    role="button",
                    name="Acknowledge & Proceed",
                    css_selector="#btn_ack_interstitial",
                    anchor_text="ALERT MSG 7104"
                ),
                max_retries=2
            )
        ]

        # Standard business outcomes for core banking queries
        standard_business_outcomes = [
            BusinessOutcomeRule(
                outcome_code="MEMBER_NOT_FOUND",
                signal_text="does not exist in institution partition",
                description="Member record not found in institution database partition."
            )
        ]

        step_counter = 0

        # Step 0: Ensure entry point navigation is first-class
        if trace.entry_url:
            step_counter += 1
            steps.append(
                CapabilityStep(
                    step_id="step_01_navigate",
                    description=f"NAVIGATE to {trace.entry_url}",
                    action_type=ActionType.NAVIGATE,
                    value_template=trace.entry_url,
                    risk_class=RiskClass.SAFE_REVERSIBLE,
                    recoverable_rules=standard_recoverables
                )
            )

        for t_step in trace.steps:
            if t_step.action.upper() == "COMPLETE":
                continue
            step_counter += 1
            step_id = f"step_{step_counter:02d}_{t_step.action.lower()}"

            # Determine action type
            try:
                act_type = ActionType(t_step.action.upper())
            except ValueError:
                act_type = ActionType.CLICK

            # Build multi-strategy locator
            loc_dict = t_step.locator_strategy or {}
            locator = MultiStrategyLocator(
                description=t_step.target_description,
                role=loc_dict.get("role"),
                name=loc_dict.get("name"),
                anchor_text=loc_dict.get("anchor_text"),
                anchor_direction=loc_dict.get("anchor_direction", "right"),
                tag_name=loc_dict.get("tag_name"),
                xpath=loc_dict.get("xpath"),
                css_selector=loc_dict.get("css_selector"),
                attributes=loc_dict.get("attributes", {})
            )

            # Parameterization logic
            value_template = None
            if t_step.value:
                param_key = t_step.parameter_name
                if not param_key:
                    # Heuristic inference: check if value looks like a member ID
                    if t_step.value.startswith("M-") or "member" in t_step.target_description.lower():
                        param_key = "member_id"
                    else:
                        param_key = f"input_{step_counter}"

                value_template = f"{{{{inputs.{param_key}}}}}"
                inputs[param_key] = InputDefinition(
                    type="string",
                    description=f"Input value for {t_step.target_description}",
                    default=t_step.value,
                    required=True,
                    example=t_step.value
                )

            # Checkpoint derivation
            checkpoint = None
            if t_step.checkpoint:
                checkpoint = CheckpointAssertion(
                    assertion_type=AssertionType(t_step.checkpoint.get("assertion_type", "URL_MATCHES")),
                    description=t_step.checkpoint.get("description", "Step verification"),
                    expected_value=t_step.checkpoint.get("expected_value", "")
                )

            # Risk classification (Mutating financial actions are RISKY_IRREVERSIBLE)
            desc_lower = t_step.target_description.lower()
            is_mutation = any(k in desc_lower for k in ["authorization", "confirm", "debit", "origination"])
            if t_step.is_risky or is_mutation:
                risk_class = RiskClass.RISKY_IRREVERSIBLE
            else:
                risk_class = RiskClass.SAFE_REVERSIBLE

            # Handle extractions
            extraction = None
            if t_step.extractions:
                for ext in t_step.extractions:
                    v_name = ext["variable_name"]
                    v_type = ext.get("target_type", "string")
                    outputs[v_name] = OutputDefinition(
                        type=v_type,
                        description=f"Extracted field {v_name}",
                        shape="scalar"
                    )
                # Primary extraction rule for step (prioritize matching target description or selector)
                primary = t_step.extractions[0]
                target_desc_lower = t_step.target_description.lower()
                step_css = t_step.locator_strategy.get("css_selector") if isinstance(t_step.locator_strategy, dict) else None
                for ext in t_step.extractions:
                    ext_name = ext["variable_name"].lower()
                    ext_target = ext.get("target", {})
                    if ext_target and step_css and ext_target.get("css_selector") == step_css:
                        primary = ext
                        break
                    if ext_name in target_desc_lower or (ext_name.replace("_", " ") in target_desc_lower):
                        primary = ext
                        break

                extraction = ExtractionRule(
                    variable_name=primary["variable_name"],
                    target_type=primary.get("target_type", "string"),
                    description=f"Extract {primary['variable_name']}"
                )

            cap_step = CapabilityStep(
                step_id=step_id,
                description=f"{t_step.action} on {t_step.target_description}",
                action_type=act_type,
                target=locator,
                value_template=value_template,
                extraction=extraction,
                checkpoint=checkpoint,
                risk_class=risk_class,
                recoverable_rules=standard_recoverables if step_counter == 1 else []
            )
            steps.append(cap_step)

        # Also add any discovered outputs from trace
        for k, v in trace.observed_outputs.items():
            if k not in outputs:
                outputs[k] = OutputDefinition(
                    type="string",
                    description=f"Discovered output {k}",
                    shape="scalar"
                )

        # Terminal success checkpoint
        success_checkpoint = CheckpointAssertion(
            assertion_type=AssertionType.TEXT_CONTAINS,
            description="Verify completed profile view with ledger balances",
            expected_value="Account Summary & Ledger Balances"
        )

        metadata = CapabilityMetadata(
            id=cap_id,
            name=name,
            version=version,
            schema_version="1.0.0",
            description=f"Compiled capability for goal: {trace.goal}",
            target_app="ApexCore 2008 Servicing Console",
            app_version="8.4.2-R3",
            vendor="ApexCore Banking Solutions",
            author=f"Artifact Compiler from {trace.llm_model}",
            created_at_iso=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            review_status=ReviewStatus.APPROVED
        )

        return CapabilityArtifact(
            metadata=metadata,
            inputs=inputs,
            outputs=outputs,
            policy=SafetyPolicy(),
            steps=steps,
            business_outcomes=standard_business_outcomes,
            success_checkpoint=success_checkpoint
        )
