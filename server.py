import os
import json
import asyncio
import threading
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn
import logging

# ──────────────────────────────────────────
# APP SETUP
# ──────────────────────────────────────────

app = FastAPI(title="PARL Agent Pipeline API")

# Suppress uvicorn access logs (the INFO lines like "GET /status 200")
# Only WARNING and ERROR level logs will show
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
logging.getLogger("fastapi").setLevel(logging.WARNING)

# Allow the React dashboard on any port to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──────────────────────────────────────────
# WEBSOCKET CONNECTION MANAGER
# ──────────────────────────────────────────

class ConnectionManager:
    """
    Manages all active WebSocket connections.
    Multiple browser tabs can connect simultaneously —
    all receive the same broadcast messages.
    """

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"  WebSocket connected. Active: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        print(f"  WebSocket disconnected. Active: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """
        Sends a message to all connected clients.
        Automatically removes dead connections.
        """
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)

        for conn in disconnected:
            self.active_connections.remove(conn)


manager = ConnectionManager()

# ──────────────────────────────────────────
# PIPELINE STATE
# ──────────────────────────────────────────

# Tracks the current pipeline run.
# Read by the /status endpoint and updated by emit_event.
pipeline_status = {
    "running":       False,
    "current_agent": None,
    "iteration":     0,
    "status":        "idle",
    "last_updated":  None,
    "result":        None
}

# ──────────────────────────────────────────
# EVENT EMITTER
# ──────────────────────────────────────────

def emit_event(event_type: str, data: dict):
    """
    Broadcasts a pipeline event to all WebSocket clients.
    Called by agent nodes in pipeline.py during execution.

    Runs in a background thread, so uses asyncio bridge
    to safely communicate with the async WebSocket layer.

    Event types:
    - pipeline_start    : pipeline has begun
    - agent_start       : an agent node started
    - agent_complete    : an agent node finished
    - pipeline_complete : entire pipeline finished
    - pipeline_error    : pipeline crashed
    """
    message = {
        "type":      event_type,
        "data":      data,
        "timestamp": datetime.now().isoformat()
    }

    # ── UPDATE PIPELINE STATUS ──
    pipeline_status["last_updated"] = message["timestamp"]

    if event_type == "agent_start":
        pipeline_status["current_agent"] = data.get("agent")
        pipeline_status["status"] = "running"

    elif event_type == "pipeline_complete":
        pipeline_status["running"] = False
        pipeline_status["status"] = "complete"
        pipeline_status["result"] = data
        pipeline_status["current_agent"] = None

    elif event_type == "pipeline_error":
        pipeline_status["running"] = False
        pipeline_status["status"] = "error"
        pipeline_status["current_agent"] = None

    # ── BROADCAST TO WEBSOCKET CLIENTS ──
    # Bridge from sync thread to async event loop
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(
                manager.broadcast(message), loop
            )
    except Exception as e:
        print(f"  WebSocket broadcast error: {e}")

    # Always print to terminal for debugging
    print(f"  [{event_type}] {json.dumps(data)[:120]}")


# ──────────────────────────────────────────
# PIPELINE THREAD
# ──────────────────────────────────────────

def run_pipeline_thread(requirements: str):
    """
    Runs the full multi-agent pipeline in a background thread.
    FastAPI stays responsive while agents are working.
    Emits WebSocket events throughout so the dashboard
    receives live updates.
    """
    try:
        from pipeline import run_pipeline as execute_pipeline

        pipeline_status["running"] = True
        pipeline_status["status"] = "running"
        pipeline_status["iteration"] = 0

        # Run the pipeline — pass emit_event so agents can
        # broadcast their progress to the dashboard
        final_state = execute_pipeline(
            requirements=requirements,
            emit_event=emit_event
        )

        # Broadcast completion summary
        test_report = final_state.get("test_report", {})
        emit_event("pipeline_complete", {
            "status":        final_state.get("status"),
            "iterations":    final_state.get("iteration"),
            "files_created": len(final_state.get("created_files", [])),
            "test_status":   test_report.get("overall_status"),
            "summary":       test_report.get("summary", "")
        })

    except Exception as e:
        emit_event("pipeline_error", {
            "error":   str(e),
            "message": "Pipeline failed with an error"
        })
        pipeline_status["running"] = False
        pipeline_status["status"] = "error"


# ──────────────────────────────────────────
# REST ENDPOINTS
# ──────────────────────────────────────────

@app.get("/")
async def root():
    """Health check — confirms the API is running."""
    return {"message": "PARL Agent Pipeline API", "status": "running"}


@app.post("/run-pipeline")
async def run_pipeline_endpoint(body: dict):
    """
    Triggers the multi-agent pipeline with the given requirements.

    Accepts:
        { "requirements": "Build a todo app using MERN stack..." }

    Returns immediately — live progress is streamed via WebSocket.
    Connect to ws://localhost:8000/ws to receive events.

    Returns 409 if a pipeline is already running.
    Returns 400 if requirements field is missing or empty.
    """
    if pipeline_status["running"]:
        return JSONResponse(
            status_code=409,
            content={"error": "Pipeline already running. Wait for it to finish."}
        )

    requirements = body.get("requirements", "").strip()
    if not requirements:
        return JSONResponse(
            status_code=400,
            content={"error": "requirements field is required and cannot be empty"}
        )

    # Start pipeline in background — don't block the HTTP response
    thread = threading.Thread(
        target=run_pipeline_thread,
        args=(requirements,),
        daemon=True
    )
    thread.start()

    return {
        "message":           "Pipeline started successfully",
        "status":            "running",
        "websocket":         "ws://localhost:8000/ws",
        "requirements_preview": requirements[:100]
    }


@app.get("/status")
async def get_status():
    """
    Returns the current pipeline status.
    Useful for polling if WebSocket is not available.
    """
    return pipeline_status


@app.get("/files")
async def get_files():
    """
    Returns all files generated in the project/ folder
    with their content and size.
    Skips node_modules and binary files.
    Works for any generated app — not hardcoded to any project.
    """
    project_root = "project"
    files = []

    if not os.path.exists(project_root):
        return {"files": [], "total": 0}

    for root, dirs, filenames in os.walk(project_root):
        # Skip node_modules — too large and not useful to display
        dirs[:] = [d for d in dirs if d != "node_modules"]

        for filename in filenames:
            filepath = os.path.join(root, filename)
            rel_path = os.path.relpath(filepath, project_root)

            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                files.append({
                    "path":    rel_path.replace("\\", "/"),
                    "content": content,
                    "size":    len(content)
                })
            except Exception:
                # Skip binary files or files with encoding issues
                pass

    return {"files": files, "total": len(files)}


@app.get("/logs")
async def get_logs():
    """
    Returns the last 3000 characters of server and client logs.
    Used by the dashboard to show runtime errors.
    """
    logs = {}
    for log_name in ["server.log", "client.log"]:
        log_path = os.path.join("logs", log_name)
        if os.path.exists(log_path):
            with open(log_path, 'r') as f:
                content = f.read()
            # Return only last 3000 chars — logs can get large
            logs[log_name] = content[-3000:] if len(content) > 3000 else content
        else:
            logs[log_name] = ""
    return logs


@app.get("/test-report")
async def get_test_report():
    """
    Returns the latest Playwright test report.
    Includes raw results per scenario and LLM analysis.
    """
    report_path = "logs/test_report.json"

    if not os.path.exists(report_path):
        return {"error": "No test report found. Run the pipeline first."}

    with open(report_path, 'r') as f:
        return json.load(f)


@app.get("/architecture")
async def get_architecture():
    """
    Returns the architecture.md generated by the Architect agent.
    Useful for the dashboard to show what was designed.
    """
    arch_path = "project/architecture.md"

    if not os.path.exists(arch_path):
        return {"error": "No architecture found. Run the pipeline first."}

    with open(arch_path, 'r', encoding='utf-8') as f:
        content = f.read()

    return {"content": content, "length": len(content)}


# ──────────────────────────────────────────
# WEBSOCKET ENDPOINT
# ──────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time pipeline updates.
    The React dashboard connects here on load and receives
    all agent events as they happen.

    Client can send "ping" messages to keep the connection alive.
    Server responds with "pong".
    """
    await manager.connect(websocket)

    # Send current status immediately on connect
    # so the dashboard reflects the right state even if
    # the pipeline was already running before the page loaded
    await websocket.send_json({
        "type":      "connection_established",
        "data":      pipeline_status,
        "timestamp": datetime.now().isoformat()
    })

    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        manager.disconnect(websocket)


# ──────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "="*50)
    print("  PARL Agent Pipeline API")
    print("="*50)
    print(f"  API docs  : http://localhost:8000/docs")
    print(f"  WebSocket : ws://localhost:8000/ws")
    print(f"  Status    : http://localhost:8000/status")
    print("="*50 + "\n")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="warning"  # ← only warnings and errors
    )