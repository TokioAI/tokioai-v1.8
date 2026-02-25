"""
Tokio CLI Service - FastAPI Server
OpenClaw-based autonomous CLI agent as a standalone service
"""
import os
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Import engine components
from engine.openclaw_engine import OpenClawCLIEngine
from engine.session_manager import SessionManager
from engine.job_queue import JobQueue, Job, JobStatus
from api.websocket_handler import WebSocketHandler
from api.models import (
    JobCreate, JobResponse, SessionInfo, StatsResponse,
    HealthResponse, ToolListResponse, ToolInfo
)

# Logging setup
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global state
engine: Optional[OpenClawCLIEngine] = None
session_manager: Optional[SessionManager] = None
job_queue: Optional[JobQueue] = None
ws_handler: Optional[WebSocketHandler] = None
start_time = datetime.now()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for startup/shutdown"""
    global engine, session_manager, job_queue, ws_handler

    logger.info("🚀 Tokio CLI Service starting...")

    # Initialize workspace
    workspace_path = os.getenv("TOKIO_WORKSPACE", "/workspace/cli")
    os.makedirs(workspace_path, exist_ok=True)
    logger.info(f"📁 Workspace: {workspace_path}")

    # Initialize OpenClaw engine
    llm_provider = os.getenv("LLM_PROVIDER", "gemini")
    engine = OpenClawCLIEngine(
        workspace_path=workspace_path,
        llm_provider=llm_provider
    )
    await engine.initialize()

    # Initialize session manager
    session_manager = SessionManager(engine.workspace)

    # Initialize job queue
    job_queue = JobQueue()
    await job_queue.start_worker(execute_job_background)

    # Initialize WebSocket handler
    ws_handler = WebSocketHandler(engine, session_manager)

    logger.info("✅ Tokio CLI Service ready")

    yield

    # Cleanup
    logger.info("🛑 Tokio CLI Service shutting down...")
    await engine.shutdown()
    await session_manager.cleanup()
    await job_queue.cleanup()

# FastAPI app
app = FastAPI(
    title="Tokio CLI Service",
    description="OpenClaw-based autonomous CLI agent",
    version="3.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# REST API Endpoints
# ============================================================================

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    # Check component health
    components = {
        "engine": "healthy" if engine else "unhealthy",
        "mcp": "healthy" if engine and engine.mcp_client.is_connected() else "unhealthy",
        "session_manager": "healthy" if session_manager else "unhealthy",
        "job_queue": "healthy" if job_queue else "unhealthy"
    }

    # Overall status
    if all(s == "healthy" for s in components.values()):
        status = "healthy"
    elif components["engine"] == "unhealthy":
        status = "unhealthy"
    else:
        status = "degraded"

    return HealthResponse(
        status=status,
        service="tokio-cli",
        version="3.0.0",
        timestamp=datetime.now(),
        components=components
    )

@app.get("/api/cli/stats", response_model=StatsResponse)
async def get_stats():
    """Get service statistics"""
    uptime = (datetime.now() - start_time).total_seconds()

    # Get job queue stats
    job_stats = job_queue.get_stats() if job_queue else {}

    # Get tool count
    tools = await engine.tool_executor.list_all_tools() if engine else []

    return StatsResponse(
        active_sessions=session_manager.get_active_count() if session_manager else 0,
        total_sessions=len(session_manager.sessions) if session_manager else 0,
        queued_jobs=job_stats.get("queued", 0),
        running_jobs=job_stats.get("running", 0),
        completed_jobs=job_stats.get("completed", 0),
        failed_jobs=job_stats.get("failed", 0),
        uptime_seconds=uptime,
        mcp_connected=engine.mcp_client.is_connected() if engine else False,
        total_tools=len(tools)
    )

@app.get("/api/cli/tools", response_model=ToolListResponse)
async def list_tools():
    """List all available tools"""
    tools = await engine.tool_executor.list_all_tools() if engine else []

    # Count by category
    mcp_count = len([t for t in tools if t.get("category") == "MCP"])
    generated_count = len([t for t in tools if t.get("category") == "Generated"])
    base_count = len(tools) - mcp_count - generated_count

    tool_infos = [
        ToolInfo(
            name=t["name"],
            description=t.get("description", ""),
            category=t.get("category", "Unknown"),
            parameters=t.get("parameters", [])
        )
        for t in tools
    ]

    return ToolListResponse(
        tools=tool_infos,
        total=len(tools),
        mcp_tools=mcp_count,
        base_tools=base_count,
        generated_tools=generated_count
    )

@app.post("/api/cli/jobs", response_model=JobResponse)
async def create_job(job_request: JobCreate):
    """Create a new async CLI job"""
    import uuid

    job_id = f"job-{uuid.uuid4().hex[:12]}"
    session_id = job_request.session_id or f"session-{uuid.uuid4().hex[:8]}"

    # Create job
    job = Job(
        job_id=job_id,
        command=job_request.command,
        session_id=session_id,
        max_iterations=job_request.max_iterations,
        timeout=job_request.timeout
    )

    # Submit to queue
    job_queue.submit_job(job)

    logger.info(f"📝 Job created: {job_id} - {job_request.command[:50]}")

    # Convert to response model
    return JobResponse(
        job_id=job.job_id,
        status=job.status.value,
        command=job.command,
        session_id=job.session_id,
        created_at=job.created_at,
        updated_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        iterations_used=job.iterations_used,
        result=job.result,
        error=job.error,
        execution_time=job.get_execution_time()
    )

@app.get("/api/cli/jobs/{job_id}", response_model=JobResponse)
async def get_job_status(job_id: str):
    """Get job status and result"""
    job = job_queue.get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    return JobResponse(
        job_id=job.job_id,
        status=job.status.value,
        command=job.command,
        session_id=job.session_id,
        created_at=job.created_at,
        updated_at=job.completed_at or job.started_at or job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        iterations_used=job.iterations_used,
        result=job.result,
        error=job.error,
        execution_time=job.get_execution_time()
    )

@app.get("/api/cli/sessions", response_model=List[SessionInfo])
async def list_sessions(active_only: bool = False):
    """List all sessions"""
    sessions = session_manager.list_sessions(active_only=active_only)

    return [
        SessionInfo(
            session_id=s.session_id,
            created_at=s.created_at,
            last_activity=s.last_activity,
            message_count=s.get_message_count(),
            active=s.active
        )
        for s in sessions
    ]

@app.get("/api/cli/sessions/{session_id}", response_model=SessionInfo)
async def get_session(session_id: str):
    """Get session details"""
    session = session_manager.get_session(session_id)

    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    return SessionInfo(
        session_id=session.session_id,
        created_at=session.created_at,
        last_activity=session.last_activity,
        message_count=session.get_message_count(),
        active=session.active
    )

@app.delete("/api/cli/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a session"""
    success = session_manager.delete_session(session_id)

    if not success:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    return {"message": f"Session {session_id} deleted"}

# ============================================================================
# WebSocket Endpoint
# ============================================================================

@app.websocket("/ws/cli")
async def websocket_endpoint(websocket: WebSocket):
    """Interactive WebSocket terminal"""
    await ws_handler.handle_connection(websocket)

# ============================================================================
# Background Job Execution
# ============================================================================

async def execute_job_background(job_id: str, job: Job) -> str:
    """
    Execute job in background using OpenClaw engine.

    Called by job queue worker.
    """
    try:
        logger.info(f"▶️ Executing job: {job_id}")

        # Get or create session
        session = session_manager.get_or_create_session(job.session_id)

        # Execute with OpenClaw engine
        result = await engine.process_message(
            message=job.command,
            conversation_history=session.get_conversation_history(),
            max_iterations=job.max_iterations,
            session_id=job.session_id
        )

        # Add to session history
        session.add_message("user", job.command)
        session.add_message("assistant", result)

        # Update job
        job.iterations_used = 1  # Would need to track this in engine

        logger.info(f"✅ Job completed: {job_id}")

        return result

    except Exception as e:
        logger.error(f"❌ Job execution failed [{job_id}]: {e}")
        raise

# ============================================================================
# Entry Point
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8100))

    uvicorn.run(
        "server:app",
        host="YOUR_IP_ADDRESS",
        port=port,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
        reload=False
    )
