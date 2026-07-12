from collections import deque
from dataclasses import dataclass
from enum import Enum


class JobState(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class QueuedJob:
    job_id: str
    state: JobState = JobState.PENDING
    retries: int = 0
    error: str | None = None


class FileJobQueue:
    def __init__(self, max_retries=2):
        if max_retries < 0:
            raise ValueError("max retries cannot be negative")
        self.max_retries = max_retries
        self._pending = deque()
        self.active = None

    def submit(self, job_id):
        if self.active and self.active.job_id == job_id:
            raise ValueError("job ID is already queued")
        if any(job.job_id == job_id for job in self._pending):
            raise ValueError("job ID is already queued")
        job = QueuedJob(job_id)
        self._pending.append(job)
        return job

    def start_next(self):
        if self.active is not None:
            return self.active
        if not self._pending:
            return None
        self.active = self._pending.popleft()
        self.active.state = JobState.ACTIVE
        return self.active

    def complete_active(self):
        if self.active is None:
            raise RuntimeError("there is no active job")
        completed = self.active
        completed.state = JobState.COMPLETED
        self.active = None
        return completed

    def fail_active(self, error):
        if self.active is None:
            raise RuntimeError("there is no active job")
        failed = self.active
        self.active = None
        failed.retries += 1
        failed.error = error
        if failed.retries <= self.max_retries:
            failed.state = JobState.PENDING
            self._pending.appendleft(failed)
        else:
            failed.state = JobState.FAILED
        return failed

    def cancel(self, job_id):
        if self.active and self.active.job_id == job_id:
            cancelled = self.active
            self.active = None
            cancelled.state = JobState.CANCELLED
            return cancelled
        for job in self._pending:
            if job.job_id == job_id:
                self._pending.remove(job)
                job.state = JobState.CANCELLED
                return job
        raise KeyError(job_id)

    def note_clipboard_changed(self):
        """Clipboard changes intentionally have no effect on initiated jobs."""
