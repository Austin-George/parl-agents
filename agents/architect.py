import os
import sys
import json
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tracers.context import tracing_v2_enabled

# ── THE BRAIN ──
# Using Groq for the Architect as well for better
# reasoning quality and consistent output format
llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    temperature=0,
    max_tokens=4096
)

# ── SYSTEM PROMPT ──
# Instructs the Architect to return structured JSON
# so we can reliably parse thinking vs architecture content
ARCHITECT_SYSTEM_PROMPT = """
You are an expert software architect specializing in MERN stack applications.

Your job is to analyze software requirements and return a JSON response
in EXACTLY this format:

{
  "thinking": "your reasoning about the architecture decisions",
  "architecture": "the full markdown content for architecture.md"
}

The architecture markdown MUST include these sections:

# Project Overview
(brief description of the application)

# Frontend React Components
(list each component with its purpose)

# Backend API Routes
(method, path, and description for each route)

# MongoDB Schemas
(each collection with field names and types)

# Folder Structure
(the complete folder tree)

IMPORTANT:
- Return ONLY the JSON object
- No explanation before or after
- No markdown code fences around the JSON
- Be specific — the Coder agent will read this to generate code
"""


def run_architect(requirements: str) -> str:
    """
    Runs the Architect agent with the given requirements.
    Accepts any application description — not hardcoded to any app.
    Saves architecture.md to project/ folder.
    Returns the architecture content as a string.
    """
    print("\n" + "="*50)
    print("ARCHITECT AGENT STARTING")
    print("="*50 + "\n")

    messages = [
        SystemMessage(content=ARCHITECT_SYSTEM_PROMPT),
        HumanMessage(content=f"Analyze these requirements and produce the architecture:\n\n{requirements}")
    ]

    print("Thinking", end="", flush=True)

    with tracing_v2_enabled(project_name="parl-agents"):
        response = llm.invoke(
            messages,
            config={
                "run_name": "Architect Agent",
                "tags": ["architect", "parl"],
                "metadata": {
                    "agent": "architect",
                    "model": "llama-3.3-70b-versatile",
                    "requirements_length": len(requirements)
                }
            }
        )

    print(" done.\n")

    raw = response.content.strip()

    # ── PARSE JSON RESPONSE ──
    # Model returns {"thinking": "...", "architecture": "..."}
    # We extract both fields separately
    try:
        # Strip markdown fences if model added them despite instructions
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        parsed = json.loads(raw)
        thinking = parsed.get("thinking", "")
        architecture_content = parsed.get("architecture", "")

        print("Agent Thinking:")
        print("-" * 40)
        print(thinking)
        print("-" * 40 + "\n")

    except json.JSONDecodeError:
        # Fallback — if JSON parsing fails use the raw response
        # This handles cases where the model ignored formatting instructions
        print("Warning: Could not parse JSON response, using raw output")
        architecture_content = raw

    # ── SAVE TO DISK ──
    os.makedirs("project", exist_ok=True)
    filepath = "project/architecture.md"

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(architecture_content)

    print(f"Architecture saved to: {filepath}")
    print("\nPreview (first 500 chars):")
    print("-" * 40)
    print(architecture_content[:500])
    print("-" * 40)

    print("\n" + "="*50)
    print("ARCHITECT AGENT COMPLETE")
    print("="*50)

    return architecture_content


# ── RUN DIRECTLY TO TEST ──
if __name__ == "__main__":
    import sys

    # Accept requirements from command line or interactive input
    if len(sys.argv) > 1:
        # Example: python agents/architect.py "Build a todo app"
        requirements = " ".join(sys.argv[1:])
    else:
        # Interactive mode — type requirements when prompted
        print("Enter your application requirements")
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

    run_architect(requirements)