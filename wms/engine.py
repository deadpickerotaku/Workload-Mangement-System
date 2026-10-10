"""The engine — the beating heart that ties every module together.

Flow for one job:

  submit()            producer: create Job (NEW) -> persist -> enqueue (QUEUED)
  worker loop         consumer: ask scheduler for next job -> dispatch (RUNNING)
  _run_slice()        simulate CPU burst (a full burst, or one quantum for RR)
  _complete()         acquire API slot -> Gemini + Spotify (mock) ->
                      ACID transaction persists the playlist -> TERMINATED ->
                      log the JOB_EXECUTION metrics
"""
from __future__ import annotations

import threading
import time
from typing import List

import config
from .job_queue import ReadyQueue
from .models import Job, JobState
from .resource_manager import ResourceManager
from .schedulers import Scheduler
from .providers import gemini, spotify


class Engine:
    def __init__(self, database, scheduler: Scheduler,
                 num_workers: int = None, quantum_ms: int = None,
                 api_rate_per_min: int = None):
        self.db = database
        self.scheduler = scheduler
        self.num_workers = num_workers or config.NUM_WORKERS
        self.quantum_ms = quantum_ms or config.RR_QUANTUM_MS
        self.ready = ReadyQueue()
        self.rm = ResourceManager(
            self.num_workers, database, api_rate_per_min or config.API_RATE_PER_MIN
        )

        self._threads: List[threading.Thread] = []
        self._stop = threading.Event()

        # Track outstanding (not-yet-terminated) jobs so we can wait for idle.
        self._active = 0
        self._idle_cv = threading.Condition()

    # ---- lifecycle -------------------------------------------------------
    def start(self) -> None:
        for i in range(self.num_workers):
            t = threading.Thread(target=self._worker, name=f"worker-{i}", daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        self.ready.close()

    def set_scheduler(self, scheduler: Scheduler) -> None:
        self.scheduler = scheduler

    # ---- producer --------------------------------------------------------
    def submit(self, owner: str, request_text: str, priority: int = 5,
               burst_ms: int = 300, user_id: int = 0, tier: str = "FREE") -> Job:
        job = Job(owner=owner, request_text=request_text, priority=priority,
                  burst_ms=burst_ms, user_id=user_id, tier=tier,
                  scheduler_name=self.scheduler.name)
        with self._idle_cv:
            self._active += 1
        self.db.insert_job(job)          # persist as NEW (durability)
        job.on_enqueue()                 # NEW -> QUEUED
        self.db.update_job_state(job)
        self.ready.put(job)
        return job

    # ---- consumer / worker ----------------------------------------------
    def _worker(self) -> None:
        while not self._stop.is_set():
            job = self.ready.get(self.scheduler, timeout=0.3)
            if job is None:
                continue
            try:
                self._run_slice(job)
            except Exception as exc:  # keep the worker alive on any job error
                print(f"[engine] job {job.job_id} failed: {exc}")
                self._finish_active()

    def _run_slice(self, job: Job) -> None:
        with self.rm.worker_slot():
            job.scheduler_name = self.scheduler.name
            job.on_dispatch()            # QUEUED -> RUNNING
            self.db.update_job_state(job)

            if self.scheduler.preemptive:
                slice_ms = min(self.quantum_ms, job.remaining_ms)
            else:
                slice_ms = job.remaining_ms

            time.sleep(slice_ms / 1000.0)  # simulate the CPU/service burst
            job.remaining_ms -= slice_ms
            # Let fair schedulers advance their per-user virtual clock.
            self.scheduler.notify_run(job, slice_ms)

            if job.remaining_ms > 0.5:
                # Round Robin preemption — rotate to the back of the queue.
                job.on_preempt()
                self.db.update_job_state(job)
                self.ready.put(job)
                return

            self._complete(job)

    def _complete(self, job: Job) -> None:
        # External work, through the rate-limited API slot.
        self.rm.api_call()
        attrs = gemini.analyze(job.request_text)
        self.rm.api_call()
        tracks = spotify.search(attrs, n=config.PLAYLIST_SIZE)

        job.on_finish()                  # RUNNING -> TERMINATED
        title = f"{job.request_text.strip()[:40]}"
        job.playlist_id = self.db.save_result(job, title=title, tracks=tracks)
        self.db.insert_execution(job)
        self._finish_active()

    def _finish_active(self) -> None:
        with self._idle_cv:
            self._active -= 1
            if self._active <= 0:
                self._active = 0
                self._idle_cv.notify_all()

    # ---- helpers for the benchmark --------------------------------------
    def wait_idle(self, timeout: float = 60.0) -> bool:
        deadline = time.time() + timeout
        with self._idle_cv:
            while self._active > 0:
                remaining = deadline - time.time()
                if remaining <= 0:
                    return False
                self._idle_cv.wait(remaining)
        return True
