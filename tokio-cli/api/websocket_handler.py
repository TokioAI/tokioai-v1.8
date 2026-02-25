"""
WebSocket Handler - Interactive CLI terminal via WebSocket
"""
import logging
import asyncio
from datetime import datetime
from typing import Optional, Callable

from fastapi import WebSocket, WebSocketDisconnect

from .models import WSMessage, WSResponse

logger = logging.getLogger(__name__)

class WebSocketHandler:
    """
    Handles WebSocket connections for interactive CLI terminal.

    Protocol:
    - Client sends: {"type": "command", "content": "show me blocked IPs"}
    - Server streams:
        - {"type": "progress", "message": "Thinking..."}
        - {"type": "tool_call", "tool": "bash", "args": {...}}
        - {"type": "tool_result", "tool": "bash", "success": true, "output": "..."}
        - {"type": "done", "result": "..."}
    """

    def __init__(self, engine, session_manager):
        self.engine = engine
        self.session_manager = session_manager

    async def handle_connection(self, websocket: WebSocket):
        """
        Handle a new WebSocket connection.

        Args:
            websocket: FastAPI WebSocket connection
        """
        await websocket.accept()

        import uuid
        session_id = f"ws-{uuid.uuid4().hex[:8]}"

        logger.info(f"🔌 WebSocket connected: {session_id}")

        # Create session
        session = self.session_manager.create_session(session_id)

        # Send welcome message
        await self._send_message(websocket, WSResponse(
            type="welcome",
            session_id=session_id,
            message="🤖 Tokio CLI Agent ready. Type your command or 'help' for assistance."
        ))

        try:
            # Message loop
            while session.active:
                # Receive message
                try:
                    data = await websocket.receive_json()
                    ws_message = WSMessage(**data)

                except Exception as e:
                    logger.error(f"Invalid message format: {e}")
                    await self._send_error(websocket, "Invalid message format")
                    continue

                # Handle message based on type
                if ws_message.type == "command":
                    await self._handle_command(websocket, session, ws_message.content)

                elif ws_message.type == "cancel":
                    await self._handle_cancel(websocket, session, ws_message.job_id)

                elif ws_message.type == "status":
                    await self._handle_status(websocket, session)

                else:
                    logger.warning(f"Unknown message type: {ws_message.type}")
                    await self._send_error(websocket, f"Unknown message type: {ws_message.type}")

        except WebSocketDisconnect:
            logger.info(f"🔌 WebSocket disconnected: {session_id}")

        except Exception as e:
            logger.error(f"❌ WebSocket error [{session_id}]: {e}")

            try:
                await self._send_error(websocket, str(e))
            except:
                pass

        finally:
            # Mark session inactive
            session.active = False
            logger.info(f"🔌 WebSocket session closed: {session_id}")

    async def _handle_command(
        self,
        websocket: WebSocket,
        session,
        command: Optional[str]
    ):
        """Handle command execution"""
        if not command or not command.strip():
            await self._send_error(websocket, "Empty command")
            return

        command = command.strip()

        # Add to session history
        session.add_message("user", command)

        logger.info(f"💬 [{session.session_id}] Command: {command[:50]}")

        # Send acknowledgment
        await self._send_message(websocket, WSResponse(
            type="progress",
            message=f"Executing: {command}"
        ))

        # Stream callback for engine
        async def stream_callback(update: dict):
            """Called by engine to stream updates"""
            await self._send_message(websocket, WSResponse(**update))

        # Execute command with OpenClaw engine
        try:
            result = await self.engine.process_message(
                message=command,
                conversation_history=session.get_conversation_history(),
                max_iterations=10,
                stream_callback=stream_callback,
                session_id=session.session_id
            )

            # Add result to session
            session.add_message("assistant", result)

            # Send final result
            await self._send_message(websocket, WSResponse(
                type="done",
                result=result
            ))

        except Exception as e:
            logger.error(f"Command execution failed: {e}")
            await self._send_error(websocket, f"Execution failed: {str(e)}")

    async def _handle_cancel(
        self,
        websocket: WebSocket,
        session,
        job_id: Optional[str]
    ):
        """Handle job cancellation (not implemented for WebSocket)"""
        await self._send_message(websocket, WSResponse(
            type="error",
            error="Cancellation not supported in WebSocket mode"
        ))

    async def _handle_status(self, websocket: WebSocket, session):
        """Handle status request"""
        await self._send_message(websocket, WSResponse(
            type="output",
            message=f"Session: {session.session_id}\nMessages: {session.get_message_count()}\nActive: {session.active}"
        ))

    async def _send_message(self, websocket: WebSocket, response: WSResponse):
        """Send WSResponse to client"""
        try:
            await websocket.send_json(response.dict(exclude_none=True))
        except Exception as e:
            logger.error(f"Failed to send WebSocket message: {e}")
            raise

    async def _send_error(self, websocket: WebSocket, error: str):
        """Send error message"""
        await self._send_message(websocket, WSResponse(
            type="error",
            error=error
        ))
