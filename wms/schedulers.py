"""The OS Scheduler: interchangeable CPU-scheduling strategies.

Two families:

* Classic single-metric schedulers — FCFS, SJF, Priority, Round Robin.
* Multi-tenant fair schedulers — FairShare and WFQ (Weighted Fair Queuing) —
  which share a scarce resource *fairly across users* rather than per job, so no
  single user can monopolize the external-API budget. WFQ additionally weights
  each user by their service tier (PREMIUM gets more than FREE).

Every scheduler answers one question in `select`: given the jobs in the ready
queue, which index runs next? Fair schedulers also implement `notify_run`, which
the engine calls after a job runs so the scheduler can advance its bookkeeping.
"""
from __future__ import annotations

from typing import Callable, List

from .models import Job


class Scheduler:
    name = "BASE"
    preemptive = False

    def select(self, jobs: List[Job]) -> int:
        raise NotImplementedError

    def notify_run(self, job: Job, amount_ms: float) -> None:
        """Hook: the engine calls this after `job` ran for `amount_ms`.
        Stateless schedulers ignore it; fair schedulers use it."""
        pass


# --------------------------------------------------------------------------
# Classic schedulers
# --------------------------------------------------------------------------
class FCFS(Scheduler):
    """First-Come, First-Served — earliest arrival runs first."""
    name = "FCFS"

    def select(self, jobs: List[Job]) -> int:
        return min(range(len(jobs)), key=lambda i: jobs[i].first_enqueued_at)


class SJF(Scheduler):
    """Shortest Job First — smallest remaining service time runs first."""
    name = "SJF"

    def select(self, jobs: List[Job]) -> int:
        return min(range(len(jobs)),
                   key=lambda i: (jobs[i].remaining_ms, jobs[i].first_enqueued_at))


class Priority(Scheduler):
    """Priority scheduling — lowest priority number first (ties: FCFS)."""
    name = "Priority"

    def select(self, jobs: List[Job]) -> int:
        return min(range(len(jobs)),
                   key=lambda i: (jobs[i].priority, jobs[i].first_enqueued_at))


class RoundRobin(Scheduler):
    """Round Robin — each job runs one quantum, then rotates to the back."""
    name = "RoundRobin"
    preemptive = True

    def __init__(self, quantum_ms: int = 150):
        self.quantum_ms = quantum_ms

    def select(self, jobs: List[Job]) -> int:
        return min(range(len(jobs)), key=lambda i: jobs[i].last_enqueued_at)


# --------------------------------------------------------------------------
# Multi-tenant fair schedulers
# --------------------------------------------------------------------------
class WeightedFair(Scheduler):
    """Weighted Fair Queuing (virtual-time / GPS approximation).

    Each user has a virtual clock. We always run a job of the user with the
    smallest virtual time, then advance that user's clock by
    `served_time / weight`. Higher-weight (PREMIUM) users advance more slowly and
    are therefore served more often — a smooth, starvation-free way to divide a
    shared resource in proportion to tier. Preemptive at the quantum level so
    fairness holds even for long jobs.
    """
    name = "WFQ"
    preemptive = True

    def __init__(self, weight_fn: Callable[[int], float], quantum_ms: int = 150,
                 weighted: bool = True):
        self.weight_fn = weight_fn
        self.quantum_ms = quantum_ms
        self.weighted = weighted
        self.vtime: dict[int, float] = {}

    def select(self, jobs: List[Job]) -> int:
        active = {j.user_id for j in jobs}
        known = [self.vtime[u] for u in active if u in self.vtime]
        base = min(known) if known else 0.0
        # A newly-active user joins at the current front (no unfair head start,
        # no penalty for having been idle).
        for u in active:
            self.vtime.setdefault(u, base)
        return min(range(len(jobs)),
                   key=lambda i: (self.vtime[jobs[i].user_id],
                                  jobs[i].first_enqueued_at))

    def notify_run(self, job: Job, amount_ms: float) -> None:
        weight = self.weight_fn(job.user_id) if self.weighted else 1.0
        weight = max(1e-6, weight)
        self.vtime[job.user_id] = self.vtime.get(job.user_id, 0.0) + amount_ms / weight


class FairShare(WeightedFair):
    """Fair-share scheduling — WFQ with equal weights, i.e. every user gets the
    same share of the resource regardless of tier or how many jobs they queue."""
    name = "FairShare"

    def __init__(self, quantum_ms: int = 150):
        super().__init__(weight_fn=lambda _uid: 1.0, quantum_ms=quantum_ms,
                         weighted=False)


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------
def build(name: str, quantum_ms: int = 150,
          weight_fn: Callable[[int], float] = None) -> Scheduler:
    key = (name or "").lower()
    if key in ("fcfs", "fifo"):
        return FCFS()
    if key in ("sjf", "sjn", "shortest"):
        return SJF()
    if key in ("priority", "prio"):
        return Priority()
    if key in ("roundrobin", "round_robin", "rr"):
        return RoundRobin(quantum_ms)
    if key in ("fairshare", "fair", "fair_share"):
        return FairShare(quantum_ms)
    if key in ("wfq", "weightedfair", "weighted_fair"):
        if weight_fn is None:
            raise ValueError("WFQ requires a weight_fn")
        return WeightedFair(weight_fn, quantum_ms)
    raise ValueError(f"Unknown scheduler: {name!r}")


# Classic set (single-user comparison) and fair set (multi-user comparison).
CLASSIC_SCHEDULERS = ["FCFS", "SJF", "Priority", "RoundRobin"]
FAIR_SCHEDULERS = ["FairShare", "WFQ"]
ALL_SCHEDULERS = CLASSIC_SCHEDULERS + FAIR_SCHEDULERS
