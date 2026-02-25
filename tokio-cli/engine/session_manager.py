"""
Session Manager - Manages CLI session lifecycle and state
"""
import logging
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

@dataclass
class Session:
    """CLI Session"""
    session_id: str
    created_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)
    messages: List[Dict] = field(default_factory=list)
    active: bool = True
    metadata: Dict = field(default_factory=dict)

    def add_message(self, role: str, content: str, **kwargs):
        """Add message to session history"""
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            **kwargs
        }
        self.messages.append(message)
        self.last_activity = datetime.now()

    def get_message_count(self) -> int:
        """Get total message count"""
        return len(self.messages)

    def get_conversation_history(self, max_messages: Optional[int] = None) -> List[Dict]:
        """
        Get conversation history.

        Args:
            max_messages: Optional limit on number of messages (most recent)

        Returns:
            List of messages
        """
        if max_messages:
            return self.messages[-max_messages:]
        return self.messages

class SessionManager:
    """Manages multiple CLI sessions"""

    def __init__(self, workspace):
        self.workspace = workspace
        self.sessions: Dict[str, Session] = {}

    def create_session(self, session_id: Optional[str] = None) -> Session:
        """Create a new session"""
        if not session_id:
            import uuid
            session_id = f"session-{uuid.uuid4().hex[:8]}"

        # Check if session already exists
        if session_id in self.sessions:
            logger.warning(f"Session {session_id} already exists, returning existing")
            return self.sessions[session_id]

        session = Session(session_id=session_id)
        self.sessions[session_id] = session

        logger.info(f"📝 Session created: {session_id}")

        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """Get session by ID"""
        return self.sessions.get(session_id)

    def get_or_create_session(self, session_id: Optional[str] = None) -> Session:
        """Get existing session or create new one"""
        if session_id and session_id in self.sessions:
            return self.sessions[session_id]

        return self.create_session(session_id)

    def delete_session(self, session_id: str) -> bool:
        """Delete a session"""
        if session_id not in self.sessions:
            return False

        # Save session log before deleting
        session = self.sessions[session_id]
        self.workspace.save_session_log(session_id, session.messages)

        # Mark inactive
        session.active = False

        logger.info(f"🗑️ Session deleted: {session_id}")

        return True

    def list_sessions(self, active_only: bool = False) -> List[Session]:
        """List all sessions"""
        sessions = list(self.sessions.values())

        if active_only:
            sessions = [s for s in sessions if s.active]

        return sessions

    def get_active_count(self) -> int:
        """Get count of active sessions"""
        return len([s for s in self.sessions.values() if s.active])

    def cleanup_inactive_sessions(self, max_age_hours: int = 24):
        """
        Clean up old inactive sessions.

        Args:
            max_age_hours: Delete sessions inactive for more than this many hours
        """
        from datetime import timedelta

        now = datetime.now()
        cutoff = now - timedelta(hours=max_age_hours)

        to_delete = []

        for session_id, session in self.sessions.items():
            if not session.active and session.last_activity < cutoff:
                to_delete.append(session_id)

        for session_id in to_delete:
            # Save log
            session = self.sessions[session_id]
            self.workspace.save_session_log(session_id, session.messages)

            # Delete
            del self.sessions[session_id]
            logger.info(f"🧹 Cleaned up old session: {session_id}")

        if to_delete:
            logger.info(f"🧹 Cleaned up {len(to_delete)} inactive sessions")

    async def cleanup(self):
        """Cleanup all sessions on shutdown"""
        logger.info("🧹 Cleaning up all sessions...")

        for session_id, session in self.sessions.items():
            # Save logs
            self.workspace.save_session_log(session_id, session.messages)

        logger.info(f"✅ Saved {len(self.sessions)} session logs")
