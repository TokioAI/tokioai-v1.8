"""
CLI Client - HTTP client for communicating with tokio-cli service

This client replaces the embedded CLI implementations and delegates
all CLI operations to the separate tokio-cli microservice.
"""
import os
import time
import logging
import asyncio
from typing import Dict, Optional, List
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

class CLIClient:
    """
    HTTP client for tokio-cli service.

    Provides async methods to:
    - Execute CLI commands
    - Check job status
    - Wait for job completion
    - List sessions
    - Get service stats
    """

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or os.getenv("CLI_SERVICE_URL", "http://tokio-cli:8100")
        self.client = httpx.AsyncClient(timeout=60.0)

        logger.info(f"🔌 CLI Client initialized: {self.base_url}")

    async def execute_command(
        self,
        command: str,
        session_id: Optional[str] = None,
        max_iterations: int = 10,
        timeout: int = 300
    ) -> Dict:
        """
        Execute a CLI command asynchronously.

        Args:
            command: Command to execute
            session_id: Optional session ID for context
            max_iterations: Max OpenClaw iterations
            timeout: Timeout in seconds

        Returns:
            Dict with job_id, status, etc.
        """
        try:
            response = await self.client.post(
                f"{self.base_url}/api/cli/jobs",
                json={
                    "command": command,
                    "session_id": session_id,
                    "max_iterations": max_iterations,
                    "timeout": timeout
                }
            )

            response.raise_for_status()

            job_data = response.json()

            logger.info(f"📝 Job created: {job_data['job_id']}")

            return job_data

        except httpx.HTTPError as e:
            logger.error(f"Failed to execute command: {e}")
            raise Exception(f"CLI service error: {str(e)}")

    async def get_job_status(self, job_id: str) -> Dict:
        """
        Get job status and result.

        Args:
            job_id: Job ID to check

        Returns:
            Dict with status, result, error, etc.
        """
        try:
            response = await self.client.get(f"{self.base_url}/api/cli/jobs/{job_id}")

            response.raise_for_status()

            return response.json()

        except httpx.HTTPError as e:
            logger.error(f"Failed to get job status: {e}")
            raise Exception(f"CLI service error: {str(e)}")

    async def wait_for_job(
        self,
        job_id: str,
        timeout: int = 300,
        poll_interval: float = 1.0
    ) -> Dict:
        """
        Wait for job to complete.

        Args:
            job_id: Job ID to wait for
            timeout: Max wait time in seconds
            poll_interval: Polling interval in seconds

        Returns:
            Final job status dict

        Raises:
            TimeoutError: If job doesn't complete within timeout
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            status = await self.get_job_status(job_id)

            if status["status"] in ["completed", "failed", "cancelled"]:
                logger.info(f"✅ Job {job_id} finished: {status['status']}")
                return status

            logger.debug(f"⏳ Job {job_id} still running...")
            await asyncio.sleep(poll_interval)

        raise TimeoutError(f"Job {job_id} did not complete within {timeout}s")

    async def execute_and_wait(
        self,
        command: str,
        session_id: Optional[str] = None,
        timeout: int = 300
    ) -> str:
        """
        Execute command and wait for result.

        Convenience method that combines execute_command() and wait_for_job().

        Args:
            command: Command to execute
            session_id: Optional session ID
            timeout: Total timeout in seconds

        Returns:
            Command result string

        Raises:
            Exception: If execution fails or times out
        """
        # Create job
        job = await self.execute_command(command, session_id, timeout=timeout)

        # Wait for completion
        result = await self.wait_for_job(job["job_id"], timeout=timeout)

        # Check status
        if result["status"] == "completed":
            return result.get("result", "")

        elif result["status"] == "failed":
            error = result.get("error", "Unknown error")
            raise Exception(f"CLI command failed: {error}")

        else:
            raise Exception(f"CLI command ended with unexpected status: {result['status']}")

    async def list_sessions(self, active_only: bool = False) -> List[Dict]:
        """
        List all CLI sessions.

        Args:
            active_only: If True, only return active sessions

        Returns:
            List of session dicts
        """
        try:
            params = {"active_only": active_only} if active_only else {}

            response = await self.client.get(
                f"{self.base_url}/api/cli/sessions",
                params=params
            )

            response.raise_for_status()

            return response.json()

        except httpx.HTTPError as e:
            logger.error(f"Failed to list sessions: {e}")
            return []

    async def get_session(self, session_id: str) -> Optional[Dict]:
        """
        Get session details.

        Args:
            session_id: Session ID

        Returns:
            Session dict or None if not found
        """
        try:
            response = await self.client.get(f"{self.base_url}/api/cli/sessions/{session_id}")

            response.raise_for_status()

            return response.json()

        except httpx.HTTPError as e:
            logger.error(f"Failed to get session: {e}")
            return None

    async def delete_session(self, session_id: str) -> bool:
        """
        Delete a session.

        Args:
            session_id: Session ID to delete

        Returns:
            True if deleted successfully
        """
        try:
            response = await self.client.delete(f"{self.base_url}/api/cli/sessions/{session_id}")

            response.raise_for_status()

            return True

        except httpx.HTTPError as e:
            logger.error(f"Failed to delete session: {e}")
            return False

    async def get_stats(self) -> Dict:
        """
        Get CLI service statistics.

        Returns:
            Stats dict with active sessions, jobs, uptime, etc.
        """
        try:
            response = await self.client.get(f"{self.base_url}/api/cli/stats")

            response.raise_for_status()

            return response.json()

        except httpx.HTTPError as e:
            logger.error(f"Failed to get stats: {e}")
            return {}

    async def get_tools(self) -> List[Dict]:
        """
        List all available CLI tools.

        Returns:
            List of tool dicts with name, description, category, parameters
        """
        try:
            response = await self.client.get(f"{self.base_url}/api/cli/tools")

            response.raise_for_status()

            data = response.json()

            return data.get("tools", [])

        except httpx.HTTPError as e:
            logger.error(f"Failed to get tools: {e}")
            return []

    async def health_check(self) -> Dict:
        """
        Check CLI service health.

        Returns:
            Health status dict
        """
        try:
            response = await self.client.get(f"{self.base_url}/health")

            response.raise_for_status()

            return response.json()

        except httpx.HTTPError as e:
            logger.error(f"Health check failed: {e}")
            return {"status": "unhealthy", "error": str(e)}

    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()

    async def __aenter__(self):
        """Async context manager entry"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()


# Global singleton instance
_cli_client: Optional[CLIClient] = None

def get_cli_client() -> CLIClient:
    """
    Get global CLI client instance.

    Returns:
        CLIClient singleton
    """
    global _cli_client

    if _cli_client is None:
        _cli_client = CLIClient()

    return _cli_client


# ============================================================================
# Convenience Functions (for backward compatibility with old CLI code)
# ============================================================================

async def execute_cli_command(command: str, session_id: Optional[str] = None) -> str:
    """
    Execute CLI command and return result.

    Convenience function for simple use cases.

    Args:
        command: Command to execute
        session_id: Optional session ID

    Returns:
        Command result string
    """
    client = get_cli_client()

    return await client.execute_and_wait(command, session_id)
