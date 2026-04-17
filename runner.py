import os
import time
import subprocess
import requests


class ServerManager:
    """
    Manages starting and stopping the Express and React servers
    as background processes so the pipeline runs fully automated.

    Responsibilities:
    - Install npm dependencies for both server and client
    - Start Express backend and wait until it responds
    - Start React frontend and wait until it responds
    - Read server/client logs to surface errors to the pipeline
    - Stop both servers cleanly after tests complete
    """

    def __init__(self):
        self.backend_process = None
        self.frontend_process = None
        self.project_root = "project"

    # ──────────────────────────────────────────
    # SETUP
    # ──────────────────────────────────────────

    def setup_and_start(self) -> dict:
        """
        Full setup sequence:
        1. npm install in server/ and client/
        2. Start Express backend
        3. Start React frontend
        4. Return success status with any errors found

        Called by tester_node in pipeline.py before running
        Playwright tests. Errors returned here are treated as
        test failures so the Coder agent can fix them.
        """
        os.makedirs("logs", exist_ok=True)

        print("\n" + "="*50)
        print("SERVER MANAGER — Setting up servers")
        print("="*50)

        # ── INSTALL DEPENDENCIES ──
        server_ok = self.run_npm_install("server")
        client_ok = self.run_npm_install("client")

        errors = {}
        if not server_ok:
            errors["server_install"] = self.read_server_errors()
        if not client_ok:
            errors["client_install"] = self.read_client_errors()

        if errors:
            return {"success": False, "errors": errors}

        # ── START BACKEND FIRST ──
        # Frontend may make API calls on load so backend must be ready first
        backend_ok = self.start_backend()
        if not backend_ok:
            return {
                "success": False,
                "errors": {
                    "server_start": self.read_server_errors()
                                    or "Server failed to start"
                }
            }

        # ── START FRONTEND ──
        frontend_ok = self.start_frontend()
        if not frontend_ok:
            return {
                "success": False,
                "errors": {
                    "client_start": self.read_client_errors()
                                    or "React failed to start"
                }
            }

        print("\n✓ Both servers running — ready for Playwright tests")
        return {"success": True, "errors": {}}

    def stop_all(self):
        """
        Terminates both server processes cleanly.
        Always called in the pipeline's finally block
        so servers stop even if tests crash.
        """
        print("\n  Stopping servers...")

        if self.backend_process:
            self.backend_process.terminate()
            self.backend_process = None
            print("  ✓ Express server stopped")

        if self.frontend_process:
            self.frontend_process.terminate()
            self.frontend_process = None
            print("  ✓ React frontend stopped")

    # ──────────────────────────────────────────
    # NPM INSTALL
    # ──────────────────────────────────────────

    def run_npm_install(self, folder: str) -> bool:
        """
        Runs npm install in project/folder.
        Uses shell=True so Windows resolves npm.cmd correctly.
        Returns True if successful.
        """
        full_path = os.path.join(self.project_root, folder)
        print(f"\n  Running npm install in {full_path}...")

        result = subprocess.run(
            "npm install",
            cwd=full_path,
            capture_output=True,
            text=True,
            timeout=120,
            shell=True
        )

        if result.returncode != 0:
            print(f"  ✗ npm install failed in {folder}")
            print(f"  STDERR: {result.stderr[:500]}")
            return False

        print(f"  ✓ npm install complete in {folder}")
        return True

    # ──────────────────────────────────────────
    # START SERVERS
    # ──────────────────────────────────────────

    def start_backend(self) -> bool:
        """
        Starts Express server as a background process.
        Uses the root endpoint / as a generic health check
        so this works for any generated app, not just calculator.
        """
        server_path = os.path.join(self.project_root, "server")
        print(f"\n  Starting Express server...")

        os.makedirs("logs", exist_ok=True)
        log_file = open("logs/server.log", "w")

        self.backend_process = subprocess.Popen(
            "node app.js",
            cwd=server_path,
            stdout=log_file,
            stderr=log_file,
            text=True,
            shell=True
        )

        for i in range(15):
            time.sleep(1)
            try:
                # Use root endpoint as generic health check
                # Works for any Express app regardless of routes
                response = requests.get(
                    "http://localhost:5000",
                    timeout=2
                )
                # Any response means server is up — even 404
                # means Express is running and responding
                if response.status_code in [200, 404]:
                    print(f"  ✓ Express server ready on port 5000")
                    return True
            except:
                print(f"  Waiting for server... ({i+1}s)")

        print("  ✗ Express server failed to start")
        self._print_server_errors()
        return False

    def start_frontend(self) -> bool:
        """
        Starts React dev server as a background process.
        Writes all output to logs/client.log.
        Polls localhost:3000 until React responds
        or times out after 60 seconds.

        CI=false  → prevents React treating warnings as errors
        BROWSER=none → prevents auto-opening a browser tab
        """
        client_path = os.path.join(self.project_root, "client")
        print(f"\n  Starting React frontend...")

        os.makedirs("logs", exist_ok=True)
        log_file = open("logs/client.log", "w")

        env = os.environ.copy()
        env["CI"] = "false"
        env["BROWSER"] = "none"

        self.frontend_process = subprocess.Popen(
            "npm start",
            cwd=client_path,
            stdout=log_file,
            stderr=log_file,
            text=True,
            env=env,
            shell=True
        )

        for i in range(60):
            time.sleep(1)
            try:
                response = requests.get(
                    "http://localhost:3000",
                    timeout=2
                )
                if response.status_code == 200:
                    print(f"  ✓ React frontend ready on port 3000")
                    return True
            except:
                if i % 5 == 0:
                    print(f"  Waiting for React... ({i+1}s)")

        print("  ✗ React frontend failed to start")
        self._print_client_errors()
        return False

    # ──────────────────────────────────────────
    # ERROR READING
    # ──────────────────────────────────────────

    def read_server_errors(self) -> str:
        """
        Reads logs/server.log and returns lines that contain
        error indicators. Called by the pipeline to surface
        runtime crashes back to the Coder agent.
        """
        return self._read_errors(
            log_path="logs/server.log",
            indicators=[
                'error', 'cannot find', 'failed',
                'syntaxerror', 'typeerror', 'referenceerror'
            ]
        )

    def read_client_errors(self) -> str:
        """
        Reads logs/client.log and returns lines that contain
        React compilation error indicators.
        """
        return self._read_errors(
            log_path="logs/client.log",
            indicators=[
                'error', 'failed to compile', 'module not found',
                'syntaxerror', 'cannot find module'
            ]
        )

    def _read_errors(self, log_path: str, indicators: list) -> str:
        """
        Generic log reader — filters lines by error indicators.
        Shared by read_server_errors and read_client_errors.
        """
        if not os.path.exists(log_path):
            return ""

        with open(log_path, 'r') as f:
            content = f.read()

        error_lines = [
            line for line in content.split('\n')
            if any(ind in line.lower() for ind in indicators)
        ]

        return '\n'.join(error_lines)

    def _print_server_errors(self):
        """Prints first 10 server error lines to terminal."""
        errors = self.read_server_errors()
        if errors:
            print("\n  Server errors detected:")
            for line in errors.split('\n')[:10]:
                print(f"    {line}")

    def _print_client_errors(self):
        """Prints first 10 client error lines to terminal."""
        errors = self.read_client_errors()
        if errors:
            print("\n  Client errors detected:")
            for line in errors.split('\n')[:10]:
                print(f"    {line}")