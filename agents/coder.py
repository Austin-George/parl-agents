import os
import sys
import json
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from langchain_groq import ChatGroq

# ── THE BRAIN ──
# Llama 3.1 70B via Groq — dramatically better code quality
# than any 7B local model. Free tier: 30 req/min, 6000/day
# temperature=0 → deterministic, consistent output
llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    temperature=0,
    max_tokens=4096  # enough for any single file
)

# ── PROJECT ROOT ──
PROJECT_ROOT = "project"

# ── FILE PLAN ──
# Hardcoded for a simple MERN calculator
# No auth, no JWT — just the core app
# ── FILE PLAN ──
FILE_PLAN = [
    {
        "path": "server/package.json",
        "description": """package.json for Express server.
MUST include "type": "module" to enable ES imports.
name: calculator-server
scripts.start: node app.js
dependencies: express, mongoose, cors, dotenv
Example:
{
  "name": "calculator-server",
  "version": "1.0.0",
  "type": "module",
  "scripts": { "start": "node app.js" },
  "dependencies": {
    "express": "^4.18.2",
    "mongoose": "^7.6.0",
    "cors": "^2.8.5",
    "dotenv": "^16.0.0"
  }
}"""
    },
    {
        "path": "server/.env",
        "description": """Environment file with exactly these two lines:
PORT=5000
MONGODB_URI=mongodb://localhost:27017/calculator"""
    },
    {
        "path": "server/app.js",
        "description": """Express app entry point using ES module imports.
MUST start exactly like this:
import express from 'express';
import cors from 'cors';
import mongoose from 'mongoose';
import dotenv from 'dotenv';
import calculationRoutes from './routes/calculationRoutes.js';

dotenv.config();
const app = express();
const PORT = process.env.PORT || 5000;
const MONGODB_URI = process.env.MONGODB_URI || 'mongodb://localhost:27017/calculator';

app.use(cors());
app.use(express.json());
app.use('/api/calculations', calculationRoutes);

mongoose.connect(MONGODB_URI)
  .then(() => {
    console.log('MongoDB connected');
    app.listen(PORT, () => console.log('Server running on port ' + PORT));
  })
  .catch(err => console.error('MongoDB error:', err));"""
    },
    {
        "path": "server/models/Calculation.js",
        "description": """Mongoose model using ES imports.
MUST start with: import mongoose from 'mongoose';
Schema: expression (String required), result (String required), createdAt (Date default Date.now)
MUST end with: export default mongoose.model('Calculation', CalculationSchema);"""
    },
    {
        "path": "server/routes/calculationRoutes.js",
        "description": """Express router using ES imports.
MUST start with:
import { Router } from 'express';
import Calculation from '../models/Calculation.js';
const router = Router();

POST / — create new Calculation({expression, result}), save, return json
GET / — Calculation.find().sort({_id:-1}).limit(20), return json

MUST end with: export default router;"""
    },
    {
        "path": "client/package.json",
        "description": """package.json for React client.
name: calculator-client
scripts.start: react-scripts start
dependencies: react, react-dom, react-scripts, axios
proxy: http://localhost:5000
Example:
{
  "name": "calculator-client",
  "version": "0.1.0",
  "private": true,
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "react-scripts": "5.0.1",
    "axios": "^1.6.0"
  },
  "scripts": { "start": "react-scripts start", "build": "react-scripts build" },
  "proxy": "http://localhost:5000",
  "browserslist": { "production": [">0.2%"], "development": ["last 1 chrome version"] }
}"""
    },
    {
        "path": "client/public/index.html",
        "description": """Minimal HTML shell for React.
Must have <div id="root"></div> in body.
Title: MERN Calculator"""
    },
    {
        "path": "client/src/index.js",
        "description": """React entry point.
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './App.css';
const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<React.StrictMode><App /></React.StrictMode>);"""
    },
    {
        "path": "client/src/App.js",
        "description": """Main App component.
import React, { useState } from 'react';
import Calculator from './components/Calculator';
import History from './components/History';

export default function App() {
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  return (
    <div className="app">
      <Calculator onCalculation={() => setRefreshTrigger(r => r+1)} />
      <History refreshTrigger={refreshTrigger} />
    </div>
  );
}"""
    },
    {
        "path": "client/src/components/Calculator.js",
        "description": """Calculator component with a display div with id="calculator-display".
IMPORTANT: The display div MUST have id="calculator-display" so tests can find it.
Use useState for display string.
Buttons: 7 8 9 / | 4 5 6 * | 1 2 3 - | 0 . C + | = (full width)
On number/operator: append to display state
On C: setDisplay('')
On =: try { result = String(eval(display)); POST to /api/calculations via axios; props.onCalculation(); setDisplay(result); } catch { setDisplay('ERROR') }
Use axios.post('/api/calculations', {expression: display, result})"""
    },
    {
        "path": "client/src/components/History.js",
        "description": """History component.
Accept refreshTrigger prop.
useEffect with [refreshTrigger] to fetch GET /api/calculations on mount and refresh.
Display each item as: expression = result (timestamp)
Use axios.get('/api/calculations')"""
    },
    {
        "path": "client/src/App.css",
        "description": """CSS for the calculator app.
body: background #1a1a2e, color white, display flex, justify-content center, padding 40px
.app: display flex, flex-direction row, gap 40px
.calculator: background #16213e, padding 20px, border-radius 12px
.display: background #0f3460, color white, font-size 24px, text-align right, padding 10px, margin-bottom 10px, min-height 50px, border-radius 8px
.buttons: display grid, grid-template-columns repeat(4 1fr), gap 8px
button: padding 15px, font-size 18px, background #e94560, color white, border none, border-radius 8px, cursor pointer
button:hover: background #c73652
.equals: grid-column 1 / 5, background #4ecca3
.history: background #16213e, padding 20px, border-radius 12px, width 300px, max-height 500px, overflow-y auto"""
    },
]

# ── SYSTEM PROMPT ──
# Explicitly enforce ES modules and correct paths
SYSTEM_PROMPT = """You are an expert MERN stack developer.
Generate COMPLETE, PRODUCTION-READY file content.

STRICT RULES:
1. ALWAYS use ES module syntax:
   - import express from 'express'   ✓
   - const express = require('express')  ✗ NEVER USE THIS
2. ALWAYS use export default or export const
   - export default router   ✓
   - module.exports = router  ✗ NEVER USE THIS
3. Import paths must be simple package names:
   - import express from 'express'  ✓
   - import express from '../node_modules/express'  ✗ NEVER
4. Use exactly 2 spaces for indentation
5. Write COMPLETE files — no TODOs, no placeholders
6. Return ONLY raw file content — no markdown fences, no explanation
"""

def generate_file_content(filepath: str, description: str) -> str:
    """
    Generate complete content for a single file using Groq.
    Includes a verification pass to catch placeholder comments.
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    # ── GENERATION PASS ──
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
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

    # ── CLEAN OUTPUT ──
    # Strip markdown fences even though we asked not to have them
    # 70B models rarely add them but we handle it defensively
    if content.startswith("```"):
        lines = content.split("\n")
        lines = lines[1:]  # remove opening fence
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]  # remove closing fence
        content = "\n".join(lines).strip()

    # ── VERIFICATION PASS ──
    # Check if the model still added placeholder comments
    # If detected, run a second pass asking it to fix them
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

    found_placeholders = [
        p for p in placeholder_signals
        if p.lower() in content.lower()
    ]

    if found_placeholders:
        print(f"  ⚠ Placeholder detected ({found_placeholders[0]}), running fix pass...")

        fix_messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=f"""The following file has placeholder comments that need to be replaced with real code.
Fix ALL placeholders and return the complete corrected file.

File: {filepath}
Description: {description}

Current content with placeholders:
{content}

Return the complete fixed file with no placeholders.
""")
        ]
        fix_response = llm.invoke(fix_messages)
        content = fix_response.content.strip()

        # Clean fences again after fix pass
        if content.startswith("```"):
            lines = content.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            content = "\n".join(lines).strip()

    return content


def save_file(relative_path: str, content: str) -> str:
    """
    Save generated file into project/relative_path.
    Returns the full saved path.
    """
    full_path = os.path.join(PROJECT_ROOT, relative_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    with open(full_path, 'w', encoding='utf-8') as f:
        f.write(content)

    return full_path


def run_coder(architecture: str = None) -> list:
    """
    Runs the Coder agent.
    Generates all files into project/ folder.
    Returns list of successfully created file paths.
    """
    print("\n" + "="*50)
    print("CODER AGENT STARTING")
    print(f"Model : llama-3.1-70b-versatile via Groq")
    print(f"Files : {len(FILE_PLAN)} files to generate")
    print(f"Output: {PROJECT_ROOT}/")
    print("="*50)

    created_files = []
    failed_files = []
    total = len(FILE_PLAN)

    for i, file_info in enumerate(FILE_PLAN, 1):
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

    # ── SUMMARY ──
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
        for file in files:
            print(f"{subindent}{file}")

    return created_files


if __name__ == "__main__":
    arch_path = os.path.join(PROJECT_ROOT, "architecture.md")

    if not os.path.exists(arch_path):
        print(f"Error: {arch_path} not found.")
        print("Run architect first: python agents/architect.py")
        sys.exit(1)

    with open(arch_path, 'r', encoding='utf-8') as f:
        architecture = f.read()

    run_coder(architecture)





