# Computer-Use Automation System for Legacy Banking

A working end-to-end computer-use automation system built for legacy financial institution back-office software ("ApexCore 2008"). 

The system discovers workflows using the **Google Gemini API**, compiles discoveries into typed, versioned **capability artifacts**, replays them **deterministically with zero LLM in the decision loop**, handles runtime conditions with a **5-status result taxonomy** (separating business outcomes from recoverable errors and hard failures), enforces **safety guardrails and PII redaction**, and executes **true same-session human escalation handoff**.

---

## Architecture

$$\text{Natural Language Goal} \xrightarrow{\text{Gemini Discovery Agent}} \text{Discovery Trace} \xrightarrow{\text{Artifact Compiler}} \text{Capability Artifact} \xrightarrow{\text{Deterministic Replay Engine}} \text{Execution Result}$$

```
+---------------------------------------------------------------------------------------------------+
| 1. DISCOVERY STAGE (Google Gemini LLM in the Loop)                                                |
|   Goal + URL ---> Observe Page (DOM + Visual) ---> Gemini Decide ---> Actuate Surface (Selenium)  |
|                                                                     |                             |
|                                                                     v                             |
|                                                           Discovery Trace (.json)                 |
+---------------------------------------------------------------------------------------------------+
                                                                      |
                                                                      v
+---------------------------------------------------------------------------------------------------+
| 2. ARTIFACT COMPILER STAGE (Pure Offline Transformation)                                          |
|   Discovery Trace ---> Parameterize Inputs (e.g. M-10928 -> {{inputs.member_id}})                 |
|                   ---> Synthesize 5-Layer Multi-Strategy Locators                                 |
|                   ---> Derive First-Class Checkpoint Assertions                                   |
|                   ---> Inject Business Outcome & Recoverable Interstitial Rules                   |
|                   ---> Classify Risky Mutations ("Open Sub-Account" -> RISKY_IRREVERSIBLE)        |
|                                                                     |                             |
|                                                                     v                             |
|                                                        Capability Artifact (.json)                |
+---------------------------------------------------------------------------------------------------+
                                                                      |
                                                                      v
+---------------------------------------------------------------------------------------------------+
| 3. DETERMINISTIC REPLAY STAGE (Zero LLM in the Loop)                                             |
|   Capability Artifact + Runtime Inputs ---> Evaluate Domain & Action Allowlists                  |
|                                        ---> Interpolate Template Parameters                       |
|                                        ---> Auto-Detect & Dismiss Interstitials (SUCCESS)         |
|                                        ---> Detect Business Domain Signals (BUSINESS_OUTCOME)     |
|                                        ---> Resolve Multi-Strategy Locators (Adaptive Wait)       |
|                                        ---> Assert Post-Action Checkpoints                        |
|                                        ---> Enforce Risk Policy / Same-Session Escalation         |
|                                                                     |                             |
|                                                                     v                             |
|                                                      Typed Execution Result                       |
+---------------------------------------------------------------------------------------------------+
```

---

## Core Features & Highlights

1. **Google Gemini LLM Discovery**: Goal-driven Observe-Decide-Act loop exploring unlabelled UIs and outputting structured discovery traces.
2. **Explicit Artifact Compiler**: Completely decouples exploratory discovery traces from versioned capability artifacts.
3. **Zero-LLM Deterministic Replay**: Pure deterministic execution with no LLM calls, eliminating hallucination, token latency, and prompt injection risks.
4. **5-Layer Multi-Strategy Locators**: Combines Accessibility Role/Name, Text Anchor Proximity (for nested tables), Structural XPath, Visual Coordinates, and CSS Tag Fallbacks with confidence scoring.
5. **Refined 5-Status Result Taxonomy**:
   - `SUCCESS`: Complete execution (including cases where recoverable interstitials were automatically dismissed and logged).
   - `BUSINESS_OUTCOME`: Expected business result (e.g. `M-99999` $\rightarrow$ member not found); not an engineering failure.
   - `RECOVERABLE_ERROR`: Recoverable condition detected but recovery failed or was exhausted.
   - `HARD_FAILURE`: Technical system fault or failed checkpoint.
   - `ESCALATED`: Automation paused for human intervention.
6. **Same-Session Live Human Handoff**: Preserves the active Selenium Chrome window on the operator's display, pauses execution, enables direct manual intervention, logs audit actions, and resumes automation on the same session.
7. **Defense-in-Depth Safety**: Configurable domain allowlists, risk classification ("Open Sub-Account" as `RISKY_IRREVERSIBLE`), and regex PII sanitization.

---

## Quick Start

### 1. Environment Setup

```bash
# Clone or open repository directory
cd "interface project"

# Create and activate Python virtual environment (Python 3.11+)
python3 -m venv .venv
source .venv/bin/activate

# Install required dependencies
pip install -r requirements.txt
```

Ensure Google Chrome is installed on your machine. Selenium WebDriver automatically provisions the matching ChromeDriver.

### 2. Configuration (`.env`)

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Edit `.env`:
```env
# Google Gemini API Key for Discovery Agent
GEMINI_API_KEY=your_gemini_api_key_here

# LLM Model Name (default: gemini-3.5-flash-lite)
GEMINI_MODEL=gemini-3.5-flash-lite

# Target Application Port (default: 8080)
PORT=8080

# Browser Automation Headless Mode (true/false, default: false for visible demo)
SELENIUM_HEADLESS=false
```

> **Note**: If `GEMINI_API_KEY` is not provided or set to placeholder value, the system automatically activates `SimulatedGeminiProvider`, providing a deterministic offline discovery run for testing.

---

## Automated Demo (End-to-End Vertical Slice)

To run the complete vertical slice covering discovery, compilation, replay success, business outcome, auto-recovery, and live same-session escalation in a single command:

```bash
python -m core.cli demo
```

*(Add `--headless` if running in a headless CI/server environment without a display: `python -m core.cli demo --headless`)*

### What the Demo Executes:
1. Starts the mock legacy core-banking server (`ApexCore 2008`) on port 8080.
2. Runs **Gemini Discovery** for member lookup $\rightarrow$ produces `discovery_trace.json`.
3. Runs the **Artifact Compiler** $\rightarrow$ synthesizes `capability_member_lookup.json`.
4. Executes **Replay: Success Path** (`M-10928`) $\rightarrow$ verifies `SUCCESS` and extracts savings balance `$18,430.50`.
5. Executes **Replay: Business Outcome** (`M-99999`) $\rightarrow$ verifies `BUSINESS_OUTCOME` (`MEMBER_NOT_FOUND`).
6. Executes **Replay: Recoverable Interstitial** $\rightarrow$ auto-dismisses maintenance notice and finishes as `SUCCESS`.
7. Executes **Replay: Risky Action Escalation** ("Open Sub-Account") $\rightarrow$ pauses headful session, yields control of the live browser window to the human operator, logs intervention, and resumes.

All execution logs, JSON artifacts, and step screenshots are written to `/evidence/`.

---

## Running the Automated Test Suite

The test suite covers all unit, schema, compiler, locator, checkpoint, safety, and integration flows:

```bash
pytest -v
# Or using unittest:
python -m unittest discover -s tests -p "test_*.py"
```

All 25 tests pass in ~8 seconds:
- `test_artifact_schema.py`: Schema validation, serialization/deserialization, and version checking.
- `test_compiler.py`: Trace compilation, parameterization, and locator synthesis.
- `test_locators.py`: Multi-strategy locator resolution and confidence scoring.
- `test_checkpoints.py`: First-class checkpoint assertions verifying expected UI state.
- `test_guardrails.py`: Allowlist blocking, risk classification for "Open Sub-Account", and PII regex redaction.
- `test_replay_no_llm.py`: **Proves deterministic replay runs and extracts data with all LLM modules completely unconfigured and disabled.**
- `test_business_outcomes.py`: Validates that missing member returns `BUSINESS_OUTCOME` rather than failure.
- `test_recoverable_errors.py`: Tests that successfully handling a recoverable interstitial yields `SUCCESS`, while exhausted recovery yields `RECOVERABLE_ERROR`.
- `test_escalation.py`: Tests pause, same-session takeover, operator intervention logging, and resume.

---

## Step-by-Step CLI Usage

### 1. Launch the Mock Legacy Banking Server
```bash
python -m core.cli server --port 8080
```
Open `http://localhost:8080` in your browser to inspect the legacy "ApexCore 2008" interface.

### 2. Run Workflow Discovery
```bash
python -m core.cli discover \
  --goal "Look up member M-10928 and read their current savings balance" \
  --url "http://127.0.0.1:8080" \
  --output "evidence/discovery_trace.json"
```

### 3. Compile Trace into a Capability Artifact
```bash
python -m core.cli compile \
  --trace "evidence/discovery_trace.json" \
  --output "artifacts/capability_member_lookup.json"
```

### 4. Execute Deterministic Replay (Zero LLM)
```bash
python -m core.cli replay \
  --artifact "artifacts/capability_member_lookup.json" \
  --params '{"member_id":"M-10928"}'
```

### 5. Replay with Non-Existent Member (Business Outcome)
```bash
python -m core.cli replay \
  --artifact "artifacts/capability_member_lookup.json" \
  --params '{"member_id":"M-99999"}'
```

### 6. Replay Risky Action ("Open Sub-Account" with Human Escalation)
```bash
python -m core.cli replay \
  --artifact "artifacts/capability_open_subaccount.json" \
  --params '{"member_id":"M-10928"}'
```

---

## Project Structure

```
.
├── REPORT.md                         # Detailed design & evaluation report (exact 7 headings)
├── README.md                         # Project documentation and reproduction guide
├── .env.example                      # Configuration template
├── apps/
│   └── legacy_bank/
│       ├── server.py                 # Mock legacy banking server ("ApexCore 2008")
│       └── templates/                # Authentic 2000s nested table templates
├── artifacts/
│   ├── capability_member_lookup.json # Compiled member balance lookup capability
│   └── capability_open_subaccount.json # Compiled sub-account origination capability
├── core/
│   ├── surface/                      # SurfaceDriver abstraction & Selenium implementation
│   ├── locators/                     # 5-layer multi-strategy locator engine
│   ├── artifact/                     # Pydantic schema and storage management
│   ├── llm/                          # Google Gemini client & simulated provider
│   ├── agent/                        # Discovery agent (Observe-Decide-Act loop)
│   ├── compiler/                     # Artifact compiler (trace -> capability artifact)
│   ├── replay/                       # Zero-LLM deterministic replay engine
│   ├── guardrails/                   # Allowlist enforcement & PII regex redaction
│   ├── escalation/                   # Live same-session takeover manager
│   └── cli.py                        # Unified command-line interface
├── evidence/                         # Real run traces, logs, artifacts, and screenshots
│   ├── capability_member_lookup.json
│   ├── capability_open_subaccount.json
│   ├── discovery_trace.json
│   ├── discovery_run.log
│   ├── replay_success.log
│   ├── replay_success_state.png
│   ├── replay_business_outcome_not_found.log
│   ├── replay_business_outcome_state.png
│   ├── replay_recoverable_interstitial.log
│   └── replay_escalation_handoff.log
└── tests/                            # 25 comprehensive automated tests
```

---

## Design Report

For a detailed analysis of system architecture, artifact schema contracts, zero-LLM determinism, multi-tenant reuse/drift detection, same-session escalation, and safety guardrails, see [REPORT.md](REPORT.md).
