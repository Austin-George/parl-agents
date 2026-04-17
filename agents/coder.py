import os
import sys
import json
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage

# ── THE BRAIN ──
# Llama 3.3 70B via Groq — strong code generation quality
# temperature=0 → deterministic, consistent output
llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    temperature=0,
    max_tokens=4096
)

# ── PROJECT ROOT ──
# All generated files go inside this folder
# Keeps the MERN app completely separate from agent code
PROJECT_ROOT = "project"

# ── FILE PLAN PROMPT ──
# Asks the LLM to decide which files need to be created
# based on whatever architecture the Architect produced
FILE_PLAN_PROMPT = """You are a MERN stack developer.
Given an architecture specification, return a JSON array of files to create.

Return ONLY a JSON array in this exact format:
[
  {
    "path": "server/package.json",
    "description": "detailed description of what this file should contain"
  },
  {
    "path": "client/src/components/TodoList.js",
    "description": "detailed description of what this file should contain"
  }
]

Rules:
- All server files must start with server/
- All client files must start with client/
- Always include server/package.json and client/package.json
- Always include server/app.js as Express entry point
- Always include client/src/index.js and client/src/App.js
- Always include client/public/index.html
- Include ALL components mentioned in the architecture
- Include ALL routes mentioned in the architecture
- Include ALL models mentioned in the architecture
- Descriptions must be detailed enough to generate complete working code
- Return ONLY the JSON array, no explanation
"""

# ── FILE GENERATION PROMPT ──
# Strict rules to prevent the most common model mistakes:
# wrong import paths, placeholder comments, missing code
FILE_GENERATION_PROMPT = """You are an expert MERN stack developer.
Generate COMPLETE, PRODUCTION-READY file content.

STRICT RULES — violating any of these is unacceptable:
1. Write the COMPLETE file — never truncate or summarize
2. ALWAYS use ES module syntax:
   - import express from 'express'          ✓
   - const express = require('express')     ✗ never
3. ALWAYS use ES module exports:
   - export default router                  ✓
   - module.exports = router               ✗ never
4. Import paths must be package names only:
   - import express from 'express'          ✓
   - import express from '../node_modules/express'  ✗ never
5. Use exactly 2 spaces for indentation
6. No placeholder comments:
   - // TODO, // add your code, // replace with  ✗ never
7. For server/app.js ALWAYS include this health check route:
   app.get('/', (req, res) => res.json({ status: 'ok' }))
8. Return ONLY the raw file content
9. No markdown fences, no explanation before or after
"""


def generate_file_plan(architecture: str) -> list:
    """
    Asks the LLM to plan which files need to be created
    based on the architecture spec.
    Returns a list of {path, description} dicts.
    This is the PERCEIVE step — understanding what needs building.
    """
    print("\nGenerating file plan from architecture...")

    messages = [
        SystemMessage(content=FILE_PLAN_PROMPT),
        HumanMessage(content=f"Generate the file plan for this architecture:\n\n{architecture}")
    ]

    response = llm.invoke(
        messages,
        config={
            "run_name": "Coder — File Plan",
            "tags": ["coder", "parl", "planning"],
            "metadata": {
                "agent": "coder",
                "step": "file_planning",
                "model": "llama-3.3-70b-versatile"
            }
        }
    )

    raw = response.content.strip()

    # Strip markdown fences if present
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    # Extract just the JSON array in case model added text around it
    start = raw.find("[")
    end = raw.rfind("]") + 1
    if start != -1 and end != 0:
        raw = raw[start:end]

    try:
        file_plan = json.loads(raw)
        print(f"  → Planned {len(file_plan)} files:")
        for f in file_plan:
            print(f"    - {f['path']}")
        return file_plan
    except json.JSONDecodeError as e:
        print(f"  ✗ Could not parse file plan: {e}")
        return []


def generate_file_content(filepath: str, description: str) -> str:
    """
    Generates complete content for a single file.
    Runs a verification pass if placeholder comments are detected.
    This is the ACT step — producing the actual code.
    """
    messages = [
        SystemMessage(content=FILE_GENERATION_PROMPT),
        HumanMessage(content=f"""Generate the COMPLETE content for this file.

File path: {filepath}
What this file does: {description}
""")
    ]

    response = llm.invoke(
        messages,
        config={
            "run_name": f"Coder — {filepath}",
            "tags": ["coder", "parl", "code-generation"],
            "metadata": {
                "agent": "coder",
                "file": filepath,
                "model": "llama-3.3-70b-versatile"
            }
        }
    )

    content = response.content.strip()

    # ── STRIP MARKDOWN FENCES ──
    # Models occasionally wrap output in ```javascript ... ```
    # despite instructions — strip defensively
    if content.startswith("```"):
        lines = content.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        content = "\n".join(lines).strip()

    # ── VERIFICATION PASS ──
    # If placeholder comments are detected run a fix pass
    # This catches cases where the model ignored instructions
    placeholder_signals = [
        "// add your",
        "// replace with",
        "// your code",
        "// TODO",
        "// ...",
        "/* ... */",
        "rest of the",
        "implement here",
    ]

    found = [p for p in placeholder_signals if p.lower() in content.lower()]

    if found:
        print(f"  ⚠ Placeholder detected ({found[0]}), running fix pass...")

        fix_messages = [
            SystemMessage(content=FILE_GENERATION_PROMPT),
            HumanMessage(content=f"""This file has placeholder comments.
Replace ALL placeholders with real working code.

File: {filepath}
Description: {description}

Current content:
{content}

Return the complete fixed file with no placeholders.
""")
        ]

        fix_response = llm.invoke(fix_messages)
        content = fix_response.content.strip()

        # Strip fences again after fix pass
        if content.startswith("```"):
            lines = content.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            content = "\n".join(lines).strip()

    return content


def save_file(relative_path: str, content: str) -> str:
    """
    Saves generated file to project/relative_path.
    Creates parent directories automatically.
    Returns the full saved path.
    """
    full_path = os.path.join(PROJECT_ROOT, relative_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    with open(full_path, 'w', encoding='utf-8') as f:
        f.write(content)

    return full_path


def run_coder(architecture: str) -> list:
    """
    Runs the Coder agent.
    Reads the architecture spec and generates all MERN files.
    Works for any app — not hardcoded to any specific project.
    Returns list of successfully created file paths.
    """
    print("\n" + "="*50)
    print("CODER AGENT STARTING")
    print("="*50)

    # ── PERCEIVE ──
    # Understand what files need to be built
    file_plan = generate_file_plan(architecture)

    if not file_plan:
        print("✗ Could not generate file plan")
        return []

    print(f"\nModel  : llama-3.3-70b-versatile via Groq")
    print(f"Files  : {len(file_plan)} to generate")
    print(f"Output : {PROJECT_ROOT}/")

    created_files = []
    failed_files = []
    total = len(file_plan)

    # ── REASON + ACT ──
    # Generate each file one at a time
    # Focused generation per file produces better quality
    # than asking for everything at once
    for i, file_info in enumerate(file_plan, 1):
        relative_path = file_info["path"]
        description = file_info["description"]

        print(f"\n[{i}/{total}] {relative_path}")

        try:
            content = generate_file_content(relative_path, description)

            if not content:
                print(f"  ✗ Empty response")
                failed_files.append(relative_path)
                continue

            full_path = save_file(relative_path, content)
            created_files.append(full_path)

            # Show first line as quick sanity check
            first_line = content.split('\n')[0][:70]
            print(f"  ✓ {len(content)} chars — {first_line}")

        except Exception as e:
            print(f"  ✗ Error: {e}")
            failed_files.append(relative_path)
            continue

    # ── LEARN ──
    # Report what was accomplished this iteration
    print("\n" + "="*50)
    print("CODER AGENT COMPLETE")
    print("="*50)
    print(f"\n✓ Created : {len(created_files)}/{total} files")

    if failed_files:
        print(f"✗ Failed  : {len(failed_files)} files")
        for f in failed_files:
            print(f"  - {f}")

    print("\nGenerated project structure:")
    for root, dirs, files in os.walk(PROJECT_ROOT):
        dirs[:] = [d for d in dirs if d != 'node_modules']
        level = root.replace(PROJECT_ROOT, '').count(os.sep)
        indent = "  " * level
        print(f"{indent}{os.path.basename(root)}/")
        subindent = "  " * (level + 1)
        for filename in files:
            print(f"{subindent}{filename}")

    return created_files


# ── RUN DIRECTLY TO TEST ──
if __name__ == "__main__":
    arch_path = os.path.join(PROJECT_ROOT, "architecture.md")

    if not os.path.exists(arch_path):
        print(f"✗ {arch_path} not found.")
        print("Run the Architect first: python agents/architect.py")
        sys.exit(1)

    with open(arch_path, 'r', encoding='utf-8') as f:
        architecture = f.read()

    print(f"✓ Read architecture.md ({len(architecture)} chars)")
    run_coder(architecture)