import os
import time
import subprocess
import requests


class ServerManager:
    def __init__(self):
        self.backend_process = None
        self.frontend_process = None
        self.project_root = "project"

    def run_npm_install(self, folder: str) -> bool:
        """Runs npm install in the given folder."""
        full_path = os.path.join(self.project_root, folder)
        print(f"\n  Running npm install in {full_path}...")

        result = subprocess.run(
            "npm install",
            cwd=full_path,
            capture_output=True,
            text=True,
            timeout=120,
            shell=True  # ← add this
        )

        if result.returncode != 0:
            print(f"  ✗ npm install failed in {folder}")
            print(f"  STDERR: {result.stderr[:500]}")
            return False

        print(f"  ✓ npm install complete in {folder}")
        return True

    def start_backend(self) -> bool:
        """Starts Express server as background process."""
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
            shell=True  # ← add this
        )

        # Poll until server responds
        for i in range(15):
            time.sleep(1)
            try:
                response = requests.get(
                    "http://localhost:5000/api/calculations",
                    timeout=2
                )
                if response.status_code == 200:
                    print(f"  ✓ Express server ready on port 5000")
                    return True
            except:
                print(f"  Waiting for server... ({i+1}s)")

        print("  ✗ Express server failed to start")
        self._print_server_errors()
        return False

    def start_frontend(self) -> bool:
        """Starts React dev server as background process."""
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
            shell=True  # ← add this
        )

        # React takes longer — poll for 60 seconds
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

    def read_server_errors(self) -> str:
        """Reads error lines from server log."""
        log_path = "logs/server.log"
        if not os.path.exists(log_path):
            return ""

        with open(log_path, 'r') as f:
            content = f.read()

        error_lines = []
        for line in content.split('\n'):
            if any(indicator in line.lower() for indicator in
                   ['error', 'cannot find', 'failed', 'undefined',
                    'syntaxerror', 'typeerror', 'referenceerror']):
                error_lines.append(line)

        return '\n'.join(error_lines)

    def read_client_errors(self) -> str:
        """Reads React compilation errors from client log."""
        log_path = "logs/client.log"
        if not os.path.exists(log_path):
            return ""

        with open(log_path, 'r') as f:
            content = f.read()

        error_lines = []
        for line in content.split('\n'):
            if any(indicator in line.lower() for indicator in
                   ['error', 'failed to compile', 'module not found',
                    'syntaxerror', 'cannot find module']):
                error_lines.append(line)

        return '\n'.join(error_lines)

    def _print_server_errors(self):
        errors = self.read_server_errors()
        if errors:
            print("\n  Server errors detected:")
            for line in errors.split('\n')[:10]:
                print(f"    {line}")

    def _print_client_errors(self):
        errors = self.read_client_errors()
        if errors:
            print("\n  Client errors detected:")
            for line in errors.split('\n')[:10]:
                print(f"    {line}")

    def stop_all(self):
        """Stops both servers cleanly."""
        print("\n  Stopping servers...")
        if self.backend_process:
            self.backend_process.terminate()
            self.backend_process = None
            print("  ✓ Express server stopped")
        if self.frontend_process:
            self.frontend_process.terminate()
            self.frontend_process = None
            print("  ✓ React frontend stopped")

    def setup_and_start(self) -> dict:
        """
        Full setup sequence:
        1. npm install both server and client
        2. Start backend
        3. Start frontend
        Returns dict with success status and any errors found.
        """
        os.makedirs("logs", exist_ok=True)
        print("\n" + "="*50)
        print("SERVER MANAGER — Setting up servers")
        print("="*50)

        errors = {}

        # Install dependencies
        server_ok = self.run_npm_install("server")
        client_ok = self.run_npm_install("client")

        if not server_ok:
            errors["server_install"] = self.read_server_errors()

        if not client_ok:
            errors["client_install"] = self.read_client_errors()

        if errors:
            return {"success": False, "errors": errors}

        # Start backend first
        backend_ok = self.start_backend()
        if not backend_ok:
            server_errors = self.read_server_errors()
            return {
                "success": False,
                "errors": {
                    "server_start": server_errors or "Server failed to start"
                }
            }

        # Then start frontend
        frontend_ok = self.start_frontend()
        if not frontend_ok:
            client_errors = self.read_client_errors()
            return {
                "success": False,
                "errors": {
                    "client_start": client_errors or "React failed to start"
                }
            }

        print("\n✓ Both servers running — ready for Playwright tests")
        return {"success": True, "errors": {}}