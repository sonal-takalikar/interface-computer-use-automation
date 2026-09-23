"""
LLM Provider Abstraction & Google Gemini Client.
Supports Google Gemini API via GEMINI_API_KEY in .env,
and includes an offline Simulated Provider for deterministic testing and review.
"""

import json
import os
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from dotenv import load_dotenv

load_dotenv()


class LLMProvider(ABC):
    """Abstract interface for discovery reasoning."""

    @abstractmethod
    def decide(self, prompt: str, system_prompt: str) -> Dict[str, Any]:
        """Generate a structured action decision given the observation prompt."""
        pass


class GeminiClient(LLMProvider):
    """Real Google Gemini API provider using GEMINI_API_KEY."""

    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "GEMINI_API_KEY is not set. Please set it in .env or pass it to GeminiClient. "
                "Alternatively, use SimulatedGeminiProvider for offline testing."
            )
        self.model_name = model_name or os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")

    def decide(self, prompt: str, system_prompt: str) -> Dict[str, Any]:
        """Call Gemini API and return parsed JSON decision."""
        import httpx

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={self.api_key}"
        headers = {"Content-Type": "application/json"}

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": f"System Context:\n{system_prompt}\n\nCurrent Observation:\n{prompt}"}]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json"
            }
        }

        try:
            response = httpx.post(url, headers=headers, json=payload, timeout=30.0)
            response.raise_for_status()
            data = response.json()
            raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(raw_text)
        except Exception as e:
            if "raw_text" in locals():
                clean = re.sub(r"^```json\s*|\s*```$", "", raw_text.strip(), flags=re.MULTILINE)
                try:
                    return json.loads(clean)
                except Exception:
                    pass
            raise RuntimeError(f"Gemini API call failed: {e}")


class SimulatedGeminiProvider(LLMProvider):
    """
    Simulated Gemini Provider.
    Emulates Gemini's reasoning for legacy banking tasks deterministically,
    enabling offline verification, CI/CD testing, and reviewer evaluation without API keys.
    """

    def decide(self, prompt: str, system_prompt: str) -> Dict[str, Any]:
        prompt_lower = prompt.lower()

        # Parse URL from prompt
        url = ""
        for line in prompt.splitlines():
            if line.startswith("URL:"):
                url = line.replace("URL:", "").strip()
                break

        # Priority 1: Member Detail Page
        if "/member_detail" in url:
            goal_line = ""
            for line in prompt.splitlines():
                if line.startswith("GOAL:"):
                    goal_line = line.lower()
                    break

            if "sub-account" in goal_line or "open a new sub-account" in goal_line or "originate" in goal_line:
                return {
                    "action": "CLICK",
                    "control_description": "Open Sub-Account Button",
                    "locator_strategy": {
                        "role": "link",
                        "name": "+ Open Sub-Account",
                        "css_selector": "#btn_act_open_subacct"
                    },
                    "value": None,
                    "reasoning": "Goal requires opening a sub-account. Navigating to sub-account origination form.",
                    "is_risky": False,
                    "checkpoint": {
                        "assertion_type": "URL_MATCHES",
                        "description": "Verify navigated to open account form",
                        "expected_value": "open_account"
                    }
                }
            else:
                return {
                    "action": "EXTRACT",
                    "control_description": "High-Yield Savings Balance",
                    "locator_strategy": {
                        "role": "cell",
                        "name": "Savings Balance",
                        "anchor_text": "High-Yield Savings",
                        "css_selector": "#acct_balance_1",
                        "attributes": {"id": "acct_balance_1"}
                    },
                    "value": None,
                    "extraction_variable": "savings_balance",
                    "extraction_type": "string",
                    "extractions": [
                        {
                            "variable_name": "savings_balance",
                            "target": {"css_selector": "#acct_balance_1"},
                            "target_type": "string"
                        }
                    ],
                    "reasoning": "Reached member profile page. Extracting member profile details and ledger balances.",
                    "is_risky": False,
                    "is_terminal": True,
                    "checkpoint": {
                        "assertion_type": "TEXT_CONTAINS",
                        "description": "Verify account summary table visible",
                        "expected_value": "Account Summary & Ledger Balances"
                    }
                }

        # Priority 2: Open Sub-Account Form Page
        if "/open_account" in url:
            if "modal_confirm_subaccount" in prompt_lower or "confirmation required" in prompt_lower:
                return {
                    "action": "COMPLETE",
                    "reasoning": "Confirmation modal for irreversible financial mutation reached.",
                    "is_risky": True,
                    "is_terminal": True
                }
            return {
                "action": "CLICK",
                "control_description": "Continue to Authorization Button",
                "locator_strategy": {
                    "role": "button",
                    "name": "Continue to Authorization",
                    "css_selector": "#btn_submit_open_acct"
                },
                "value": None,
                "reasoning": "Submitting sub-account form to trigger authorization modal. This is a RISKY_IRREVERSIBLE financial mutation.",
                "is_risky": True,
                "is_terminal": True,
                "checkpoint": {
                    "assertion_type": "ELEMENT_VISIBLE",
                    "description": "Verify confirmation modal appears",
                    "expected_value": "#modal_confirm_subaccount"
                }
            }

        # Priority 3: Member Search Query Form
        if "/member_search" in url:
            if "'member_id'" in prompt_lower or "filled: ['member_id']" in prompt_lower or "inputs already filled" in prompt_lower:
                return {
                    "action": "CLICK",
                    "control_description": "Search Member Button",
                    "locator_strategy": {
                        "role": "button",
                        "name": "Search Member",
                        "css_selector": "#ctl00_cphBody_btnSearch",
                        "attributes": {"id": "ctl00_cphBody_btnSearch", "type": "submit"}
                    },
                    "value": None,
                    "reasoning": "Member ID entered. Submitting search query form to fetch account profile.",
                    "is_risky": False,
                    "checkpoint": {
                        "assertion_type": "URL_MATCHES",
                        "description": "Verify navigated to member detail page",
                        "expected_value": "member_detail"
                    }
                }
            else:
                return {
                    "action": "FILL",
                    "control_description": "Member Number Input",
                    "locator_strategy": {
                        "role": "textbox",
                        "name": "Member ID",
                        "anchor_text": "Member Number:",
                        "css_selector": "#ctl00_cphBody_txtMemberID",
                        "attributes": {"id": "ctl00_cphBody_txtMemberID", "name": "ctl00$cphBody$txtMemberID"}
                    },
                    "value": "M-10928",
                    "parameter_name": "member_id",
                    "reasoning": "Entering target member ID M-10928 into Member Number input.",
                    "is_risky": False,
                    "checkpoint": None
                }

        # Priority 4: Home / Index / Servicing Console
        if "/servicing" in url or "/index" in url or url.endswith(":8080/") or "home console" in prompt_lower:
            return {
                "action": "CLICK",
                "control_description": "Search Member Account Link",
                "locator_strategy": {
                    "role": "link",
                    "name": "Search Member Account",
                    "anchor_text": "Search Member Account",
                    "css_selector": "#lnk_nav_member_search"
                },
                "value": None,
                "reasoning": "Observed ApexCore home console. Navigating to Member Search query form.",
                "is_risky": False,
                "checkpoint": None
            }

        # Fallback
        return {
            "action": "COMPLETE",
            "reasoning": "Goal satisfied or state processed.",
            "is_risky": False
        }


def get_llm_provider(force_simulated: bool = False) -> LLMProvider:
    """Factory helper returning GeminiClient if GEMINI_API_KEY is present, else SimulatedGeminiProvider."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if force_simulated or not api_key or api_key == "your_gemini_api_key_here":
        return SimulatedGeminiProvider()
    return GeminiClient(api_key=api_key)
