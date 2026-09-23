"""
Safety & Policy Guardrails.
Enforces domain and route allowlists, action type permissions,
and classifies actions as SAFE_REVERSIBLE vs RISKY_IRREVERSIBLE ("Open Sub-Account").
"""

import urllib.parse
from typing import List, Optional
from core.artifact.schema import ActionType, RiskClass


class PolicyEnforcer:
    """Enforces safety constraints on URLs and action invocations."""

    DEFAULT_ALLOWED_DOMAINS = ["127.0.0.1", "localhost", "apexcore.bank.internal"]
    DEFAULT_ALLOWED_ACTIONS = [
        ActionType.NAVIGATE,
        ActionType.CLICK,
        ActionType.FILL,
        ActionType.SELECT,
        ActionType.EXTRACT,
        ActionType.ASSERT_CHECKPOINT,
    ]

    def __init__(
        self,
        allowed_domains: Optional[List[str]] = None,
        allowed_actions: Optional[List[ActionType]] = None,
        require_human_confirmation_for_risky: bool = True
    ):
        self.allowed_domains = allowed_domains or self.DEFAULT_ALLOWED_DOMAINS
        self.allowed_actions = allowed_actions or self.DEFAULT_ALLOWED_ACTIONS
        self.require_human_confirmation_for_risky = require_human_confirmation_for_risky

    def validate_url(self, url: str) -> bool:
        """Verify URL hostname belongs to the configured allowlist."""
        parsed = urllib.parse.urlparse(url)
        hostname = parsed.hostname or ""
        if not any(allowed in hostname for allowed in self.allowed_domains):
            raise PermissionError(
                f"Security Guardrail Violation: Navigation to domain '{hostname}' is not in the configured allowlist: {self.allowed_domains}"
            )
        return True

    def validate_action(self, action_type: ActionType) -> bool:
        """Verify action type is explicitly permitted."""
        if action_type not in self.allowed_actions:
            raise PermissionError(
                f"Security Guardrail Violation: Action type '{action_type}' is forbidden by policy."
            )
        return True

    def classify_risk(self, action_type: ActionType, target_description: str) -> RiskClass:
        """
        Classify action as SAFE_REVERSIBLE or RISKY_IRREVERSIBLE.
        'Open Sub-Account' and fund withdrawals are strictly classified as RISKY_IRREVERSIBLE.
        """
        desc_lower = target_description.lower()
        if (
            "authorization" in desc_lower
            or "confirm & open" in desc_lower
            or "confirm_authorize" in desc_lower
            or "origination" in desc_lower
            or "debit" in desc_lower
        ):
            return RiskClass.RISKY_IRREVERSIBLE
        return RiskClass.SAFE_REVERSIBLE
