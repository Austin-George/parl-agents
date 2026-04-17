import os
import sys
import json
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from langchain_core.tracers.context import tracing_v2_enabled


# ── THE BRAIN ──
llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    temperature=0,
    max_tokens=4096  # enough for any single file
)

# ── SYSTEM PROMPT ──
# We now tell the model to return ONLY a JSON block
# This is called "structured output" - more reliable than tool calling
# for local models because we control the parsing ourselves
ARCHITECT_SYSTEM_PROMPT = """
You are an expert software architect specializing in MERN stack applications.

Your job is to analyze requirements and return a JSON response in EXACTLY this format:

{
  "thinking": "your reasoning about the architecture",
  "architecture": "the full markdown content for architecture.md"
}

The architecture markdown MUST include these sections:
# Project Overview
(brief description)

# Frontend React Components
(list each component with its purpose)

# Backend API Routes
(method, path, description for each route)

# MongoDB Schemas
(each collection with field names and types)

# Folder Structure
(the complete folder tree)

IMPORTANT: Return ONLY the JSON object. No explanation before or after. No markdown code fences.
"""

def run_architect(requirements: str) -> str:
    """
    Runs the Architect agent with given requirements.
    Saves architecture.md to project/ folder.
    Returns the architecture content.
    """
    print("\n" + "="*50)
    print("ARCHITECT AGENT STARTING")
    print("="*50 + "\n")

    # tracing_v2_enabled gives this trace a meaningful name
    # in LangSmith instead of showing as "ChatOllama"
    with tracing_v2_enabled(project_name="parl-agents"):
        from langchain_core.callbacks import collect_runs
        messages = [
            SystemMessage(content=ARCHITECT_SYSTEM_PROMPT),
            HumanMessage(content=f"Analyze these requirements:\n\n{requirements}")
        ]

        response = llm.invoke(
            messages,
            config={
                "run_name": "Architect Agent",
                "tags": ["architect", "parl", "phase-1"],
                "metadata": {
                    "agent": "architect",
                    "model": "llama3.2",
                    "requirements_length": len(requirements)
                }
            }
        )

    raw = response.content.strip()

    print(" done.\n")

    # ── PARSE THE JSON RESPONSE ──
    # The model should return a JSON object with "thinking" and "architecture"
    # We extract both and save the architecture to disk ourselves
    try:
        # Sometimes models wrap JSON in ```json ... ``` fences despite instructions
        # This strips those out if present
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
        # If JSON parsing fails, treat the whole response as architecture content
        # This is the fallback - the model didn't follow instructions perfectly
        print("Warning: Could not parse JSON response, using raw output")
        architecture_content = raw

    # ── SAVE TO DISK ──
    # We do this ourselves instead of relying on the model to call a tool
    # This is more reliable for local models
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
    requirements = """
    Build a simple Calculator web application using MERN stack:
    - A clean calculator UI in React with buttons 0-9, +, -, *, /, =, and Clear
    - Display shows current input and result
    - Each calculation is saved to MongoDB (expression + result + timestamp)
    - One Express API route: POST /api/calculations to save a calculation
    - One Express API route: GET /api/calculations to fetch history
    - Show calculation history below the calculator
    Tech stack: MongoDB, Express.js, React, Node.js (MERN)
    """

    content = run_architect(requirements)