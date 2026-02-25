"""
Job Queue - Async job queue for background CLI command execution
"""
import asyncio
import logging
from datetime import datetime
from typing import Dict, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

class JobStatus(Enum):
    """Job status enumeration"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

@dataclass
class Job:
    """Background job"""
    job_id: str
    command: str
    session_id: Optional[str] = None
    status: JobStatus = JobStatus.PENDING
    result: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    iterations_used: int = 0
    max_iterations: int = 10
    timeout: int = 300

    def get_execution_time(self) -> Optional[float]:
        """Get execution time in seconds"""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

class JobQueue:
    """Manages async job queue"""

    def __init__(self):
        self.jobs: Dict[str, Job] = {}
        self.queue: asyncio.Queue = asyncio.Queue()
        self.worker_task: Optional[asyncio.Task] = None
        self._running = False

    async def start_worker(self, executor_func: Callable):
        """
        Start background worker to process jobs.

        Args:
            executor_func: Async function to execute jobs (job_id, job) -> result
        """
        if self._running:
            logger.warning("Job queue worker already running")
            return

        self._running = True
        self.worker_task = asyncio.create_task(self._worker_loop(executor_func))

        logger.info("⚙️ Job queue worker started")

    async def _worker_loop(self, executor_func: Callable):
        """Background worker loop"""
        logger.info("🔄 Job queue worker loop started")

        while self._running:
            try:
                # Get job from queue (with timeout to allow checking _running flag)
                try:
                    job_id = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                job = self.jobs.get(job_id)

                if not job:
                    logger.error(f"Job {job_id} not found in registry")
                    continue

                # Update status
                job.status = JobStatus.RUNNING
                job.started_at = datetime.now()

                logger.info(f"▶️ Processing job: {job_id}")

                try:
                    # Execute job
                    result = await executor_func(job_id, job)

                    # Update with result
                    job.status = JobStatus.COMPLETED
                    job.result = result
                    job.completed_at = datetime.now()

                    logger.info(f"✅ Job completed: {job_id} ({job.get_execution_time():.2f}s)")

                except Exception as e:
                    logger.error(f"❌ Job failed [{job_id}]: {e}")
                    job.status = JobStatus.FAILED
                    job.error = str(e)
                    job.completed_at = datetime.now()

                finally:
                    self.queue.task_done()

            except Exception as e:
                logger.error(f"Worker loop error: {e}")
                await asyncio.sleep(1)

        logger.info("🛑 Job queue worker loop stopped")

    def submit_job(self, job: Job) -> str:
        """
        Submit a job to the queue.

        Returns:
            job_id
        """
        # Register job
        self.jobs[job.job_id] = job

        # Add to queue
        self.queue.put_nowait(job.job_id)

        logger.info(f"📝 Job submitted: {job.job_id} - {job.command[:50]}")

        return job.job_id

    def get_job(self, job_id: str) -> Optional[Job]:
        """Get job by ID"""
        return self.jobs.get(job_id)

    def list_jobs(
        self,
        status: Optional[JobStatus] = None,
        session_id: Optional[str] = None
    ) -> list[Job]:
        """
        List jobs with optional filters.

        Args:
            status: Filter by status
            session_id: Filter by session

        Returns:
            List of matching jobs
        """
        jobs = list(self.jobs.values())

        if status:
            jobs = [j for j in jobs if j.status == status]

        if session_id:
            jobs = [j for j in jobs if j.session_id == session_id]

        return jobs

    def get_queue_size(self) -> int:
        """Get number of jobs in queue"""
        return self.queue.qsize()

    def get_stats(self) -> Dict:
        """Get queue statistics"""
        return {
            "total_jobs": len(self.jobs),
            "queued": len([j for j in self.jobs.values() if j.status == JobStatus.PENDING]),
            "running": len([j for j in self.jobs.values() if j.status == JobStatus.RUNNING]),
            "completed": len([j for j in self.jobs.values() if j.status == JobStatus.COMPLETED]),
            "failed": len([j for j in self.jobs.values() if j.status == JobStatus.FAILED]),
            "queue_size": self.queue.qsize()
        }

    async def cancel_job(self, job_id: str) -> bool:
        """
        Cancel a pending job.

        Note: Cannot cancel running jobs.
        """
        job = self.get_job(job_id)

        if not job:
            return False

        if job.status == JobStatus.PENDING:
            job.status = JobStatus.CANCELLED
            logger.info(f"🚫 Job cancelled: {job_id}")
            return True

        logger.warning(f"Cannot cancel job {job_id} with status {job.status}")
        return False

    async def stop_worker(self):
        """Stop background worker"""
        if not self._running:
            return

        logger.info("🛑 Stopping job queue worker...")

        self._running = False

        if self.worker_task:
            # Wait for current job to complete
            await asyncio.sleep(2)

            # Cancel worker task
            self.worker_task.cancel()

            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass

        logger.info("✅ Job queue worker stopped")

    async def cleanup(self):
        """Cleanup on shutdown"""
        await self.stop_worker()
        logger.info(f"🧹 Job queue cleaned up ({len(self.jobs)} jobs total)")
