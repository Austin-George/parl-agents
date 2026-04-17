import os
import sys
import json
import asyncio
import time
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage
from playwright.async_api import async_playwright

# ── THE BRAIN ──
# Used for two tasks:
# 1. Generating test scenarios from architecture
# 2. Analyzing test results and producing failure reports
llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    temperature=0,
    max_tokens=2048
)

# ── SCENARIO GENERATION PROMPT ──
# Asks the LLM to produce a structured list of UI test actions
# based on whatever app the Architect designed
SCENARIO_GENERATION_PROMPT = """You are a QA engineer writing Playwright test scenarios.
Given an architecture spec, generate UI test scenarios.

Return ONLY a JSON array in this exact format:
[
  {
    "name": "Test name",
    "description": "what this test verifies",
    "actions": [
      {"type": "navigate", "url": "http://localhost:3000"},
      {"type": "click", "selector": "button:has-text('Add')"},
      {"type": "fill", "selector": "input[placeholder='Task name']", "value": "Buy groceries"},
      {"type": "click", "selector": "button:has-text('Save')"},
      {"type": "assert_text", "selector": ".task-list", "expected": "Buy groceries"}
    ]
  }
]

Available action types:
- navigate   : go to a URL               (fields: url)
- click      : click an element          (fields: selector)
- fill       : type into an input        (fields: selector, value)
- assert_text: verify element has text   (fields: selector, expected)
- assert_visible: verify element exists  (fields: selector)
- wait       : pause execution           (fields: value in ms)

Rules:
- Use realistic selectors based on the architecture components
- Test the core user flows described in the architecture
- Generate 3-5 test scenarios covering the main features
- Return ONLY the JSON array, no explanation
"""

# ── RESULT ANALYSIS PROMPT ──
# Asks the LLM to reason about what failed and why
# Produces structured failure reports the Coder can act on
RESULT_ANALYSIS_PROMPT = """You are a QA engineer analyzing Playwright test results.
Analyze the results and return a JSON report in this exact format:
{
  "overall_status": "PASS" or "FAIL",
  "passed_count": number,
  "failed_count": number,
  "summary": "brief overall summary",
  "failures": [
    {
      "scenario": "test name",
      "expected": "expected value",
      "actual": "actual value",
      "likely_cause": "your diagnosis of why it failed",
      "fix_needed": "specific code change needed to fix this"
    }
  ],
  "recommendation": "what the Coder agent should do next"
}
Return ONLY the JSON object, no explanation.
"""


# ──────────────────────────────────────────
# SCENARIO GENERATION
# ──────────────────────────────────────────

def generate_test_scenarios(architecture: str) -> list:
    """
    Dynamically generates Playwright test scenarios
    from the architecture spec.
    Works for any app — not hardcoded to any specific project.
    This is the PERCEIVE step — understanding what needs testing.
    """
    print("\n  Generating test scenarios from architecture...")

    messages = [
        SystemMessage(content=SCENARIO_GENERATION_PROMPT),
        HumanMessage(content=f"""Generate test scenarios for this app:

{architecture}

The app runs on http://localhost:3000
""")
    ]

    response = llm.invoke(
        messages,
        config={
            "run_name": "Tester — Generate Scenarios",
            "tags": ["tester", "parl", "planning"],
            "metadata": {
                "agent": "tester",
                "step": "scenario_planning",
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

    # Extract just the JSON array
    start = raw.find("[")
    end = raw.rfind("]") + 1
    if start != -1 and end != 0:
        raw = raw[start:end]

    try:
        scenarios = json.loads(raw)
        print(f"  → Generated {len(scenarios)} scenarios:")
        for s in scenarios:
            print(f"    - {s['name']}")
        return scenarios
    except json.JSONDecodeError as e:
        print(f"  ✗ Could not parse scenarios: {e}")
        return []


# ──────────────────────────────────────────
# PLAYWRIGHT BROWSER ACTIONS
# ──────────────────────────────────────────

async def execute_scenario(page, scenario: dict) -> dict:
    """
    Executes a single test scenario by running each action
    in sequence. Stops on first failure.
    This is the ACT step — physically interacting with the UI.

    Supported action types:
    navigate, click, fill, assert_text, assert_visible, wait
    """
    print(f"\n  Running: {scenario['name']}")

    passed = True
    error_message = ""
    actions_completed = 0

    for action in scenario.get("actions", []):
        action_type = action.get("type")

        try:
            if action_type == "navigate":
                await page.goto(action["url"])
                await page.wait_for_load_state("networkidle")
                await page.wait_for_timeout(500)

            elif action_type == "click":
                await page.locator(action["selector"]).first.click()
                await page.wait_for_timeout(300)

            elif action_type == "fill":
                await page.locator(action["selector"]).first.fill(action["value"])
                await page.wait_for_timeout(200)

            elif action_type == "assert_text":
                element = page.locator(action["selector"]).first
                actual = await element.inner_text()
                if action["expected"] not in actual:
                    passed = False
                    error_message = (
                        f"Expected '{action['expected']}' "
                        f"in '{actual[:50]}'"
                    )

            elif action_type == "assert_visible":
                visible = await page.locator(action["selector"]).first.is_visible()
                if not visible:
                    passed = False
                    error_message = f"Element '{action['selector']}' not visible"

            elif action_type == "wait":
                await page.wait_for_timeout(int(action.get("value", 500)))

            actions_completed += 1

        except Exception as e:
            passed = False
            error_message = f"Action '{action_type}' failed: {str(e)[:100]}"
            print(f"    ✗ {error_message}")
            break

    status = "✓ PASS" if passed else "✗ FAIL"
    print(f"  {status} — {scenario['name']}")
    if not passed:
        print(f"    Reason: {error_message}")

    # Screenshot after each scenario for the trace log
    screenshot_path = f"logs/screenshot_{scenario['name'].replace(' ', '_')}.png"
    os.makedirs("logs", exist_ok=True)
    await page.screenshot(path=screenshot_path)

    return {
        "scenario": scenario["name"],
        "description": scenario.get("description", ""),
        "passed": passed,
        "error": error_message,
        "actions_completed": actions_completed,
        "total_actions": len(scenario.get("actions", [])),
        "screenshot": screenshot_path
    }


async def run_playwright_tests(
    base_url: str = "http://localhost:3000",
    scenarios: list = None
) -> list:
    """
    Opens a real Chromium browser and runs all test scenarios.
    Captures browser console errors and page crashes automatically.
    Returns list of result dicts — one per scenario.
    """
    print("\n  Launching Chromium browser...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        # ── BROWSER ERROR LISTENERS ──
        # Captures JS errors that happen inside React
        # These are invisible to the terminal but visible here
        browser_errors = []

        page.on("console", lambda msg: browser_errors.append(
            f"[{msg.type.upper()}] {msg.text}"
        ) if msg.type in ["error", "warning"] else None)

        page.on("pageerror", lambda err: browser_errors.append(
            f"[JS CRASH] {err}"
        ))

        print(f"  Navigating to {base_url}...")
        await page.goto(base_url)
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(1000)

        print(f"\n  Running {len(scenarios)} scenarios...")
        results = []

        for scenario in scenarios:
            result = await execute_scenario(page, scenario)
            results.append(result)

        # Print browser errors collected during the full session
        if browser_errors:
            print("\n  Browser console errors detected:")
            for err in browser_errors:
                print(f"    {err}")

        # Attach browser errors to every result
        # so the LLM can reason about them during analysis
        for result in results:
            result["browser_errors"] = browser_errors

        await browser.close()
        return results


# ──────────────────────────────────────────
# RESULT ANALYSIS
# ──────────────────────────────────────────

def analyze_results_with_llm(results: list, architecture: str) -> dict:
    """
    Uses the LLM to analyze Playwright results and produce
    a structured failure report the Coder agent can act on.
    This is the REASON step — making sense of what was observed.
    """
    results_json = json.dumps(results, indent=2)

    # Collect all browser errors across all scenarios
    all_browser_errors = []
    for r in results:
        all_browser_errors.extend(r.get("browser_errors", []))
    browser_error_text = '\n'.join(all_browser_errors) or "None"

    messages = [
        SystemMessage(content=RESULT_ANALYSIS_PROMPT),
        HumanMessage(content=f"""Analyze these test results:

{results_json}

Browser console errors detected during tests:
{browser_error_text}

Architecture context:
{architecture[:500]}
""")
    ]

    response = llm.invoke(
        messages,
        config={
            "run_name": "Tester — Result Analysis",
            "tags": ["tester", "parl", "analysis"],
            "metadata": {
                "agent": "tester",
                "total_tests": len(results),
                "passed": sum(1 for r in results if r.get("passed")),
                "failed": sum(1 for r in results if not r.get("passed"))
            }
        }
    )

    raw = response.content.strip()

    # Strip markdown fences if present
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {
            "overall_status": "UNKNOWN",
            "passed_count": 0,
            "failed_count": len(results),
            "summary": raw,
            "failures": [],
            "recommendation": "Manual review needed — could not parse LLM analysis"
        }


# ──────────────────────────────────────────
# MAIN ENTRY POINT
# ──────────────────────────────────────────

def run_tester(architecture: str = "") -> dict:
    """
    Runs the full Tester agent PARL loop:
    Perceive → generate test scenarios from architecture
    Act      → run Playwright browser tests
    Reason   → analyze results with LLM
    Learn    → save report for negotiation loop
    """
    print("\n" + "="*50)
    print("TESTER AGENT STARTING")
    print("="*50)

    # ── PERCEIVE ──
    # Understand what needs to be tested
    scenarios = generate_test_scenarios(architecture)

    if not scenarios:
        return {
            "overall_status": "FAIL",
            "passed_count": 0,
            "failed_count": 0,
            "summary": "Could not generate test scenarios",
            "failures": [],
            "recommendation": "Check that architecture.md exists and is valid"
        }

    # ── ACT ──
    # Run the actual browser tests
    results = asyncio.run(
        run_playwright_tests(
            base_url="http://localhost:3000",
            scenarios=scenarios
        )
    )

    if not results:
        return {
            "overall_status": "FAIL",
            "passed_count": 0,
            "failed_count": 0,
            "summary": "Could not run tests — page did not load",
            "failures": [],
            "recommendation": "Check React app is running on localhost:3000"
        }

    # ── REASON ──
    # Analyze what happened and produce structured report
    print("\n  Analyzing results with LLM...")
    report = analyze_results_with_llm(results, architecture)

    # ── LEARN ──
    # Save report so pipeline and negotiation loop can read it
    print("\n" + "="*50)
    print("TESTER AGENT REPORT")
    print("="*50)
    print(f"\nOverall Status : {report.get('overall_status')}")
    print(f"Passed         : {report.get('passed_count', 0)}")
    print(f"Failed         : {report.get('failed_count', 0)}")
    print(f"Summary        : {report.get('summary')}")

    if report.get('failures'):
        print("\nFailures:")
        for f in report['failures']:
            print(f"  ✗ {f['scenario']}")
            print(f"    Cause : {f.get('likely_cause')}")
            print(f"    Fix   : {f.get('fix_needed')}")

    os.makedirs("logs", exist_ok=True)
    report_path = "logs/test_report.json"
    with open(report_path, 'w') as f:
        json.dump({
            "raw_results": results,
            "analysis": report
        }, f, indent=2)

    print(f"\n  Report saved to: {report_path}")
    return report


# ── RUN DIRECTLY TO TEST ──
if __name__ == "__main__":
    arch_path = "project/architecture.md"
    architecture = ""

    if os.path.exists(arch_path):
        with open(arch_path, 'r') as f:
            architecture = f.read()
        print(f"✓ Read architecture.md ({len(architecture)} chars)")
    else:
        print("⚠ No architecture.md found — running with empty architecture")

    run_tester(architecture)