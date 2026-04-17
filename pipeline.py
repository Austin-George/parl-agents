import os
import sys
import json
from typing import TypedDict
from dotenv import load_dotenv
load_dotenv()

from langgraph.graph import StateGraph, END
from langsmith import traceable

from agents.architect import run_architect
from agents.coder import run_coder
from agents.tester import run_tester

# ── GRAPH STATE ──
# Shared state object passed between every agent node.
# Each agent reads from it and writes its output back to it.
# This is how agents communicate in LangGraph.
class PipelineState(TypedDict):
    requirements:    str       # user's original prompt
    architecture:    str       # Architect's output
    created_files:   list      # Coder's output — list of file paths
    test_report:     dict      # Tester's output — pass/fail analysis
    iteration:       int       # which negotiation round we're on
    max_iterations:  int       # give up after this many failed rounds
    status:          str       # architecting → coding → testing → done/failed
    failure_history: list      # all failure reports across iterations
    emit_event:      object    # WebSocket broadcaster from FastAPI layer


# ──────────────────────────────────────────
# AGENT NODES
# ──────────────────────────────────────────

def architect_node(state: PipelineState) -> PipelineState:
    """
    Node 1: Architect Agent
    Reads:  requirements
    Writes: architecture
    """
    emit = state.get("emit_event", lambda e, d: None)

    emit("agent_start", {
        "agent": "Architect",
        "message": "Analyzing requirements"
    })

    architecture = run_architect(state["requirements"])

    emit("agent_complete", {
        "agent": "Architect",
        "message": "Architecture specification complete",
        "output": architecture[:200]
    })

    return {
        **state,
        "architecture": architecture,
        "status": "coding"
    }


def coder_node(state: PipelineState) -> PipelineState:
    """
    Node 2: Coder Agent
    Reads:  architecture, test_report (on fix iterations)
    Writes: created_files, iteration

    On iteration 0: generates all files fresh from architecture.
    On subsequent iterations: fixes only the files that failed.
    This is the negotiation — Coder responds to Tester's report.
    """
    emit = state.get("emit_event", lambda e, d: None)
    iteration = state.get("iteration", 0)

    emit("agent_start", {
        "agent": "Coder",
        "message": f"Generating files (iteration {iteration})"
    })

    if iteration == 0:
        # First run — generate everything from scratch
        created_files = run_coder(state["architecture"])
    else:
        # Fix run — only repair files identified in the failure report
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


def tester_node(state: PipelineState) -> PipelineState:
    """
    Node 3: Tester Agent
    Reads:  architecture, created_files
    Writes: test_report, failure_history, status

    Automatically starts both servers, runs Playwright tests,
    reads server logs for runtime errors, then stops servers.
    """
    from runner import ServerManager

    emit = state.get("emit_event", lambda e, d: None)
    iteration = state.get("iteration", 1)

    emit("agent_start", {
        "agent": "Tester",
        "message": f"Starting browser tests (iteration {iteration})"
    })

    print(f"\n🧪  TESTER NODE — Iteration {iteration}")

    server_manager = ServerManager()

    try:
        # ── START SERVERS AUTOMATICALLY ──
        startup_result = server_manager.setup_and_start()

        if not startup_result["success"]:
            startup_errors = startup_result["errors"]

            # Read the full server log for detailed error
            full_log = server_manager.read_server_errors()

            print(f"\n  ✗ Servers failed to start")
            print(f"  Error: {full_log[:300]}")

            report = {
                "overall_status": "FAIL",
                "passed_count": 0,
                "failed_count": 1,
                "summary": "Application failed to start due to a runtime error",
                "failures": [{
                    "scenario": "Server Startup",
                    "expected": "Server starts successfully on port 5000",
                    "actual": full_log or str(startup_errors),
                    "likely_cause": "Syntax error or missing export in a generated file",
                    "fix_needed": (
                        f"Fix the following server startup error: {full_log or startup_errors}. "
                        f"Check all model files have 'export default' at the bottom. "
                        f"Check all route files use correct import paths."
                    )
                }],
                "recommendation": (
                    f"Fix server startup error: {full_log or startup_errors}"
                )
            }

        else:
            # ── RUN PLAYWRIGHT TESTS ──
            report = run_tester(state["architecture"])

            # Check for runtime errors that appeared in server
            # log DURING the Playwright session
            runtime_errors = server_manager.read_server_errors()
            if runtime_errors and report.get("overall_status") == "FAIL":
                report["runtime_errors"] = runtime_errors
                print(f"\n  Runtime errors in server log:")
                print(f"  {runtime_errors[:200]}")

    finally:
        # Always stop servers — even if tests crash
        server_manager.stop_all()

    # ── ACCUMULATE FAILURE HISTORY ──
    # Gives the Coder context about what's been tried before
    failure_history = state.get("failure_history", [])
    if report.get("overall_status") == "FAIL":
        failure_history.append({
            "iteration": iteration,
            "failures": report.get("failures", [])
        })

    # ── DETERMINE NEXT STATUS ──
    if report.get("overall_status") == "PASS":
        status = "done"
    elif iteration >= state.get("max_iterations", 3):
        status = "failed"
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


# ──────────────────────────────────────────
# NEGOTIATION ROUTING
# ──────────────────────────────────────────

def should_continue(state: PipelineState) -> str:
    """
    Conditional edge function — called after the Tester node.
    Decides whether to loop back to Coder or end the pipeline.

    Returns "coder" to trigger another fix iteration.
    Returns "end" to finish the pipeline.
    """
    status = state.get("status")
    iteration = state.get("iteration", 1)
    max_iter = state.get("max_iterations", 3)

    if status == "done":
        print(f"\n✅  All tests passed — pipeline complete.")
        return "end"

    elif status == "failed" or iteration >= max_iter:
        print(f"\n❌  Max iterations ({max_iter}) reached — stopping.")
        return "end"

    else:
        print(f"\n🔄  Tests failed — sending back to Coder "
              f"(iteration {iteration}/{max_iter})")
        return "coder"


# ──────────────────────────────────────────
# FILE REPAIR (NEGOTIATION)
# ──────────────────────────────────────────
def fix_files_from_report(test_report: dict, architecture: str) -> list:
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

    # ── EXTRACT FILE PATH FROM NODE.JS ERROR ──
    # Node.js errors often mention the exact file:
    # "file:///path/to/project/server/models/Calculation.js"
    # We extract this to tell the LLM exactly which file to fix
    import re
    error_text = ' '.join([
        f.get('actual', '') + ' ' + f.get('fix_needed', '')
        for f in failures
    ])

    # Find file paths mentioned in error messages
    file_mentions = re.findall(
        r'project[/\\](server|client)[/\\][\w/\\.-]+\.js',
        error_text
    )
    file_mentions = list(set([
        f.replace('\\', '/') for f in file_mentions
    ]))

    if file_mentions:
        print(f"  Files mentioned in error: {file_mentions}")

    # ── ASK LLM WHICH FILES TO FIX ──
    messages = [
        SystemMessage(content="""You are a MERN stack developer fixing bugs.
Given test failures and error messages, return a JSON array of files to fix.

Return ONLY a JSON array:
[
  {
    "path": "server/models/Calculation.js",
    "fix": "specific description of what to change"
  }
]

Rules:
- If the error mentions a specific file, always include it
- If the error says 'does not provide an export named default',
  the fix is to add 'export default ModelName' at the bottom
- If the error says 'cannot find module', check the import path
- Return ONLY the JSON array
"""),
        HumanMessage(content=f"""Failures:
{json.dumps(failures, indent=2)}

Files mentioned in errors:
{file_mentions}

Recommendation: {recommendation}

Which files need fixing?""")
    ]

    response = llm.invoke(
        messages,
        config={
            "run_name": "Coder — Identify Files to Fix",
            "tags": ["coder", "parl", "negotiation"],
        }
    )

    raw = response.content.strip()

    if raw.startswith("```"):
        lines = raw.split("\n")[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()

    # Extract JSON array
    start = raw.find("[")
    end = raw.rfind("]") + 1
    if start != -1 and end != 0:
        raw = raw[start:end]

    try:
        files_to_fix = json.loads(raw)
    except json.JSONDecodeError:
        print("  ✗ Could not parse fix list")
        # Fallback — if we found file mentions in the error,
        # fix those directly even if LLM parsing failed
        if file_mentions:
            files_to_fix = [{
                "path": f,
                "fix": f"Fix the error mentioned in: {error_text[:200]}"
            } for f in file_mentions]
        else:
            return []

    # ── REGENERATE EACH BROKEN FILE ──
    PROJECT_ROOT = "project"
    fixed_files = []

    FIX_PROMPT = """You are fixing a bug in a MERN stack application.
Generate the COMPLETE corrected file.
Rules:
- Use ES module syntax (import/export)
- ALWAYS include 'export default' for models and routers
- 2 space indentation
- No placeholders or TODOs
- Return ONLY the raw file content, no markdown fences
"""

    for file_info in files_to_fix:
        filepath = file_info["path"]
        fix_description = file_info["fix"]

        print(f"\n  Fixing: {filepath}")
        print(f"  Fix   : {fix_description}")

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

        fix_response = llm.invoke(
            fix_messages,
            config={
                "run_name": f"Coder — Fix {filepath}",
                "tags": ["coder", "parl", "negotiation", "fix"],
                "metadata": {"file": filepath}
            }
        )

        fixed_content = fix_response.content.strip()

        if fixed_content.startswith("```"):
            lines = fixed_content.split("\n")[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            fixed_content = "\n".join(lines).strip()

        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(fixed_content)

        fixed_files.append(full_path)
        print(f"  ✓ Fixed and saved")

    return fixed_files


# ──────────────────────────────────────────
# GRAPH ASSEMBLY
# ──────────────────────────────────────────

def build_pipeline() -> StateGraph:
    """
    Assembles the LangGraph pipeline.

    Graph structure:
    architect → coder → tester → PASS? → END
                  ↑               |
                  └──── FAIL ─────┘
    """
    graph = StateGraph(PipelineState)

    # Register nodes
    graph.add_node("architect", architect_node)
    graph.add_node("coder", coder_node)
    graph.add_node("tester", tester_node)

    # Fixed edges
    graph.add_edge("architect", "coder")
    graph.add_edge("coder", "tester")

    # Conditional edge after tester
    # should_continue() decides: "coder" or "end"
    graph.add_conditional_edges(
        "tester",
        should_continue,
        {
            "coder": "coder",
            "end": END
        }
    )

    graph.set_entry_point("architect")
    return graph.compile()


# ──────────────────────────────────────────
# MAIN ENTRY POINT
# ──────────────────────────────────────────

@traceable(
    name="PARL Full Pipeline",
    tags=["pipeline", "parl", "full-run"]
)
def run_pipeline(requirements: str, emit_event=None) -> dict:
    """
    Runs the complete multi-agent PARL pipeline.
    Accepts any application requirements — not hardcoded to any app.

    emit_event is optional — when provided by FastAPI's server.py,
    it streams live progress to the React dashboard via WebSocket.
    """
    def emit(event_type: str, data: dict):
        """Safely calls emit_event if provided."""
        if emit_event:
            emit_event(event_type, data)

    print("\n" + "="*60)
    print("  PARL MULTI-AGENT PIPELINE STARTING")
    print("="*60)

    emit("pipeline_start", {"message": "Pipeline starting"})

    pipeline = build_pipeline()

    # Initial state — everything starts empty
    # agents will fill in their respective fields
    initial_state: PipelineState = {
        "requirements":    requirements,
        "architecture":    "",
        "created_files":   [],
        "test_report":     {},
        "iteration":       0,
        "max_iterations":  3,
        "status":          "architecting",
        "failure_history": [],
        "emit_event":      emit
    }

    final_state = pipeline.invoke(initial_state)

    # ── FINAL REPORT ──
    test_report = final_state.get("test_report", {})

    print("\n" + "="*60)
    print("  PIPELINE COMPLETE")
    print("="*60)
    print(f"\nStatus     : {final_state['status']}")
    print(f"Iterations : {final_state['iteration']}")
    print(f"Files      : {len(final_state['created_files'])} generated")
    print(f"Tests      : {test_report.get('overall_status', 'N/A')}")
    print(f"Summary    : {test_report.get('summary', 'N/A')}")

    # Save final state for debugging
    os.makedirs("logs", exist_ok=True)
    with open("logs/final_state.json", 'w') as f:
        # Filter out non-serializable fields (emit_event callable)
        serializable = {
            k: v for k, v in final_state.items()
            if isinstance(v, (str, int, list, dict, bool))
        }
        json.dump(serializable, f, indent=2)

    print(f"\nFull state saved to: logs/final_state.json")
    return final_state


if __name__ == "__main__":
    # Accept requirements from command line or interactive input
    if len(sys.argv) > 1:
        # Example: python pipeline.py "Build a todo app"
        requirements = " ".join(sys.argv[1:])
    else:
        # Interactive mode
        print("Enter your app requirements")
        print("(press Enter twice when done):\n")
        lines = []
        while True:
            line = input()
            if line == "":
                if lines:
                    break
            else:
                lines.append(line)
        requirements = "\n".join(lines)

    run_pipeline(requirements)