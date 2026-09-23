"""
Tests for Explicit Artifact Compiler.
Verifies compilation of DiscoveryTrace into a decoupled, parameterized CapabilityArtifact.
"""

import unittest
from core.agent.discovery import DiscoveryTrace, TraceStep
from core.compiler.artifact_compiler import ArtifactCompiler
from core.artifact.schema import ActionType, RiskClass


class TestArtifactCompiler(unittest.TestCase):

    def test_trace_compilation_and_parameterization(self):
        """Verify that concrete values like 'M-10928' become parameterized inputs."""
        trace = DiscoveryTrace(
            goal="Look up member M-10928 and read their current savings balance",
            entry_url="http://127.0.0.1:8080/servicing",
            started_at_iso="2026-09-09T12:00:00Z",
            completed_at_iso="2026-09-09T12:01:00Z",
            llm_model="gemini-2.0-flash",
            steps=[
                TraceStep(
                    step_number=1,
                    action="CLICK",
                    target_description="Search Member Account Link",
                    locator_strategy={"role": "link", "name": "Search Member Account", "css_selector": "#lnk_nav_member_search"}
                ),
                TraceStep(
                    step_number=2,
                    action="FILL",
                    target_description="Member Number Input",
                    locator_strategy={"role": "textbox", "anchor_text": "Member Number:", "css_selector": "#ctl00_cphBody_txtMemberID"},
                    value="M-10928",
                    parameter_name="member_id"
                ),
                TraceStep(
                    step_number=3,
                    action="CLICK",
                    target_description="Search Member Button",
                    locator_strategy={"role": "button", "name": "Search Member", "css_selector": "#ctl00_cphBody_btnSearch"},
                    checkpoint={"assertion_type": "URL_MATCHES", "expected_value": "member_detail"}
                ),
                TraceStep(
                    step_number=4,
                    action="EXTRACT",
                    target_description="Savings Balance Cell",
                    locator_strategy={"css_selector": "#acct_balance_1"},
                    extractions=[
                        {"variable_name": "savings_balance", "target_type": "string"}
                    ]
                )
            ],
            observed_outputs={"savings_balance": "$18,430.50"}
        )

        artifact = ArtifactCompiler.compile(trace, capability_id="cap_test_lookup")

        self.assertEqual(artifact.metadata.id, "cap_test_lookup")
        self.assertIn("member_id", artifact.inputs)
        self.assertEqual(artifact.inputs["member_id"].default, "M-10928")
        self.assertEqual(artifact.steps[2].value_template, "{{inputs.member_id}}")
        self.assertIn("savings_balance", artifact.outputs)
        self.assertIsNotNone(artifact.steps[3].checkpoint)
        self.assertEqual(artifact.steps[3].checkpoint.expected_value, "member_detail")
        self.assertIsNotNone(artifact.steps[4].extraction)
        self.assertEqual(artifact.steps[4].extraction.variable_name, "savings_balance")

    def test_risky_action_classification_in_compiler(self):
        """Verify that Open Sub-Account operations are flagged as RISKY_IRREVERSIBLE."""
        trace = DiscoveryTrace(
            goal="Open a new sub-account for member M-10928",
            entry_url="http://127.0.0.1:8080/member_detail?id=M-10928",
            started_at_iso="2026-09-09T12:00:00Z",
            completed_at_iso="2026-09-09T12:01:00Z",
            llm_model="gemini-2.0-flash",
            steps=[
                TraceStep(
                    step_number=1,
                    action="CLICK",
                    target_description="Continue to Authorization Button",
                    locator_strategy={"role": "link", "name": "+ Open Sub-Account", "css_selector": "#btn_act_open_subacct"},
                    is_risky=True
                )
            ]
        )

        artifact = ArtifactCompiler.compile(trace, capability_id="cap_test_subacct")
        self.assertEqual(artifact.steps[1].risk_class, RiskClass.RISKY_IRREVERSIBLE)


if __name__ == "__main__":
    unittest.main()
