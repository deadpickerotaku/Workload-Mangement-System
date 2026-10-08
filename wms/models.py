"""Core data model: the Job and its lifecycle, mirroring an OS process.

A Job moves through the classic process states:

    NEW  --enqueue-->  QUEUED  --dispatch-->  RUNNING  --finish-->  TERMINATED
                          ^                        |
                          +----- preempt (RR) -----+

All timestamps are wall-clock milliseconds so we can derive the standard
scheduling metrics (waiting / turnaround / response time).
"""
from __future__ import annotations

import itertools
import threading
import time
from dataclasses import dataclass, field
from enum import Enum


class JobState(str, Enum):
    NEW = "NEW"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    TERMINATED = "TERMINATED"


_id_counter = itertools.count(1)
_id_lock = threading.Lock()


def next_job_id() -> int:
    with _id_lock:
        return next(_id_counter)


def seed_job_ids(start: int) -> None:
    """Resume the ID sequence above IDs already persisted, so job_ids stay
    unique across process restarts (the DB file outlives the process)."""
    global _id_counter
    with _id_lock:
        _id_counter = itertools.count(max(1, start))


def now_ms() -> float:
    return time.time() * 1000.0


@dataclass
class Job:
    owner: str
    request_text: str
    priority: int = 5          # lower number = higher priority
    burst_ms: int = 300        # estimated total service time
    user_id: int = 0           # owning user (for multi-tenant fair scheduling)
    tier: str = "FREE"         # FREE | PREMIUM
    job_id: int = field(default_factory=next_job_id)

    state: JobState = JobState.NEW
    scheduler_name: str = "FCFS"

    # Remaining service time — decremented as the job runs (matters for RR/SJF).
    remaining_ms: float = field(default=None)  # type: ignore

    created_at: float = field(default_factory=now_ms)
    first_enqueued_at: float = None   # arrival into the ready queue
    last_enqueued_at: float = None    # most recent enqueue (RR rotation)
    started_at: float = None          # first time it got the CPU
    finished_at: float = None

    # Accumulated time spent waiting in the ready queue (handles RR re-queues).
    waiting_accum_ms: float = 0.0

    playlist_id: int = None

    def __post_init__(self):
        if self.remaining_ms is None:
            self.remaining_ms = float(self.burst_ms)

    # ---- lifecycle transitions ------------------------------------------
    def on_enqueue(self) -> None:
        t = now_ms()
        if self.first_enqueued_at is None:
            self.first_enqueued_at = t
        self.last_enqueued_at = t
        self.state = JobState.QUEUED

    def on_dispatch(self) -> float:
        t = now_ms()
        self.waiting_accum_ms += t - self.last_enqueued_at
        if self.started_at is None:
            self.started_at = t
        self.state = JobState.RUNNING
        return t

    def on_preempt(self) -> None:
        self.last_enqueued_at = now_ms()
        self.state = JobState.QUEUED

    def on_finish(self) -> None:
        self.finished_at = now_ms()
        self.state = JobState.TERMINATED

    # ---- classic scheduling metrics (milliseconds) ----------------------
    @property
    def response_ms(self) -> float:
        return self.started_at - self.first_enqueued_at

    @property
    def turnaround_ms(self) -> float:
        return self.finished_at - self.first_enqueued_at

    @property
    def waiting_ms(self) -> float:
        return self.waiting_accum_ms
