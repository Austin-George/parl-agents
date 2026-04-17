import os
import sys
import json
import asyncio
import subprocess
import time
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage
from playwright.async_api import async_playwright

# ── THE BRAIN ──
llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    temperature=0,
    max_tokens=2048
)

# ── TEST SCENARIOS ──
# These are the specific user flows the Tester will verify
# Each scenario has steps the agent will execute in order
# For a calculator app we test basic arithmetic operations
TEST_SCENARIOS = [
    {
        "name": "Addition Test",
        "steps": ["2", "+", "3", "="],
        "expected_result": "5",
        "description": "Verify 2 + 3 = 5"
    },
    {
        "name": "Subtraction Test",
        "steps": ["9", "-", "4", "="],
        "expected_result": "5",
        "description": "Verify 9 - 4 = 5"
    },
    {
        "name": "Multiplication Test",
        "steps": ["3", "*", "4", "="],
        "expected_result": "12",
        "description": "Verify 3 * 4 = 12"
    },
    {
        "name": "Division Test",
        "steps": ["8", "/", "2", "="],
        "expected_result": "4",
        "description": "Verify 8 / 2 = 4"
    },
    {
        "name": "Clear Test",
        "steps": ["5", "+", "3", "C"],
        "expected_result": "",
        "description": "Verify Clear button resets display"
    },
]

# ── PLAYWRIGHT BROWSER ACTIONS ──
# These are the actual browser control functions
# The agent decides WHAT to test, Playwright decides HOW to do it

async def get_page_state(page) -> dict:
    """
    Capture the current state of the calculator page.
    This is the agent's PERCEPTION step — reading the UI.
    Returns a dict with display value, buttons, and history.
    """
    try:
        # Get the display value
        display = await page.locator('[class*="display"], [class*="Display"], #display').first.inner_text()
    except:
        display = "NOT FOUND"

    try:
        # Get all button texts
        buttons = await page.locator('button').all_inner_texts()
    except:
        buttons = []

    try:
        # Get history items if visible
        history_items = await page.locator('[class*="history"] *').all_inner_texts()
        history = history_items[:5]  # just first 5 items
    except:
        history = []

    # Take a screenshot for the trace log
    screenshot_path = f"logs/screenshot_{int(time.time())}.png"
    os.makedirs("logs", exist_ok=True)
    await page.screenshot(path=screenshot_path)

    return {
        "display": display.strip(),
        "buttons_available": buttons,
        "history_preview": history,
        "screenshot": screenshot_path
    }


async def click_button(page, button_text: str) -> str:
    """
    Click a calculator button by its text content.
    Returns confirmation or error message.
    """
    try:
        # Find button by exact text match
        button = page.locator(f'button:has-text("{button_text}")').first
        await button.click()
        await page.wait_for_timeout(300)  # small delay for UI to update
        return f"Clicked button: {button_text}"
    except Exception as e:
        return f"Failed to click {button_text}: {str(e)}"


async def run_test_scenario(page, scenario: dict) -> dict:
    """
    Run a single test scenario by clicking through the steps
    and verifying the expected result.
    Returns a result dict with pass/fail status.
    """
    print(f"\n  Running: {scenario['name']}")
    print(f"  Steps: {' → '.join(scenario['steps'])}")

    # Clear the calculator before each test
    try:
        await page.locator('button:has-text("C")').first.click()
        await page.wait_for_timeout(300)
    except:
        pass

    # Execute each step
    for step in scenario['steps']:
        result = await click_button(page, step)
        print(f"    {result}")
        await page.wait_for_timeout(200)

    # Read the final display state
    state = await get_page_state(page)
    actual_result = state["display"]

    # Compare with expected
    passed = str(actual_result).strip() == str(scenario["expected_result"]).strip()

    result = {
        "scenario": scenario["name"],
        "description": scenario["description"],
        "steps": scenario["steps"],
        "expected": scenario["expected_result"],
        "actual": actual_result,
        "passed": passed,
        "screenshot": state["screenshot"]
    }

    status = "✓ PASS" if passed else "✗ FAIL"
    print(f"  {status} — Expected: '{scenario['expected_result']}' | Got: '{actual_result}'")

    return result


async def run_playwright_tests(base_url: str = "http://localhost:3000") -> list:
    """
    Main Playwright test runner.
    Opens browser, runs all scenarios, returns results.
    """
    print("\nLaunching Chromium browser...")

    async with async_playwright() as p:
        # Launch browser
        # headless=False means you can SEE the browser opening and clicking
        # Set to True to run invisibly in background
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        # ── BROWSER CONSOLE LISTENER ──
        # This captures JavaScript errors that happen inside React
        # These are invisible to the terminal but visible here
        # Stored so we can include them in the failure report
        browser_errors = []
        page.on("console", lambda msg: browser_errors.append(
            f"[{msg.type.upper()}] {msg.text}"
        ) if msg.type in ["error", "warning"] else None)

        page.on("pageerror", lambda err: browser_errors.append(
            f"[JS CRASH] {err}"
        ))


        print(f"Navigating to {base_url}...")
        await page.goto(base_url)

        # Wait for the page to fully load
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(1000)

        # Capture initial page state
        print("\nReading initial page state...")
        initial_state = await get_page_state(page)
        print(f"  Buttons found: {initial_state['buttons_available']}")
        print(f"  Display: '{initial_state['display']}'")

        if not initial_state['buttons_available']:
            print("  ✗ No buttons found — page may not have loaded correctly")
            await browser.close()
            return []

        # Run all test scenarios
        print(f"\nRunning {len(TEST_SCENARIOS)} test scenarios...")
        results = []

        for scenario in TEST_SCENARIOS:
            result = await run_test_scenario(page, scenario)
            results.append(result)


        # Print any browser errors collected during the session
        if browser_errors:
            print("\n  Browser console errors detected:")
            for err in browser_errors:
                print(f"    {err}")

        await browser.close()

        # Attach browser errors to each result so the LLM
        # can reason about them during analysis
        for result in results:
            result["browser_errors"] = browser_errors

        return results


def analyze_results_with_llm(results: list, architecture: str) -> dict:
    """
    Use the LLM to analyze test results and generate a report.
    If tests failed, it produces a structured failure report
    that the Coder agent can act on.

    This is the REASONING step of the Tester's PARL loop —
    making sense of what was observed.
    """
    results_json = json.dumps(results, indent=2)

    # ── Collect browser errors BEFORE building messages list ──
    # This must be outside the messages list — it's Python code
    # not a message object
    all_browser_errors = []
    for r in results:
        all_browser_errors.extend(r.get("browser_errors", []))

    browser_error_text = '\n'.join(all_browser_errors) if all_browser_errors else "None"

    # Now build the messages list using the collected data
    messages = [
        SystemMessage(content="""You are a QA engineer analyzing test results.
Analyze the test results and return a JSON report in this exact format:
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
Return ONLY the JSON object, no explanation."""),
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

    # Strip markdown fences
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()

    try:
        return json.loads(raw)
    except:
        return {
            "overall_status": "UNKNOWN",
            "summary": raw,
            "failures": [],
            "recommendation": "Manual review needed"
        }


def run_tester(architecture: str = "") -> dict:
    """
    Main entry point for the Tester agent.
    Runs Playwright tests and returns analysis report.
    """
    print("\n" + "="*50)
    print("TESTER AGENT STARTING")
    print("="*50)

    # ── PERCEIVE + ACT ──
    # Run the actual browser tests
    results = asyncio.run(run_playwright_tests())

    if not results:
        return {
            "overall_status": "FAIL",
            "summary": "Could not run tests — page did not load",
            "failures": [],
            "recommendation": "Check that React app is running on localhost:3000"
        }

    # ── REASON ──
    # Analyze what happened
    print("\nAnalyzing results with LLM...")
    report = analyze_results_with_llm(results, architecture)

    # ── REPORT ──
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

    print(f"\nRecommendation: {report.get('recommendation')}")

    # Save report to disk for the negotiation loop
    os.makedirs("logs", exist_ok=True)
    report_path = "logs/test_report.json"
    with open(report_path, 'w') as f:
        json.dump({
            "raw_results": results,
            "analysis": report
        }, f, indent=2)

    print(f"\nFull report saved to: {report_path}")

    return report


if __name__ == "__main__":
    arch_path = "project/architecture.md"
    architecture = ""

    if os.path.exists(arch_path):
        with open(arch_path, 'r') as f:
            architecture = f.read()

    run_tester(architecture)