"""
MCP Client - JSON-RPC stdio communication with MCP Server
Provides access to 80+ MCP tools via subprocess communication
"""
import asyncio
import json
import logging
import os
from typing import Dict, List, Optional, Any
from asyncio.subprocess import Process

logger = logging.getLogger(__name__)

class MCPClient:
    """
    Client for communicating with MCP server via JSON-RPC stdio protocol.

    The MCP server is spawned as a subprocess and communication happens via:
    - stdin: Send JSON-RPC requests
    - stdout: Receive JSON-RPC responses
    - stderr: Logging output
    """

    def __init__(self, mcp_server_path: str = "/app/mcp-core/mcp_server.py"):
        self.mcp_server_path = mcp_server_path
        self.process: Optional[Process] = None
        self.request_id = 0
        self.tools_cache: Optional[List[Dict]] = None
        self._initialized = False

    async def connect(self):
        """Start MCP server process and establish stdio connection"""
        if self._initialized:
            logger.debug("MCP client already connected")
            return

        try:
            # Spawn MCP server as subprocess
            self.process = await asyncio.create_subprocess_exec(
                "python3",
                self.mcp_server_path,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={
                    **os.environ,
                    "PYTHONUNBUFFERED": "1"  # Disable buffering
                }
            )

            logger.info(f"🔌 MCP server started (PID: {self.process.pid})")

            # Initialize connection
            await self._initialize_protocol()

            self._initialized = True
            logger.info("✅ MCP client connected")

        except Exception as e:
            logger.error(f"❌ Failed to connect to MCP server: {e}")
            raise

    async def _initialize_protocol(self):
        """
        Send initialize request to MCP server.

        JSON-RPC format:
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {...}}
        """
        request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "tokio-cli",
                    "version": "3.0.0"
                }
            }
        }

        response = await self._send_request(request)

        if "error" in response:
            raise Exception(f"MCP initialization failed: {response['error']}")

        logger.debug("MCP protocol initialized")

    def _next_id(self) -> int:
        """Generate next request ID"""
        self.request_id += 1
        return self.request_id

    async def _send_request(self, request: Dict) -> Dict:
        """
        Send JSON-RPC request and wait for response.

        Args:
            request: JSON-RPC request dict

        Returns:
            JSON-RPC response dict
        """
        if not self.process or not self.process.stdin:
            raise Exception("MCP server not connected")

        try:
            # Send request
            request_data = json.dumps(request) + "\n"
            self.process.stdin.write(request_data.encode())
            await self.process.stdin.drain()

            logger.debug(f"→ MCP Request: {request['method']} (id: {request['id']})")

            # Read response
            response_data = await self.process.stdout.readline()

            if not response_data:
                raise Exception("MCP server closed connection")

            response = json.loads(response_data.decode())

            logger.debug(f"← MCP Response: id {response.get('id')}")

            return response

        except Exception as e:
            logger.error(f"MCP communication error: {e}")
            raise

    async def list_tools(self) -> List[Dict]:
        """
        Get list of all available MCP tools.

        Returns:
            List of tool definitions with name, description, parameters
        """
        # Use cache if available
        if self.tools_cache:
            return self.tools_cache

        request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/list",
            "params": {}
        }

        response = await self._send_request(request)

        if "error" in response:
            logger.error(f"Failed to list MCP tools: {response['error']}")
            return []

        tools = response.get("result", {}).get("tools", [])

        # Cache tools
        self.tools_cache = tools

        logger.info(f"📋 Listed {len(tools)} MCP tools")

        return tools

    async def call_tool(self, name: str, arguments: Dict) -> Dict:
        """
        Call an MCP tool.

        Args:
            name: Tool name
            arguments: Tool arguments dict

        Returns:
            Tool result dict with 'content' or 'error'
        """
        request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments
            }
        }

        logger.debug(f"🔧 Calling MCP tool: {name}")

        response = await self._send_request(request)

        if "error" in response:
            error_msg = response["error"].get("message", "Unknown error")
            logger.error(f"MCP tool {name} failed: {error_msg}")
            return {
                "success": False,
                "error": error_msg
            }

        result = response.get("result", {})

        # Extract content from MCP response format
        content_items = result.get("content", [])

        if not content_items:
            return {
                "success": True,
                "output": ""
            }

        # Combine all content items
        output_parts = []
        for item in content_items:
            if item.get("type") == "text":
                output_parts.append(item.get("text", ""))

        output = "\n".join(output_parts)

        return {
            "success": True,
            "output": output
        }

    async def find_tool(self, name: str) -> Optional[Dict]:
        """Find tool definition by name"""
        tools = await self.list_tools()

        for tool in tools:
            if tool.get("name") == name:
                return tool

        return None

    async def disconnect(self):
        """Close connection to MCP server"""
        if self.process:
            try:
                # Send shutdown (optional)
                # self.process.stdin.close()

                # Terminate process
                self.process.terminate()
                await self.process.wait()

                logger.info("🔌 MCP server disconnected")

            except Exception as e:
                logger.error(f"Error disconnecting MCP server: {e}")

            finally:
                self.process = None
                self._initialized = False

    async def __aenter__(self):
        """Async context manager entry"""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.disconnect()

    def is_connected(self) -> bool:
        """Check if MCP client is connected"""
        return self._initialized and self.process is not None

    async def health_check(self) -> bool:
        """
        Check if MCP server is healthy.

        Returns True if server responds to ping.
        """
        if not self.is_connected():
            return False

        try:
            # Try listing tools as health check
            tools = await self.list_tools()
            return len(tools) > 0

        except Exception as e:
            logger.error(f"MCP health check failed: {e}")
            return False
