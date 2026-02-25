"""
API Models - Pydantic models for request/response validation
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

# ============================================================================
# Job Models
# ============================================================================

class JobCreate(BaseModel):
    """Request to create a new CLI job"""
    command: str = Field(..., description="Command to execute", min_length=1)
    session_id: Optional[str] = Field(None, description="Existing session ID to use")
    max_iterations: int = Field(10, description="Max OpenClaw iterations", ge=1, le=50)
    timeout: int = Field(300, description="Timeout in seconds", ge=10, le=3600)

class JobResponse(BaseModel):
    """Job status and result"""
    job_id: str
    status: str  # pending, running, completed, failed, cancelled
    command: str
    session_id: Optional[str] = None
    result: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    iterations_used: int = 0
    execution_time: Optional[float] = None  # seconds

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

# ============================================================================
# Session Models
# ============================================================================

class SessionInfo(BaseModel):
    """Session information"""
    session_id: str
    created_at: datetime
    last_activity: datetime
    message_count: int
    active: bool

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

class SessionListResponse(BaseModel):
    """List of sessions"""
    sessions: List[SessionInfo]
    total: int

# ============================================================================
# Stats Models
# ============================================================================

class StatsResponse(BaseModel):
    """Service statistics"""
    active_sessions: int
    total_sessions: int
    queued_jobs: int
    running_jobs: int
    completed_jobs: int
    failed_jobs: int
    uptime_seconds: float
    mcp_connected: bool
    total_tools: int

# ============================================================================
# WebSocket Models
# ============================================================================

class WSMessage(BaseModel):
    """WebSocket message (client -> server)"""
    type: str = Field(..., description="Message type: command, cancel, status")
    content: Optional[str] = Field(None, description="Message content (for type=command)")
    job_id: Optional[str] = Field(None, description="Job ID (for type=cancel)")

class WSResponse(BaseModel):
    """WebSocket response (server -> client)"""
    type: str = Field(..., description="welcome, progress, tool_call, tool_result, output, done, error")
    session_id: Optional[str] = None
    message: Optional[str] = None
    tool: Optional[str] = None
    args: Optional[Dict[str, Any]] = None
    success: Optional[bool] = None
    output: Optional[str] = None
    result: Optional[str] = None
    error: Optional[str] = None
    iteration: Optional[int] = None

# ============================================================================
# Tool Models
# ============================================================================

class ToolInfo(BaseModel):
    """Tool information"""
    name: str
    description: str
    category: str
    parameters: List[str]

class ToolListResponse(BaseModel):
    """List of available tools"""
    tools: List[ToolInfo]
    total: int
    mcp_tools: int
    base_tools: int
    generated_tools: int

# ============================================================================
# Error Models
# ============================================================================

class ErrorResponse(BaseModel):
    """Error response"""
    error: str
    detail: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

# ============================================================================
# Health Models
# ============================================================================

class HealthResponse(BaseModel):
    """Health check response"""
    status: str  # healthy, degraded, unhealthy
    service: str
    version: str
    timestamp: datetime
    components: Dict[str, str]  # component -> status

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
