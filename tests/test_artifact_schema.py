"""
Tests for Capability Artifact Schema.
Verifies schema validation, typing, serialization/deserialization, and version metadata.
"""

import json
import unittest
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
from core.artifact.storage import ArtifactStorage
from core.locators.multi_strategy import MultiStrategyLocator


class TestArtifactSchema(unittest.TestCase):

    def setUp(self):
        self.sample_artifact = CapabilityArtifact(
            metadata=CapabilityMetadata(
                id="test_cap_001",
                name="Test Member Lookup",
                version="1.0.0",
                schema_version="1.0.0",
                description="Test capability artifact",
                created_at_iso="2026-09-09T12:00:00Z",
                review_status=ReviewStatus.APPROVED
            ),
            inputs={
                "member_id": InputDefinition(
                    type="string",
                    description="Member ID",
                    default="M-10928",
                    required=True,
                    example="M-10928"
                )
            },
            outputs={
                "savings_balance": OutputDefinition(
                    type="string",
                    description="Balance of savings account",
                    shape="scalar"
                )
            },
            policy=SafetyPolicy(
                allowed_domains=["127.0.0.1", "localhost"],
                require_human_confirmation_for_risky=True
            ),
            steps=[
                CapabilityStep(
                    step_id="step_01_navigate",
                    description="Navigate to search",
                    action_type=ActionType.NAVIGATE,
                    value_template="http://127.0.0.1:8080/servicing"
                ),
                CapabilityStep(
                    step_id="step_02_fill",
                    description="Fill Member ID",
                    action_type=ActionType.FILL,
                    target=MultiStrategyLocator(
                        description="Member Number Input",
                        role="textbox",
                        name="Member ID",
                        anchor_text="Member Number:"
                    ),
                    value_template="{{inputs.member_id}}"
                ),
                CapabilityStep(
                    step_id="step_03_extract",
                    description="Extract Savings Balance",
                    action_type=ActionType.EXTRACT,
                    target=MultiStrategyLocator(
                        description="Savings Cell",
                        css_selector="#acct_balance_1"
                    ),
                    extraction=ExtractionRule(
                        variable_name="savings_balance",
                        target_type="string"
                    )
                )
            ],
            business_outcomes=[
                BusinessOutcomeRule(
                    outcome_code="MEMBER_NOT_FOUND",
                    signal_text="does not exist in institution partition",
                    description="Member record not found"
                )
            ],
            success_checkpoint=CheckpointAssertion(
                assertion_type=AssertionType.TEXT_CONTAINS,
                description="Verify account balances table",
                expected_value="Account Summary & Ledger Balances"
            )
        )

    def test_schema_serialization_and_deserialization(self):
        """Test round-trip JSON serialization and validation."""
        json_str = self.sample_artifact.model_dump_json()
        loaded = CapabilityArtifact.model_validate_json(json_str)

        self.assertEqual(loaded.metadata.id, "test_cap_001")
        self.assertEqual(loaded.metadata.version, "1.0.0")
        self.assertEqual(len(loaded.steps), 3)
        self.assertEqual(loaded.inputs["member_id"].default, "M-10928")
        self.assertEqual(loaded.steps[1].value_template, "{{inputs.member_id}}")
        self.assertEqual(loaded.steps[1].target.anchor_text, "Member Number:")

    def test_version_and_metadata_validation(self):
        """Ensure schema captures application context and review state."""
        self.assertEqual(self.sample_artifact.metadata.review_status, ReviewStatus.APPROVED)
        self.assertEqual(self.sample_artifact.metadata.target_app, "ApexCore 2008 Servicing Console")
        self.assertEqual(self.sample_artifact.metadata.vendor, "ApexCore Banking Solutions")

    def test_invalid_action_type_rejection(self):
        """Ensure invalid action types trigger Pydantic validation error."""
        data = json.loads(self.sample_artifact.model_dump_json())
        data["steps"][0]["action_type"] = "INVALID_UNSAFE_ACTION"
        with self.assertRaises(Exception):
            CapabilityArtifact.model_validate(data)


if __name__ == "__main__":
    unittest.main()
