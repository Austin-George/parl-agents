import os
import sys
import json
from typing import TypedDict, Annotated
from dotenv import load_dotenv
load_dotenv()

# LangGraph imports
from langgraph.graph import StateGraph, END

# Our agents
from agents.architect import run_architect
from agents.coder import run_coder, FILE_PLAN
from agents.tester import run_tester

from langsmith import traceable

# ── GRAPH STATE ──
# TypedDict defines the shape of the state object
# Every agent reads and writes to this shared state
# This is how agents communicate in LangGraph
class PipelineState(TypedDict):
    # Input
    requirements: str

    # Architect output
    architecture: str

    # Coder output
    created_files: list

    # Tester output
    test_report: dict

    # Pipeline control
    iteration: int          # which negotiation round we're on
    max_iterations: int     # stop after this many failed attempts
    status: str             # "architecting","coding","testing","done","failed"
    failure_history: list   # all failure reports across iterations
    emit_event: object  # ← add this



# ── NODE 1: ARCHITECT ──
def architect_node(state: PipelineState) -> PipelineState:
    emit = state.get("emit_event", lambda e, d: None)
    emit("agent_start", {"agent": "Architect", "message": "Analyzing requirements"})

    architecture = run_architect(state["requirements"])

    emit("agent_complete", {
        "agent": "Architect",
        "message": "Architecture specification complete",
        "output": architecture[:200]
    })

    return {**state, "architecture": architecture, "status": "coding"}


# ── NODE 2: CODER ──
def coder_node(state: PipelineState) -> PipelineState:
    emit = state.get("emit_event", lambda e, d: None)
    iteration = state.get("iteration", 0)

    emit("agent_start", {
        "agent": "Coder",
        "message": f"Generating files (iteration {iteration})"
    })

    if iteration == 0:
        created_files = run_coder(state["architecture"])
    else:
        created_files = fix_files_from_report(
            state["test_report"],
            state["architecture"]
        )

    emit("agent_complete", {
        "agent": "Coder",
        "message": f"Generated {len(created_files)} files",
        "files": created_files
    })

    return {
        **state,
        "created_files": created_files,
        "iteration": iteration + 1,
        "status": "testing"
    }


# ── NODE 3: TESTER ──
def tester_node(state: PipelineState) -> PipelineState:
    """
    Tester node now does three things:
    1. Starts both servers automatically
    2. Reads any terminal/startup errors
    3. Runs Playwright tests
    """
    from runner import ServerManager

    emit = state.get("emit_event", lambda e, d: None)
    emit("agent_start", {"agent": "Tester", "message": "Starting browser tests"})

    print(f"\n🧪  TESTER NODE — Iteration {state.get('iteration', 1)}")

    server_manager = ServerManager()

    try:
        # ── START SERVERS ──
        startup_result = server_manager.setup_and_start()

        if not startup_result["success"]:
            # Servers failed to start — treat startup errors
            # as test failures so the Coder can fix them
            print("\n  ✗ Servers failed to start")
            startup_errors = startup_result["errors"]

            report = {
                "overall_status": "FAIL",
                "passed_count": 0,
                "failed_count": 1,
                "summary": "Application failed to start",
                "failures": [
                    {
                        "scenario": "Server Startup",
                        "expected": "Server running on port 5000",
                        "actual": str(startup_errors),
                        "likely_cause": "Runtime error or missing dependency",
                        "fix_needed": f"Fix startup errors: {startup_errors}"
                    }
                ],
                "recommendation": f"Fix these startup errors: {startup_errors}"
            }

        else:
            # ── RUN PLAYWRIGHT TESTS ──
            report = run_tester(state["architecture"])

            # Also check for any runtime errors that appeared
            # in the server log DURING the tests
            runtime_errors = server_manager.read_server_errors()
            if runtime_errors and report.get("overall_status") == "FAIL":
                report["runtime_errors"] = runtime_errors
                print(f"\n  Runtime errors detected in server log:")
                print(f"  {runtime_errors[:200]}")

    finally:
        # Always stop servers when done
        server_manager.stop_all()

    # Accumulate failure history
    failure_history = state.get("failure_history", [])
    if report.get("overall_status") == "FAIL":
        failure_history.append({
            "iteration": state.get("iteration", 1),
            "failures": report.get("failures", [])
        })

    # Determine next status
    if report.get("overall_status") == "PASS":
        status = "done"
    elif state.get("iteration", 1) >= state.get("max_iterations", 3):
        status = "failed"
    else:
        status = "fixing"

    return {
        **state,
        "test_report": report,
        "failure_history": failure_history,
        "status": status
    }
    """
    Runs the Tester agent.
    Reads: created_files
    Writes: test_report, status, failure_history
    """
    print(f"\n🧪  TESTER NODE — Iteration {state.get('iteration', 1)}")

    report = run_tester(state["architecture"])

    # Accumulate failure history across iterations
    # This gives the Coder context about what has been tried before
    failure_history = state.get("failure_history", [])
    if report.get("overall_status") == "FAIL":
        failure_history.append({
            "iteration": state.get("iteration", 1),
            "failures": report.get("failures", [])
        })

    # Determine next status
    if report.get("overall_status") == "PASS":
        status = "done"
    elif state.get("iteration", 1) >= state.get("max_iterations", 3):
        status = "failed"  # give up after max iterations
    else:
        status = "fixing"

    emit("agent_complete", {
        "agent": "Tester",
        "message": f"Tests {report.get('overall_status')}",
        "passed": report.get("passed_count", 0),
        "failed": report.get("failed_count", 0)
    })

    return {
        **state,
        "test_report": report,
        "failure_history": failure_history,
        "status": status
    }


# ── CONDITIONAL EDGE ──
# This function decides which node to go to after the Tester runs.
# It's the "brain" of the negotiation loop.
def should_continue(state: PipelineState) -> str:
    """
    Routing function for the conditional edge after Tester.
    Returns the name of the next node to execute.
    """
    status = state.get("status")
    iteration = state.get("iteration", 1)
    max_iter = state.get("max_iterations", 3)

    if status == "done":
        print(f"\n✅  All tests passed! Pipeline complete.")
        return "end"

    elif status == "failed" or iteration >= max_iter:
        print(f"\n❌  Max iterations ({max_iter}) reached. Stopping.")
        return "end"

    else:
        print(f"\n🔄  Tests failed. Sending back to Coder (iteration {iteration}/{max_iter})")
        return "coder"  # loop back


# ── FIX FILES FROM REPORT ──
# This is the actual negotiation — the Coder reads the Tester's
# failure report and regenerates only the broken files
def fix_files_from_report(test_report: dict, architecture: str) -> list:
    """
    Given a failure report from the Tester, use Groq to fix
    only the specific files that need changing.
    """
    from langchain_groq import ChatGroq
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = ChatGroq(
        model="llama-3.3-70b-versatile",
        temperature=0,
        max_tokens=4096
    )

    failures = test_report.get("failures", [])
    recommendation = test_report.get("recommendation", "")

    if not failures:
        print("  No specific failures to fix")
        return []

    # Ask the LLM which files need to be changed
    messages = [
        SystemMessage(content="""You are a MERN stack developer fixing bugs.
Given test failures, return a JSON array of files to fix:
[
  {
    "path": "server/routes/calculationRoutes.js",
    "fix": "specific description of what to change"
  }
]
Return ONLY the JSON array."""),
        HumanMessage(content=f"""Test failures:
{json.dumps(failures, indent=2)}

Recommendation: {recommendation}

Which files need to be fixed? Return the JSON array.""")
    ]

    response = llm.invoke(messages)
    raw = response.content.strip()

    # Strip fences
    if raw.startswith("```"):
        lines = raw.split("\n")[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()

    try:
        files_to_fix = json.loads(raw)
    except:
        print(f"  Could not parse fix list, skipping")
        return []

    # Regenerate each broken file
    fixed_files = []
    PROJECT_ROOT = "project"

    FIX_PROMPT = """You are fixing a bug in a MERN stack application.
Generate the COMPLETE corrected file content.
Rules:
- Use ES module syntax (import/export)
- 2 space indentation
- No placeholders or TODOs
- Return ONLY the raw file content, no markdown fences
"""

    for file_info in files_to_fix:
        filepath = file_info["path"]
        fix_description = file_info["fix"]

        print(f"  Fixing: {filepath}")
        print(f"  Fix: {fix_description}")

        # Read current content for context
        full_path = os.path.join(PROJECT_ROOT, filepath)
        current_content = ""
        if os.path.exists(full_path):
            with open(full_path, 'r') as f:
                current_content = f.read()

        fix_messages = [
            SystemMessage(content=FIX_PROMPT),
            HumanMessage(content=f"""Fix this file: {filepath}

What needs fixing: {fix_description}

Current file content:
{current_content}

Architecture context:
{architecture[:500]}

Return the complete fixed file.""")
        ]

        fix_response = llm.invoke(fix_messages)
        fixed_content = fix_response.content.strip()

        # Strip fences
        if fixed_content.startswith("```"):
            lines = fixed_content.split("\n")[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            fixed_content = "\n".join(lines).strip()

        # Save fixed file
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(fixed_content)

        fixed_files.append(full_path)
        print(f"  ✓ Fixed and saved")

    return fixed_files


# ── BUILD THE GRAPH ──
def build_pipeline() -> StateGraph:
    """
    Assembles the LangGraph pipeline.
    Nodes = agents
    Edges = connections between agents
    Conditional edges = negotiation routing
    """
    graph = StateGraph(PipelineState)

    # Add nodes
    graph.add_node("architect", architect_node)
    graph.add_node("coder", coder_node)
    graph.add_node("tester", tester_node)

    # Add edges
    # architect always goes to coder
    graph.add_edge("architect", "coder")
    # coder always goes to tester
    graph.add_edge("coder", "tester")

    # Tester has a CONDITIONAL edge
    # It either goes back to coder (on fail) or ends (on pass)
    graph.add_conditional_edges(
        "tester",           # from this node
        should_continue,    # call this function to decide
        {
            "coder": "coder",   # if function returns "coder" → go to coder
            "end": END          # if function returns "end" → finish
        }
    )

    # Set entry point
    graph.set_entry_point("architect")

    return graph.compile()


# ── RUN THE FULL PIPELINE ──
@traceable(
    name="PARL Full Pipeline",
    tags=["pipeline", "parl", "full-run"]
)
def run_pipeline(requirements: str, emit_event=None):
    """
    Runs the complete multi-agent pipeline.
    emit_event is optional — if provided, sends live updates
    to the FastAPI WebSocket layer.
    """

    # Helper that safely calls emit_event if it was provided
    def emit(event_type: str, data: dict):
        if emit_event:
            emit_event(event_type, data)

    print("\n" + "="*60)
    print("  PARL MULTI-AGENT PIPELINE STARTING")
    print("="*60)

    emit("pipeline_start", {"message": "Pipeline starting"})

    pipeline = build_pipeline()

    initial_state: PipelineState = {
        "requirements": requirements,
        "architecture": "",
        "created_files": [],
        "test_report": {},
        "iteration": 0,
        "max_iterations": 3,
        "status": "architecting",
        "failure_history": [],
        "emit_event": emit  # pass emitter into graph state
    }

    final_state = pipeline.invoke(initial_state)

    # Final report
    print("\n" + "="*60)
    print("  PIPELINE COMPLETE")
    print("="*60)
    print(f"\nStatus     : {final_state['status']}")
    print(f"Iterations : {final_state['iteration']}")
    print(f"Files      : {len(final_state['created_files'])} generated")

    test_report = final_state.get('test_report', {})
    print(f"Tests      : {test_report.get('overall_status', 'N/A')}")
    print(f"Summary    : {test_report.get('summary', 'N/A')}")

    os.makedirs("logs", exist_ok=True)
    with open("logs/final_state.json", 'w') as f:
        serializable = {
            k: v for k, v in final_state.items()
            if isinstance(v, (str, int, list, dict, bool))
        }
        json.dump(serializable, f, indent=2)

    return final_state


if __name__ == "__main__":
    requirements = """
    Build a simple Calculator web application using MERN stack:
    - A clean calculator UI in React with buttons 0-9, +, -, *, /, =, and Clear
    - Display shows current input and result
    - Each calculation saved to MongoDB (expression + result + timestamp)
    - POST /api/calculations to save a calculation
    - GET /api/calculations to fetch history
    - Show calculation history below the calculator
    Tech stack: MongoDB, Express.js, React, Node.js (MERN)
    """

    run_pipeline(requirements)