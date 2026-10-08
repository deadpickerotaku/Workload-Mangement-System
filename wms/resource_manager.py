"""The Resource Manager: gate-keeps the three scarce resources a running job
needs — a worker slot (CPU), a pooled DB connection, and an external-API slot
(rate limited) — so that no single job can starve the others.
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager


class RateLimiter:
    """Token-bucket limiter for the external (mock/real) music + AI APIs."""

    def __init__(self, per_minute: int):
        self.capacity = max(1, per_minute)
        self.tokens = float(self.capacity)
        self.refill_per_sec = self.capacity / 60.0
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                self.tokens = min(
                    self.capacity, self.tokens + (now - self._last) * self.refill_per_sec
                )
                self._last = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
            time.sleep(0.01)


class ResourceManager:
    def __init__(self, num_workers: int, database, api_rate_per_min: int):
        # A counting semaphore representing available CPU/worker slots.
        self.worker_slots = threading.Semaphore(num_workers)
        # The pooled DB connections live in the Database object.
        self.database = database
        # Rate-limited slot for external API calls.
        self.api = RateLimiter(api_rate_per_min)

    @contextmanager
    def worker_slot(self):
        self.worker_slots.acquire()
        try:
            yield
        finally:
            self.worker_slots.release()

    @contextmanager
    def db_connection(self):
        conn = self.database.get_conn()
        try:
            yield conn
        finally:
            self.database.put_conn(conn)

    def api_call(self):
        """Block until a rate-limit token is available, then proceed."""
        self.api.acquire()
