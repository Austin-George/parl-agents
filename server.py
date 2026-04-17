import os
import sys
import json
import asyncio
import threading
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

app = FastAPI(title="PARL Agent Pipeline API")

# ── CORS ──
# Allows the React dashboard (localhost:3001) to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── CONNECTION MANAGER ──
# Manages all active WebSocket connections
# Multiple browser tabs can connect simultaneously
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"  WebSocket connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        print(f"  WebSocket disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """Send a message to ALL connected clients."""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                disconnected.append(connection)

        # Clean up dead connections
        for conn in disconnected:
            self.active_connections.remove(conn)


manager = ConnectionManager()

# ── PIPELINE STATE ──
# Tracks the current pipeline run status
# This is read by the /status endpoint
pipeline_status = {
    "running": False,
    "current_agent": None,
    "iteration": 0,
    "status": "idle",
    "last_updated": None,
    "result": None
}


# ── EVENT EMITTER ──
# This function is passed into the pipeline so agents can
# broadcast their progress to the frontend in real time
# It runs in a background thread so we need asyncio bridge
def emit_event(event_type: str, data: dict):
    """
    Called by agents to broadcast progress to all WebSocket clients.
    event_type examples: "agent_start", "agent_complete", "file_created",
                         "test_result", "pipeline_complete", "error"
    """
    message = {
        "type": event_type,
        "data": data,
        "timestamp": datetime.now().isoformat()
    }

    # Update pipeline status
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

    # Broadcast to all WebSocket clients
    # Since this runs in a thread, we use asyncio to bridge to async
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(
                manager.broadcast(message), loop
            )
    except Exception as e:
        print(f"  WebSocket broadcast error: {e}")

    # Always print to terminal too
    print(f"  [{event_type}] {json.dumps(data)[:100]}")


# ── PIPELINE RUNNER ──
# Runs the pipeline in a background thread so FastAPI
# stays responsive while agents are working
def run_pipeline_thread(requirements: str):
    """Runs the full pipeline in a background thread."""
    try:
        # Import pipeline
        from pipeline import run_pipeline as execute_pipeline

        pipeline_status["running"] = True
        pipeline_status["status"] = "running"
        pipeline_status["iteration"] = 0

        emit_event("pipeline_start", {
            "message": "Pipeline starting",
            "requirements": requirements[:100]
        })

        # Run the pipeline
        final_state = execute_pipeline(
            requirements=requirements,
            emit_event=emit_event  # pass emitter to pipeline
        )

        # Emit completion
        emit_event("pipeline_complete", {
            "status": final_state.get("status"),
            "iterations": final_state.get("iteration"),
            "files_created": len(final_state.get("created_files", [])),
            "test_status": final_state.get("test_report", {}).get("overall_status"),
            "summary": final_state.get("test_report", {}).get("summary", "")
        })

    except Exception as e:
        emit_event("pipeline_error", {
            "error": str(e),
            "message": "Pipeline failed with an error"
        })
        pipeline_status["running"] = False
        pipeline_status["status"] = "error"


# ── REST ENDPOINTS ──

@app.get("/")
async def root():
    return {"message": "PARL Agent Pipeline API", "status": "running"}


@app.post("/run-pipeline")
async def run_pipeline_endpoint(body: dict):
    """
    Triggers the multi-agent pipeline.
    Accepts: { "requirements": "Build a calculator..." }
    Returns immediately — progress comes via WebSocket.
    """
    if pipeline_status["running"]:
        return JSONResponse(
            status_code=409,
            content={"error": "Pipeline already running"}
        )

    requirements = body.get("requirements", "").strip()
    if not requirements:
        return JSONResponse(
            status_code=400,
            content={"error": "requirements field is required"}
        )

    # Start pipeline in background thread
    thread = threading.Thread(
        target=run_pipeline_thread,
        args=(requirements,),
        daemon=True
    )
    thread.start()

    return {
        "message": "Pipeline started",
        "status": "running",
        "connect_websocket": "ws://localhost:8000/ws"
    }


@app.get("/status")
async def get_status():
    """Returns current pipeline status."""
    return pipeline_status


@app.get("/files")
async def get_files():
    """Returns list of all generated files in project/."""
    project_root = "project"
    files = []

    if not os.path.exists(project_root):
        return {"files": []}

    for root, dirs, filenames in os.walk(project_root):
        dirs[:] = [d for d in dirs if d != "node_modules"]
        for filename in filenames:
            filepath = os.path.join(root, filename)
            rel_path = os.path.relpath(filepath, project_root)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                files.append({
                    "path": rel_path.replace("\\", "/"),
                    "content": content,
                    "size": len(content)
                })
            except:
                pass

    return {"files": files}


@app.get("/logs")
async def get_logs():
    """Returns server and client logs."""
    logs = {}
    for log_name in ["server.log", "client.log"]:
        log_path = os.path.join("logs", log_name)
        if os.path.exists(log_path):
            with open(log_path, 'r') as f:
                logs[log_name] = f.read()[-3000:]  # last 3000 chars
        else:
            logs[log_name] = ""
    return logs


@app.get("/test-report")
async def get_test_report():
    """Returns the latest test report."""
    report_path = "logs/test_report.json"
    if not os.path.exists(report_path):
        return {"error": "No test report found yet"}
    with open(report_path, 'r') as f:
        return json.load(f)


# ── WEBSOCKET ENDPOINT ──
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket connection for real-time pipeline updates.
    The React dashboard connects here to receive live events.
    """
    await manager.connect(websocket)

    # Send current status immediately on connect
    await websocket.send_json({
        "type": "connection_established",
        "data": pipeline_status,
        "timestamp": datetime.now().isoformat()
    })

    try:
        # Keep connection alive — wait for messages from client
        while True:
            data = await websocket.receive_text()
            # Client can send "ping" to keep connection alive
            if data == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        manager.disconnect(websocket)


if __name__ == "__main__":
    print("Starting PARL Agent Pipeline API...")
    print("API docs: http://localhost:8000/docs")
    print("WebSocket: ws://localhost:8000/ws")
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)