"""The in-memory ready queue plus the Producer that feeds it.

This is the seam that decouples job *intake* from job *execution*: producers
drop jobs in, worker (consumer) threads pull the next one out according to the
active scheduling strategy. It is fully thread-safe.
"""
from __future__ import annotations

import threading
from typing import List, Optional

from .models import Job
from .schedulers import Scheduler


class ReadyQueue:
    def __init__(self):
        self._jobs: List[Job] = []
        self._cv = threading.Condition()
        self._closed = False

    def put(self, job: Job) -> None:
        """Producer side — add a QUEUED job to the ready queue."""
        with self._cv:
            self._jobs.append(job)
            self._cv.notify()

    def get(self, scheduler: Scheduler, timeout: float = 0.3) -> Optional[Job]:
        """Consumer side — block until a job is available, then hand back the
        one the scheduler selects. Returns None on timeout (so callers can
        re-check a stop flag) or when the queue is closed and drained."""
        with self._cv:
            if not self._jobs:
                if self._closed:
                    return None
                self._cv.wait(timeout)
                if not self._jobs:
                    return None
            idx = scheduler.select(self._jobs)
            return self._jobs.pop(idx)

    def close(self) -> None:
        with self._cv:
            self._closed = True
            self._cv.notify_all()

    def __len__(self) -> int:
        with self._cv:
            return len(self._jobs)
