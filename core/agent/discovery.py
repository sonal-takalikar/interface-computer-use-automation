"""
Discovery Agent & Observe-Decide-Act Loop.
Drives the live application surface using Google Gemini (or the Simulated Provider),
discovers the sequence of actions and robust locators, and outputs a DiscoveryTrace.
"""

import datetime
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from core.surface.base import SurfaceDriver, SurfaceState
from core.locators.multi_strategy import MultiStrategyLocator
from core.llm.gemini_client import LLMProvider, get_llm_provider
from core.agent.prompts import DISCOVERY_SYSTEM_PROMPT, format_observation_prompt


class TraceStep(BaseModel):
    step_number: int
    action: str
    target_description: str
    locator_strategy: Dict[str, Any]
    value: Optional[str] = None
    parameter_name: Optional[str] = None
    reasoning: str = ""
    is_risky: bool = False
    checkpoint: Optional[Dict[str, Any]] = None
    extractions: List[Dict[str, Any]] = Field(default_factory=list)
    status: str = "SUCCESS"
    url_after: str = ""
    duration_ms: float = 0.0


class DiscoveryTrace(BaseModel):
    goal: str
    entry_url: str
    started_at_iso: str
    completed_at_iso: str
    llm_model: str
    steps: List[TraceStep] = Field(default_factory=list)
    observed_outputs: Dict[str, Any] = Field(default_factory=dict)
    status: str = "COMPLETED"  # COMPLETED | FAILED | MAX_STEPS_EXCEEDED


class DiscoveryAgent:
    """Agent running the LLM-driven Observe-Decide-Act loop."""

    def __init__(
        self,
        surface: SurfaceDriver,
        llm_provider: Optional[LLMProvider] = None,
        max_steps: int = 8
    ):
        self.surface = surface
        self.llm = llm_provider or get_llm_provider()
        self.max_steps = max_steps

    def discover(self, goal: str, entry_url: str) -> DiscoveryTrace:
        """Run the discovery loop against the live application."""
        start_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        trace = DiscoveryTrace(
            goal=goal,
            entry_url=entry_url,
            started_at_iso=start_iso,
            completed_at_iso="",
            llm_model=getattr(self.llm, "model_name", "SimulatedGeminiProvider"),
            steps=[],
            observed_outputs={},
            status="IN_PROGRESS"
        )

        print(f"\n[Discovery Agent] Initiating discovery run for goal: '{goal}'")
        print(f"[Discovery Agent] Navigating to entry URL: {entry_url}")
        self.surface.navigate(entry_url)

        history: List[Dict[str, Any]] = []
        filled_inputs = set()

        for step_idx in range(1, self.max_steps + 1):
            step_start = time.time()
            state = self.surface.get_state()

            # Append hint about filled inputs into observation if needed
            page_context = state.page_text
            if filled_inputs:
                page_context += f"\n[Context Notes: Inputs already filled: {list(filled_inputs)}]"

            prompt = format_observation_prompt(
                goal=goal,
                url=state.url,
                title=state.title,
                controls=state.controls,
                page_text=page_context,
                history=history
            )

            print(f"[Discovery Agent] Step {step_idx} - Observing page '{state.title}' ({state.url})")
            decision = self.llm.decide(prompt, DISCOVERY_SYSTEM_PROMPT)
            action = decision.get("action", "COMPLETE").upper()
            target_desc = decision.get("control_description", "Unknown target")
            loc_dict = decision.get("locator_strategy", {})
            value = decision.get("value")
            param_name = decision.get("parameter_name")
            reasoning = decision.get("reasoning", "")
            is_risky = decision.get("is_risky", False)
            checkpoint = decision.get("checkpoint")
            extractions = decision.get("extractions", [])
            is_terminal = decision.get("is_terminal", False)

            print(f"[Discovery Agent] Step {step_idx} - Decision: {action} on '{target_desc}'")
            if reasoning:
                print(f"                 Reasoning: {reasoning}")
            if is_risky:
                print(f"                 ⚠️ Action flagged as RISKY_IRREVERSIBLE")

            # Execute action on the surface
            locator = MultiStrategyLocator.model_validate(loc_dict) if loc_dict else MultiStrategyLocator()
            step_status = "SUCCESS"

            try:
                if action == "CLICK":
                    self.surface.click(locator)
                elif action == "FILL":
                    self.surface.type_text(locator, value or "")
                    if param_name:
                        filled_inputs.add(param_name)
                    else:
                        filled_inputs.add(target_desc)
                elif action == "SELECT":
                    self.surface.select_option(locator, value or "")
                elif action == "NAVIGATE":
                    self.surface.navigate(value or entry_url)
                elif action == "EXTRACT":
                    # Perform extractions
                    for ext in extractions:
                        var_name = ext["variable_name"]
                        ext_target = MultiStrategyLocator.model_validate(ext.get("target", {}))
                        extracted_val = self.surface.extract_text(ext_target)
                        trace.observed_outputs[var_name] = extracted_val
                        print(f"[Discovery Agent] Extracted '{var_name}': {extracted_val}")
                elif action == "COMPLETE":
                    is_terminal = True
            except Exception as e:
                step_status = f"FAILED: {e}"
                print(f"[Discovery Agent] Step {step_idx} execution warning: {e}")

            duration_ms = (time.time() - step_start) * 1000.0
            url_after = self.surface.get_current_url()

            trace_step = TraceStep(
                step_number=step_idx,
                action=action,
                target_description=target_desc,
                locator_strategy=loc_dict,
                value=value,
                parameter_name=param_name,
                reasoning=reasoning,
                is_risky=is_risky,
                checkpoint=checkpoint,
                extractions=extractions,
                status=step_status,
                url_after=url_after,
                duration_ms=duration_ms
            )
            trace.steps.append(trace_step)

            history.append({
                "step": step_idx,
                "action": action,
                "target": target_desc,
                "status": step_status
            })

            if is_terminal or action == "COMPLETE":
                trace.status = "COMPLETED"
                break
        else:
            trace.status = "MAX_STEPS_EXCEEDED"

        trace.completed_at_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        print(f"[Discovery Agent] Discovery finished with status: {trace.status} ({len(trace.steps)} steps)\n")
        return trace
