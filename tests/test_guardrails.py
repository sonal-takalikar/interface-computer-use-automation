"""
Tests for Safety Guardrails & PII Redaction.
Verifies domain allowlists, action permissions, risky action classification, and regex redaction.
"""

import unittest
from core.artifact.schema import ActionType, RiskClass
from core.guardrails.policy import PolicyEnforcer
from core.guardrails.redaction import SensitiveDataRedactor


class TestGuardrails(unittest.TestCase):

    def setUp(self):
        self.policy = PolicyEnforcer(
            allowed_domains=["127.0.0.1", "localhost", "apexcore.bank.internal"],
            allowed_actions=[ActionType.NAVIGATE, ActionType.CLICK, ActionType.FILL, ActionType.EXTRACT]
        )

    def test_allowlist_domain_validation(self):
        self.assertTrue(self.policy.validate_url("http://127.0.0.1:8080/servicing"))
        self.assertTrue(self.policy.validate_url("http://localhost:8080/member_search"))
        self.assertTrue(self.policy.validate_url("https://apexcore.bank.internal/profile"))

        with self.assertRaises(PermissionError):
            self.policy.validate_url("https://malicious-external-site.com/steal-data")

    def test_allowlist_action_validation(self):
        self.assertTrue(self.policy.validate_action(ActionType.CLICK))
        self.assertTrue(self.policy.validate_action(ActionType.FILL))

        with self.assertRaises(PermissionError):
            self.policy.validate_action(ActionType.SELECT)  # Not in custom allowed_actions

    def test_risky_action_classification(self):
        self.assertEqual(
            self.policy.classify_risk(ActionType.CLICK, "Search Member Button"),
            RiskClass.SAFE_REVERSIBLE
        )
        self.assertEqual(
            self.policy.classify_risk(ActionType.CLICK, "Continue to Authorization Button"),
            RiskClass.RISKY_IRREVERSIBLE
        )
        self.assertEqual(
            self.policy.classify_risk(ActionType.CLICK, "Confirm & Open Sub-Account"),
            RiskClass.RISKY_IRREVERSIBLE
        )

    def test_pii_and_secret_redaction(self):
        raw_log = "Member SSN is 123-45-8492 with Account 0049-8210-91. Operator token=SEC-OP-9988."
        redacted = SensitiveDataRedactor.redact_text(raw_log)

        self.assertNotIn("123-45-8492", redacted)
        self.assertIn("***-**-8492", redacted)

        self.assertNotIn("0049-8210-91", redacted)
        self.assertIn("****-****-91", redacted)

        self.assertNotIn("SEC-OP-9988", redacted)
        self.assertIn("[REDACTED_SECRET]", redacted)

    def test_redact_structure(self):
        nested = {
            "member": {"ssn": "987-65-1923", "account": "0082-1920-11"},
            "notes": ["Authorization override_code=SECRET_AUTH_99"]
        }
        sanitized = SensitiveDataRedactor.redact_structure(nested)
        self.assertEqual(sanitized["member"]["ssn"], "***-**-1923")
        self.assertEqual(sanitized["member"]["account"], "****-****-11")
        self.assertIn("[REDACTED_SECRET]", sanitized["notes"][0])


if __name__ == "__main__":
    unittest.main()
