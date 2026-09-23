"""
Unified Command Line Interface for Computer-Use Automation System.
Provides commands for:
- server: Start the mock legacy banking server (ApexCore 2008)
- discover: Run Gemini LLM discovery against a target URL
- compile: Compile a discovery trace into a typed capability artifact
- replay: Replay a capability artifact deterministically without an LLM
- demo: Run the complete end-to-end vertical slice demonstration
"""

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path

from core.agent.discovery import DiscoveryAgent
from core.compiler.artifact_compiler import ArtifactCompiler
from core.artifact.schema import CapabilityArtifact
from core.artifact.storage import ArtifactStorage
from core.escalation.manager import EscalationManager
from core.llm.gemini_client import get_llm_provider
from core.replay.engine import DeterministicReplayEngine, ResultStatus
from core.surface.selenium_driver import SeleniumSurfaceDriver
from apps.legacy_bank.server import start_server, PORT


def cmd_server(args):
    port = args.port or PORT
    server = start_server(port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[ApexCore 2008] Server stopped.")
        server.server_close()


def cmd_discover(args):
    url = args.url or f"http://127.0.0.1:{PORT}/servicing"
    goal = args.goal or "Look up member M-10928 and read their current savings balance"
    output_path = args.output or "evidence/discovery_trace.json"

    # Auto-start local mock server if connecting to localhost and not running
    if "127.0.0.1" in url or "localhost" in url:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        is_running = (sock.connect_ex(("127.0.0.1", PORT)) == 0)
        sock.close()
        if not is_running:
            server = start_server(PORT)
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            time.sleep(0.5)

    surface = SeleniumSurfaceDriver(headless=args.headless)
    llm = get_llm_provider(force_simulated=args.simulated)
    agent = DiscoveryAgent(surface=surface, llm_provider=llm)

    try:
        trace = agent.discover(goal=goal, entry_url=url)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(trace.model_dump_json(indent=2))
        print(f"[CLI] Discovery trace saved to: {output_path}")

        # Also write discovery_run.log in same directory
        log_path = Path(output_path).parent / "discovery_run.log"
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"Discovery Run Log: {goal}\nModel: {trace.llm_model}\nStatus: {trace.status}\n\n")
            for s in trace.steps:
                f.write(f"Step {s.step_number}: {s.action} on '{s.target_description}' -> {s.status} ({s.duration_ms:.1f}ms)\n")
                if s.reasoning:
                    f.write(f"   Reasoning: {s.reasoning}\n")
        print(f"[CLI] Discovery log saved to: {log_path}")
    finally:
        surface.close()


def cmd_compile(args):
    trace_path = args.trace or "evidence/discovery_trace.json"
    output_path = args.output or "artifacts/capability_member_lookup.json"

    with open(trace_path, "r", encoding="utf-8") as f:
        trace_data = json.load(f)
    from core.agent.discovery import DiscoveryTrace
    trace = DiscoveryTrace.model_validate(trace_data)

    artifact = ArtifactCompiler.compile(
        trace=trace,
        capability_id=args.id or "apex_member_lookup",
        capability_name=args.name or "ApexCore Member Balance Lookup"
    )

    saved_file = ArtifactStorage.save(artifact, output_path)
    print(f"[CLI] Compiled capability artifact saved to: {saved_file}")


def cmd_replay(args):
    artifact_path = args.artifact or "artifacts/capability_member_lookup.json"
    if getattr(args, "simulate_stuck_state", False) and (not args.artifact or args.artifact == "artifacts/capability_member_lookup.json"):
        artifact_path = "artifacts/capability_member_lookup_stuck.json"

    params = json.loads(args.params) if args.params else {}

    # Reset security challenge state if testing stuck state
    if getattr(args, "simulate_stuck_state", False) or "stuck" in artifact_path:
        import apps.legacy_bank.server as srv_mod
        srv_mod.SECURITY_CHALLENGE_ACKNOWLEDGED = False

    artifact = ArtifactStorage.load(artifact_path)
    from core.artifact.schema import ActionType
    if getattr(args, "simulate_stuck_state", False) and artifact.steps and artifact.steps[0].action_type == ActionType.NAVIGATE:
        if "stuck_modal=1" not in (artifact.steps[0].value_template or ""):
            artifact.steps[0].value_template = f"http://127.0.0.1:{PORT}/servicing?stuck_modal=1"

    # Auto-start local mock server if connecting to localhost and not running
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    is_running = (sock.connect_ex(("127.0.0.1", PORT)) == 0)
    sock.close()
    if not is_running:
        server = start_server(PORT)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.5)

    surface = SeleniumSurfaceDriver(headless=args.headless)
    engine = DeterministicReplayEngine(
        surface=surface,
        allow_risky_actions=args.allow_risky,
        auto_intervene=args.auto_intervene
    )

    try:
        result = engine.replay(artifact, input_params=params)
        print("\n--- REPLAY EXECUTION RESULT ---")
        print(f"Status:             {result.status.value}")
        print(f"Capability ID:      {result.capability_id} (v{result.capability_version})")
        print(f"Outputs:            {json.dumps(result.outputs, indent=2)}")
        if result.business_outcome:
            print(f"Business Outcome:   {result.business_outcome['outcome_code']} - {result.business_outcome['description']}")
        if result.recoveries_handled:
            print(f"Recoveries Handled: {json.dumps(result.recoveries_handled, indent=2)}")
        if result.escalation_handle:
            print(f"Escalation Details: {json.dumps(result.escalation_handle, indent=2)}")
        if result.error:
            print(f"Error Details:      {json.dumps(result.error, indent=2)}")
        print(f"Total Duration:     {result.total_duration_ms:.1f}ms")
        print("-------------------------------")
    finally:
        surface.close()


def cmd_demo(args):
    """Run the complete vertical slice demonstration."""
    print("=================================================================")
    print("🚀 RUNNING COMPUTER-USE AUTOMATION SYSTEM END-TO-END DEMO 🚀")
    print("=================================================================")

    evidence_dir = Path("evidence")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir = Path("artifacts")
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    # 1. Start local mock legacy banking server in a background daemon thread
    server = start_server(PORT)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    time.sleep(0.5)

    try:
        # Step A: Real LLM Discovery Run
        print("\n--- STAGE 1: GOAL-DRIVEN DISCOVERY RUN ---")
        disc_surface = SeleniumSurfaceDriver(headless=args.headless)
        llm = get_llm_provider(force_simulated=args.simulated)
        agent = DiscoveryAgent(surface=disc_surface, llm_provider=llm)

        goal = "Look up member M-10928 and read their current savings balance"
        url = f"http://127.0.0.1:{PORT}/servicing"
        trace = agent.discover(goal=goal, entry_url=url)
        disc_surface.close()

        # Save discovery trace and log
        trace_path = evidence_dir / "discovery_trace.json"
        with open(trace_path, "w", encoding="utf-8") as f:
            f.write(trace.model_dump_json(indent=2))

        disc_log_path = evidence_dir / "discovery_run.log"
        with open(disc_log_path, "w", encoding="utf-8") as f:
            f.write(f"Discovery Run Log: {goal}\nModel: {trace.llm_model}\nStatus: {trace.status}\n\n")
            for s in trace.steps:
                f.write(f"Step {s.step_number}: {s.action} on '{s.target_description}' -> {s.status} ({s.duration_ms:.1f}ms)\n")
                if s.reasoning:
                    f.write(f"   Reasoning: {s.reasoning}\n")

        print(f"Saved: {trace_path} and {disc_log_path}")

        # Step B: Artifact Compiler Stage
        print("\n--- STAGE 2: ARTIFACT COMPILER ---")
        artifact = ArtifactCompiler.compile(
            trace=trace,
            capability_id="apex_member_lookup",
            capability_name="ApexCore Member Balance Lookup",
            version="1.0.0"
        )
        artifact_path = artifacts_dir / "capability_member_lookup.json"
        ArtifactStorage.save(artifact, artifact_path)
        # Copy to evidence
        ArtifactStorage.save(artifact, evidence_dir / "capability_member_lookup.json")
        print(f"Compiled Capability Artifact saved to: {artifact_path}")

        # Step C: Deterministic Replay - SUCCESS (Member M-10928)
        print("\n--- STAGE 3: DETERMINISTIC REPLAY (HAPPY PATH - SUCCESS) ---")
        replay_surface = SeleniumSurfaceDriver(headless=args.headless)
        engine = DeterministicReplayEngine(surface=replay_surface)
        res_success = engine.replay(artifact, input_params={"member_id": "M-10928"})

        success_log_path = evidence_dir / "replay_success.log"
        with open(success_log_path, "w", encoding="utf-8") as f:
            f.write(f"Replay Status: {res_success.status.value}\n")
            f.write(f"Capability: {res_success.capability_id} v{res_success.capability_version}\n")
            f.write(f"Outputs: {json.dumps(res_success.outputs, indent=2)}\n")
            f.write(f"Duration: {res_success.total_duration_ms:.1f}ms\n\nStep Trace:\n")
            for st in res_success.step_trace:
                f.write(f"- {st.step_id} ({st.action_type}): {st.status} via {st.matched_strategy} (conf: {st.confidence})\n")

        # Capture success screenshot
        succ_shot = evidence_dir / "replay_success_state.png"
        with open(succ_shot, "wb") as f:
            f.write(replay_surface.capture_screenshot())

        print(f"Happy path replay completed: {res_success.status.value}. Log saved to: {success_log_path}")

        # Step D: Deterministic Replay - BUSINESS_OUTCOME (Member M-99999 Not Found)
        print("\n--- STAGE 4: DETERMINISTIC REPLAY (BUSINESS OUTCOME - MEMBER NOT FOUND) ---")
        res_not_found = engine.replay(artifact, input_params={"member_id": "M-99999"})

        bo_log_path = evidence_dir / "replay_business_outcome_not_found.log"
        with open(bo_log_path, "w", encoding="utf-8") as f:
            f.write(f"Replay Status: {res_not_found.status.value}\n")
            f.write(f"Business Outcome: {json.dumps(res_not_found.business_outcome, indent=2)}\n")
            f.write(f"Duration: {res_not_found.total_duration_ms:.1f}ms\n")

        bo_shot = evidence_dir / "replay_business_outcome_state.png"
        with open(bo_shot, "wb") as f:
            f.write(replay_surface.capture_screenshot())

        print(f"Not-found replay completed: {res_not_found.status.value}. Log saved to: {bo_log_path}")

        # Step E: Deterministic Replay - RECOVERABLE INTERSTITIAL (Maintenance Notice Auto-Dismissal)
        print("\n--- STAGE 5: RECOVERABLE INTERSTITIAL AUTO-HANDLING ---")
        import apps.legacy_bank.server as srv_mod
        srv_mod.INTERSTITIAL_ACKNOWLEDGED = False
        rec_artifact = artifact.model_copy(deep=True)
        rec_artifact.steps[0].value_template = f"http://127.0.0.1:{PORT}/servicing?maintenance=1"
        res_rec = engine.replay(rec_artifact, input_params={"member_id": "M-10928"})
        rec_log_path = evidence_dir / "replay_recoverable_interstitial.log"
        with open(rec_log_path, "w", encoding="utf-8") as f:
            f.write(f"Replay Status: {res_rec.status.value}\n")
            f.write(f"Recoveries Handled: {json.dumps(res_rec.recoveries_handled, indent=2)}\n")
            f.write(f"Outputs: {json.dumps(res_rec.outputs, indent=2)}\n")

        print(f"Recoverable interstitial replay completed: {res_rec.status.value}. Log saved to: {rec_log_path}")

        # Step F: Risky Action Escalation & Same-Session Live Handoff ("Open Sub-Account")
        print("\n--- STAGE 6: RISKY ACTION ESCALATION & SAME-SESSION TAKEOVER ('OPEN SUB-ACCOUNT') ---")
        # Create sub-account capability artifact
        subacct_agent = DiscoveryAgent(surface=replay_surface, llm_provider=llm)
        subacct_trace = subacct_agent.discover(
            goal="Open a new sub-account for member M-10928 and reach the confirmation screen",
            entry_url=f"http://127.0.0.1:{PORT}/member_detail?id=M-10928"
        )
        subacct_artifact = ArtifactCompiler.compile(
            trace=subacct_trace,
            capability_id="apex_open_subaccount",
            capability_name="ApexCore Open Sub-Account",
            version="1.0.0"
        )
        ArtifactStorage.save(subacct_artifact, artifacts_dir / "capability_open_subaccount.json")
        ArtifactStorage.save(subacct_artifact, evidence_dir / "capability_open_subaccount.json")

        # Replay without pre-authorized risky actions -> triggers escalation manager with auto_intervene=True
        esc_engine = DeterministicReplayEngine(
            surface=replay_surface,
            allow_risky_actions=False,
            auto_intervene=True  # Demonstrates same-session human takeover & resume
        )
        res_escalated = esc_engine.replay(subacct_artifact, input_params={"member_id": "M-10928"})

        esc_log_path = evidence_dir / "replay_escalation_handoff.log"
        with open(esc_log_path, "w", encoding="utf-8") as f:
            f.write(f"Replay Status: {res_escalated.status.value}\n")
            f.write(f"Capability: {res_escalated.capability_id}\n")
            f.write(f"Escalation Details: {json.dumps(res_escalated.escalation_handle, indent=2)}\n")
            f.write(f"Step Trace:\n")
            for st in res_escalated.step_trace:
                f.write(f"- {st.step_id}: {st.status} ({st.details})\n")

        print(f"Escalation & takeover completed: {res_escalated.status.value}. Log saved to: {esc_log_path}")
        replay_surface.close()

        # Step G: Technical Stuck-State Escalation & Same-Session Recovery (Security Challenge)
        print("\n--- STAGE 7: STUCK-STATE ESCALATION & SAME-SESSION LIVE RESUMPTION ---")
        srv_mod.SECURITY_CHALLENGE_ACKNOWLEDGED = False
        stuck_surface = SeleniumSurfaceDriver(headless=args.headless)
        stuck_engine = DeterministicReplayEngine(
            surface=stuck_surface,
            auto_intervene=True  # Demonstrates same-session takeover and resumption
        )
        stuck_artifact = ArtifactStorage.load("artifacts/capability_member_lookup_stuck.json")
        res_stuck = stuck_engine.replay(stuck_artifact, input_params={"member_id": "M-10928"})

        stuck_log_path = evidence_dir / "replay_stuck_state_escalation.log"
        with open(stuck_log_path, "w", encoding="utf-8") as f:
            f.write(f"Replay Status: {res_stuck.status.value}\n")
            f.write(f"Capability: {res_stuck.capability_id}\n")
            f.write(f"Outputs: {json.dumps(res_stuck.outputs, indent=2)}\n")
            f.write(f"Step Trace:\n")
            for st in res_stuck.step_trace:
                f.write(f"- {st.step_id} ({st.action_type}): {st.status} ({st.details})\n")

        # Capture final checkpoint screenshot
        stuck_final_shot = evidence_dir / "replay_stuck_recovered_final_state.png"
        try:
            with open(stuck_final_shot, "wb") as f:
                f.write(stuck_surface.capture_screenshot())
        except Exception:
            pass

        print(f"Stuck-state escalation & recovery completed: {res_stuck.status.value}. Log saved to: {stuck_log_path}")
        stuck_surface.close()

        print("\n=================================================================")
        print("✅ FULL DEMO SUCCEEDED! ALL EVIDENCE GENERATED IN /evidence/ ✅")
        print("=================================================================\n")

    finally:
        server.shutdown()


def main():
    parser = argparse.ArgumentParser(description="Computer-Use Automation System CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # server
    p_server = subparsers.add_parser("server", help="Start mock legacy bank application")
    p_server.add_argument("--port", type=int, default=PORT)
    p_server.set_defaults(func=cmd_server)

    # discover
    p_disc = subparsers.add_parser("discover", help="Run Gemini LLM discovery")
    p_disc.add_argument("--goal", type=str)
    p_disc.add_argument("--url", type=str)
    p_disc.add_argument("--output", type=str, default="evidence/discovery_trace.json")
    p_disc.add_argument("--simulated", action="store_true", help="Force offline simulated LLM provider")
    p_disc.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    p_disc.set_defaults(func=cmd_discover)

    # compile
    p_comp = subparsers.add_parser("compile", help="Compile discovery trace into capability artifact")
    p_comp.add_argument("--trace", type=str, default="evidence/discovery_trace.json")
    p_comp.add_argument("--output", type=str, default="artifacts/capability_member_lookup.json")
    p_comp.add_argument("--id", type=str)
    p_comp.add_argument("--name", type=str)
    p_comp.set_defaults(func=cmd_compile)

    # replay
    p_rep = subparsers.add_parser("replay", help="Deterministic replay without LLM")
    p_rep.add_argument("--artifact", type=str, default="artifacts/capability_member_lookup.json")
    p_rep.add_argument("--params", type=str, help="JSON input parameters, e.g. '{\"member_id\":\"M-10928\"}'")
    p_rep.add_argument("--allow-risky", action="store_true", help="Allow risky irreversible actions")
    p_rep.add_argument("--auto-intervene", action="store_true", help="Auto-intervene during escalation demo")
    p_rep.add_argument("--simulate-stuck-state", action="store_true", help="Simulate a blocking modal overlay requiring human takeover")
    p_rep.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    p_rep.set_defaults(func=cmd_replay)

    # demo
    p_demo = subparsers.add_parser("demo", help="Run full end-to-end vertical slice demo")
    p_demo.add_argument("--simulated", action="store_true", help="Force offline simulated provider")
    p_demo.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    p_demo.set_defaults(func=cmd_demo)

    parsed = parser.parse_args()
    parsed.func(parsed)


if __name__ == "__main__":
    main()
