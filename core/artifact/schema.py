"""
Capability Artifact Schema.
Defines the typed, versioned, and reviewable schema for an agent-invocable capability.
The artifact is decoupled from raw LLM transcripts and expresses:
- Ordered steps/actions
- Robust multi-strategy locators
- Typed input parameters
- Typed extracted outputs
- First-class checkpoints and assertions
- Business outcomes vs recoverable error handlers
- Safety & policy allowlists
- App, vendor, and version metadata
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from core.locators.multi_strategy import MultiStrategyLocator


class ActionType(str, Enum):
    NAVIGATE = "NAVIGATE"
    CLICK = "CLICK"
    FILL = "FILL"
    SELECT = "SELECT"
    EXTRACT = "EXTRACT"
    ASSERT_CHECKPOINT = "ASSERT_CHECKPOINT"


class RiskClass(str, Enum):
    SAFE_REVERSIBLE = "SAFE_REVERSIBLE"
    RISKY_IRREVERSIBLE = "RISKY_IRREVERSIBLE"


class ReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AssertionType(str, Enum):
    ELEMENT_VISIBLE = "ELEMENT_VISIBLE"
    TEXT_CONTAINS = "TEXT_CONTAINS"
    URL_MATCHES = "URL_MATCHES"
    TABLE_ROWS_MIN = "TABLE_ROWS_MIN"


class CheckpointAssertion(BaseModel):
    """First-class assertion verifying UI state after critical actions."""
    assertion_type: AssertionType
    description: str
    target: Optional[MultiStrategyLocator] = None
    expected_value: Optional[str] = None
    timeout_seconds: float = Field(default=5.0)


class ExtractionRule(BaseModel):
    """Rule defining how data is extracted from the surface and typed."""
    variable_name: str
    target_type: str = Field(default="string", description="string, float, int, list")
    regex_pattern: Optional[str] = None
    description: str = ""


class RecoverableRule(BaseModel):
    """Rule for automatically resolving a known transient or interstitial state."""
    name: str
    trigger_text: str = Field(description="Text signature identifying the interstitial")
    dismiss_locator: MultiStrategyLocator = Field(description="Locator of button/control to dismiss")
    max_retries: int = Field(default=2)


class BusinessOutcomeRule(BaseModel):
    """Rule identifying an expected legitimate domain outcome (not a failure)."""
    outcome_code: str = Field(description="e.g. MEMBER_NOT_FOUND, ACCOUNT_LOCKED")
    signal_text: str = Field(description="Text or banner signature indicating this domain state")
    description: str = ""


class InputDefinition(BaseModel):
    """Typed input parameter specification."""
    type: str = Field(default="string", description="string, int, float, bool")
    description: str = ""
    default: Optional[Any] = None
    required: bool = True
    example: Optional[str] = None


class OutputDefinition(BaseModel):
    """Typed output parameter specification."""
    type: str = Field(default="string", description="string, float, dict, list")
    description: str = ""
    shape: Optional[str] = None


class SafetyPolicy(BaseModel):
    """Policy guardrail configuration for the capability."""
    allowed_domains: List[str] = Field(default_factory=lambda: ["127.0.0.1", "localhost"])
    allowed_actions: List[ActionType] = Field(
        default_factory=lambda: [
            ActionType.NAVIGATE,
            ActionType.CLICK,
            ActionType.FILL,
            ActionType.SELECT,
            ActionType.EXTRACT,
            ActionType.ASSERT_CHECKPOINT,
        ]
    )
    require_human_confirmation_for_risky: bool = True


class CapabilityStep(BaseModel):
    """A single deterministic step within the recorded capability."""
    step_id: str
    description: str
    action_type: ActionType
    target: Optional[MultiStrategyLocator] = None
    value_template: Optional[str] = Field(default=None, description="Template string e.g. {{inputs.member_id}}")
    extraction: Optional[ExtractionRule] = None
    checkpoint: Optional[CheckpointAssertion] = None
    risk_class: RiskClass = RiskClass.SAFE_REVERSIBLE
    recoverable_rules: List[RecoverableRule] = Field(default_factory=list)
    timeout_seconds: float = 5.0


class CapabilityMetadata(BaseModel):
    """Metadata detailing capability version, application context, and review state."""
    id: str
    name: str
    version: str = "1.0.0"
    schema_version: str = "1.0.0"
    description: str = ""
    target_app: str = "ApexCore 2008 Servicing Console"
    app_version: str = "8.4.2-R3"
    vendor: str = "ApexCore Banking Solutions"
    author: str = "Discovery Agent (Gemini 2.0 Flash)"
    created_at_iso: str
    review_status: ReviewStatus = ReviewStatus.APPROVED


class CapabilityArtifact(BaseModel):
    """
    The complete, self-contained, typed, and versioned Capability Artifact.
    This is what the Artifact Compiler produces and the Replay Engine executes.
    """
    metadata: CapabilityMetadata
    inputs: Dict[str, InputDefinition]
    outputs: Dict[str, OutputDefinition]
    policy: SafetyPolicy = Field(default_factory=SafetyPolicy)
    steps: List[CapabilityStep]
    business_outcomes: List[BusinessOutcomeRule] = Field(default_factory=list)
    success_checkpoint: Optional[CheckpointAssertion] = None
