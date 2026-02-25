# Tokio CLI Service

**OpenClaw-based autonomous CLI agent as a standalone microservice**

## Overview

Tokio CLI Service is a **separate, independent microservice** that provides AI-powered command-line interface capabilities using the OpenClaw architecture. It's completely decoupled from the dashboard and can be scaled, deployed, and distributed independently.

### Why Separate Service?

Previously, the CLI was embedded within the dashboard-api container, causing:
- ❌ 13 duplicate implementations (~5,170 lines)
- ❌ Tight coupling with dashboard
- ❌ Shared resources and crashes
- ❌ Impossible to distribute as standalone product

The new architecture provides:
- ✅ Single, clean implementation
- ✅ Process isolation (independent crashes/restarts)
- ✅ Horizontal scalability
- ✅ Standalone distribution
- ✅ 100% OpenClaw intelligence

## Architecture

```
┌─────────────────┐
│  Dashboard API  │  ──HTTP──▶  ┌──────────────────┐
└─────────────────┘              │  Tokio CLI       │
                                 │  Service         │
┌─────────────────┐              │  (Port 8100)     │
│  Frontend       │  ──WS────▶   └────────┬─────────┘
└─────────────────┘                       │
                                          │
                        ┌─────────────────┴──────────────┐
                        │                                │
                        ▼                                ▼
              ┌──────────────────┐           ┌───────────────────┐
              │ OpenClawEngine   │           │  Workspace        │
              │ - Think          │           │  /workspace/cli/  │
              │ - Act            │           │  - SOUL.md        │
              │ - Observe        │           │  - MEMORY.md      │
              │ - Learn          │           │  - CONFIG.json    │
              └─────────┬────────┘           └───────────────────┘
                        │
                        ▼
              ┌──────────────────────────────┐
              │  Tool Executor               │
              │  - Base tools                │
              │  - MCP tools (80+)           │
              │  - Generated tools           │
              └──────────────────────────────┘
```

## OpenClaw Principles

The engine implements the full OpenClaw pattern:

1. **Never Give Up** - Automatic retry with alternatives on failure
2. **Complete Context** - 3000+ character context (no truncation)
3. **Tool Mastery** - Dynamic registry of 80+ tools
4. **Error Learning** - Memory of failures to avoid repeating
5. **Self-Repair** - Auto-fix and recovery capabilities
6. **Workspace Persistence** - SOUL, MEMORY, CONFIG for continuity

## Components

### Core Engine

- **openclaw_engine.py** - Main Think→Act→Observe→Learn loop
- **workspace.py** - SOUL/MEMORY/CONFIG persistence
- **tool_executor.py** - Unified tool execution (base + MCP + generated)
- **mcp_client.py** - JSON-RPC stdio client for MCP server
- **error_learner.py** - Error memory and retry logic
- **context_builder.py** - Full context building (3000+ chars)
- **session_manager.py** - Session lifecycle management
- **job_queue.py** - Async job queue with background workers

### API Layer

- **server.py** - FastAPI application
- **api/models.py** - Pydantic request/response models
- **api/websocket_handler.py** - Interactive WebSocket terminal

## API Endpoints

### REST API

```
POST   /api/cli/jobs          # Create async job
GET    /api/cli/jobs/{id}     # Get job status
GET    /api/cli/sessions      # List sessions
GET    /api/cli/sessions/{id} # Get session details
DELETE /api/cli/sessions/{id} # Delete session
GET    /api/cli/tools         # List available tools
GET    /api/cli/stats         # Service statistics
GET    /health                # Health check
```

### WebSocket

```
WS     /ws/cli                # Interactive terminal
```

**WebSocket Protocol:**

Client → Server:
```json
{"type": "command", "content": "show me blocked IPs"}
```

Server → Client (streaming):
```json
{"type": "progress", "message": "Thinking..."}
{"type": "tool_call", "tool": "bash", "args": {...}}
{"type": "tool_result", "success": true, "output": "..."}
{"type": "done", "result": "..."}
```

## Installation

### 1. Build and Deploy

```bash
# Build service
docker-compose build tokio-cli

# Start service (local profile)
docker-compose --profile local up -d tokio-cli

# Check health
curl http://localhost:8100/health
```

### 2. Environment Variables

```bash
# PostgreSQL
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=soc_ai
POSTGRES_USER=soc_user
POSTGRES_PASSWORD=changeme

# Kafka
KAFKA_BOOTSTRAP_SERVERS=kafka:9092

# LLM
GEMINI_API_KEY=your_key_here
ANTHROPIC_API_KEY=your_key_here  # optional
LLM_PROVIDER=gemini  # or anthropic

# Workspace
TOKIO_WORKSPACE=/workspace/cli

# Logging
LOG_LEVEL=INFO
```

### 3. Verify Installation

```bash
# Health check
curl http://localhost:8100/health

# Get stats
curl http://localhost:8100/api/cli/stats

# List tools
curl http://localhost:8100/api/cli/tools
```

## Usage

### From Dashboard (via CLIClient)

```python
from cli_client import get_cli_client

# Get client
client = get_cli_client()

# Execute command and wait for result
result = await client.execute_and_wait("show me the top 10 blocked IPs")

print(result)
```

### Direct REST API

```bash
# Create job
JOB_ID=$(curl -X POST http://localhost:8100/api/cli/jobs \
  -H "Content-Type: application/json" \
  -d '{"command": "analyze recent incidents"}' \
  | jq -r '.job_id')

# Poll for result
while true; do
  STATUS=$(curl -s http://localhost:8100/api/cli/jobs/$JOB_ID | jq -r '.status')

  if [ "$STATUS" = "completed" ]; then
    curl -s http://localhost:8100/api/cli/jobs/$JOB_ID | jq -r '.result'
    break
  fi

  sleep 1
done
```

### WebSocket Terminal

```javascript
const ws = new WebSocket('ws://localhost:8100/ws/cli');

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);

  if (msg.type === 'welcome') {
    console.log(msg.message);

    // Send command
    ws.send(JSON.stringify({
      type: 'command',
      content: 'list recent security incidents'
    }));
  }

  if (msg.type === 'done') {
    console.log('Result:', msg.result);
  }
};
```

## Workspace Structure

```
/workspace/cli/
├── SOUL.md              # Agent identity and principles
├── MEMORY.md            # Long-term learning storage
├── CONFIG.json          # Configuration
├── tools/               # Generated tools
│   └── custom_tool.py
└── sessions/            # Session transcripts (JSONL)
    └── session-abc123.jsonl
```

## Available Tools

The CLI has access to 80+ tools across three categories:

### Base Tools (Built-in)
- `bash` - Execute bash commands
- `postgres_query` - Query PostgreSQL database
- `docker` - Docker container management

### MCP Tools (80+ via MCP server)
- Database queries and analysis
- Log analysis and pattern detection
- Container and service management
- Security scanning and threat detection
- And many more...

### Generated Tools (Dynamic)
- Custom tools created by the agent
- Saved to workspace/tools/
- Automatically loaded on restart

## Testing

```bash
# Run unit tests
docker-compose exec tokio-cli pytest tests/test_engine.py -v

# Integration tests
docker-compose exec tokio-cli pytest tests/test_integration.py -v

# End-to-end tests
docker-compose exec tokio-cli pytest tests/test_e2e.py -v
```

## Development

### Project Structure

```
tokio-cli/
├── server.py                 # FastAPI application
├── Dockerfile                # Container definition
├── requirements.txt          # Python dependencies
├── engine/                   # Core engine
│   ├── openclaw_engine.py
│   ├── workspace.py
│   ├── tool_executor.py
│   ├── mcp_client.py
│   ├── error_learner.py
│   ├── context_builder.py
│   ├── session_manager.py
│   └── job_queue.py
├── api/                      # API layer
│   ├── models.py
│   └── websocket_handler.py
└── tests/                    # Tests
    ├── test_engine.py
    ├── test_integration.py
    └── test_e2e.py
```

### Adding New Tools

```python
# In engine/tool_executor.py

def _load_custom_tools(self):
    self.registry.register_tool(
        name="my_tool",
        description="Does something useful",
        category="Custom",
        parameters=["arg1", "arg2"],
        executor_func=self._execute_my_tool
    )

async def _execute_my_tool(self, arg1: str, arg2: str) -> str:
    # Implementation
    return f"Result: {arg1} + {arg2}"
```

## Monitoring

### Health Check

```bash
curl http://localhost:8100/health

# Expected response:
{
  "status": "healthy",
  "service": "tokio-cli",
  "version": "3.0.0",
  "components": {
    "engine": "healthy",
    "mcp": "healthy",
    "session_manager": "healthy",
    "job_queue": "healthy"
  }
}
```

### Statistics

```bash
curl http://localhost:8100/api/cli/stats

# Expected response:
{
  "active_sessions": 2,
  "total_sessions": 15,
  "queued_jobs": 0,
  "running_jobs": 1,
  "completed_jobs": 145,
  "failed_jobs": 3,
  "uptime_seconds": 3600.5,
  "mcp_connected": true,
  "total_tools": 85
}
```

### Logs

```bash
# View logs
docker-compose logs tokio-cli -f

# Filter by level
docker-compose logs tokio-cli | grep ERROR
```

## Troubleshooting

### Service Won't Start

```bash
# Check dependencies
docker-compose ps

# Verify PostgreSQL is healthy
docker-compose exec postgres pg_isready

# Verify Kafka is healthy
docker-compose exec kafka kafka-broker-api-versions --bootstrap-server localhost:9092

# Check logs
docker-compose logs tokio-cli --tail 100
```

### MCP Connection Issues

```bash
# Verify MCP server path
docker-compose exec tokio-cli ls -la /app/mcp-core/mcp_server.py

# Check MCP server can run
docker-compose exec tokio-cli python3 /app/mcp-core/mcp_server.py --help
```

### Job Stuck in "pending"

```bash
# Check job queue status
curl http://localhost:8100/api/cli/stats | jq '.queued_jobs, .running_jobs'

# Check if worker is running
docker-compose logs tokio-cli | grep "worker"
```

## Migration from Embedded CLI

If you're migrating from the old embedded CLI:

1. **Update imports** in dashboard-api:
   ```python
   # OLD
   from cli_openclaw_real import OpenClawTokioAgent

   # NEW
   from cli_client import get_cli_client
   ```

2. **Update function calls**:
   ```python
   # OLD
   agent = OpenClawTokioAgent()
   result = agent.process_message(command)

   # NEW
   client = get_cli_client()
   result = await client.execute_and_wait(command)
   ```

3. **Remove old CLI files** (after testing):
   - cli_openclaw_real.py and 12 other variants
   - Total ~5,170 lines of duplicate code

## Performance

- **Startup Time**: ~10-15 seconds
- **Average Response Time**: 2-5 seconds
- **Concurrent Sessions**: 100+ supported
- **Memory Usage**: ~512MB
- **CPU Usage**: <50% during normal operation

## Security

- ✅ Process isolation from dashboard
- ✅ No direct database credentials exposure
- ✅ Tool execution sandboxing
- ✅ Session-based access control
- ✅ Audit logging of all commands

## Future Enhancements

- [ ] Multi-instance deployment with load balancing
- [ ] Redis for distributed session storage
- [ ] Tool execution rate limiting
- [ ] Advanced analytics and reporting
- [ ] Voice command support
- [ ] Multi-language support

## License

Part of Tokio AI v3.0 - SOC AI Lab

## Support

For issues or questions:
- GitHub Issues: [Link to repo]
- Documentation: [Link to docs]
- Community: [Link to community]
