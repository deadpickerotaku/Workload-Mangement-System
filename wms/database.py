"""The DBMS layer.

Owns a small pool of connections and exposes typed operations over the five
normalized tables. The key DBMS concept on display is the ACID transaction in
`save_result`: a playlist, its tracks, and the join rows are all written (and
the JOB row updated) atomically — either everything commits or everything rolls
back. Works against SQLite (default) or MySQL via a paramstyle swap.
"""
from __future__ import annotations

import os
import queue
import threading
from typing import List, Optional

import config
from .models import Job

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Database:
    def __init__(self):
        self.backend = config.DB_BACKEND
        # SQLite serializes writers, so we guard writes with a single lock to
        # avoid "database is locked" under concurrent workers.
        self._write_lock = threading.Lock()
        self._pool: "queue.Queue" = queue.Queue()

        if self.backend == "sqlite":
            import sqlite3
            self.ph = "?"                       # parameter placeholder
            self._sqlite3 = sqlite3
            for _ in range(config.DB_POOL_SIZE):
                conn = sqlite3.connect(
                    config.SQLITE_PATH, check_same_thread=False, timeout=30
                )
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA foreign_keys=ON")
                self._pool.put(conn)
        elif self.backend == "mysql":
            import mysql.connector
            self.ph = "%s"
            for _ in range(config.DB_POOL_SIZE):
                self._pool.put(mysql.connector.connect(**config.MYSQL))
        else:
            raise ValueError(f"Unknown DB backend: {self.backend!r}")

    # ---- connection pool -------------------------------------------------
    def get_conn(self):
        return self._pool.get()

    def put_conn(self, conn) -> None:
        self._pool.put(conn)

    def _q(self, sql: str) -> str:
        """Swap the '?' placeholders in our SQL for the backend's style."""
        return sql if self.ph == "?" else sql.replace("?", self.ph)

    # ---- schema ----------------------------------------------------------
    def init_schema(self) -> None:
        fname = "schema_sqlite.sql" if self.backend == "sqlite" else "schema_mysql.sql"
        with open(os.path.join(_HERE, "db", fname), "r", encoding="utf-8") as f:
            sql = f.read()
        conn = self.get_conn()
        try:
            if self.backend == "sqlite":
                conn.executescript(sql)
            else:
                cur = conn.cursor()
                for stmt in [s for s in sql.split(";") if s.strip()]:
                    cur.execute(stmt)
                cur.close()
            conn.commit()
        finally:
            self.put_conn(conn)

    # ---- USER writes -----------------------------------------------------
    def list_users(self) -> List[dict]:
        return [dict(r) for r in self._query(
            "SELECT user_id, name, tier FROM USER")]

    def insert_user(self, name: str, tier: str, created_at: float) -> int:
        with self._write_lock:
            conn = self.get_conn()
            try:
                cur = conn.cursor()
                cur.execute(self._q(
                    "INSERT INTO USER (name, tier, created_at) VALUES (?, ?, ?)"),
                    (name, tier, created_at))
                user_id = cur.lastrowid
                conn.commit()
                return user_id
            finally:
                self.put_conn(conn)

    def update_user_tier(self, user_id: int, tier: str) -> None:
        with self._write_lock:
            conn = self.get_conn()
            try:
                self._exec(conn, self._q(
                    "UPDATE USER SET tier=? WHERE user_id=?"), (tier, user_id))
                conn.commit()
            finally:
                self.put_conn(conn)

    # ---- JOB writes ------------------------------------------------------
    def insert_job(self, job: Job) -> None:
        sql = self._q(
            "INSERT INTO JOB (job_id, user_id, owner, tier, request_text, "
            "priority, burst_ms, state, scheduler, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )
        params = (
            job.job_id, job.user_id, job.owner, job.tier, job.request_text,
            job.priority, job.burst_ms, job.state.value, job.scheduler_name,
            job.created_at,
        )
        with self._write_lock:
            conn = self.get_conn()
            try:
                self._exec(conn, sql, params)
                conn.commit()
            finally:
                self.put_conn(conn)

    def update_job_state(self, job: Job) -> None:
        sql = self._q(
            "UPDATE JOB SET state=?, scheduler=?, enqueued_at=?, started_at=?, "
            "finished_at=? WHERE job_id=?"
        )
        params = (
            job.state.value, job.scheduler_name, job.first_enqueued_at,
            job.started_at, job.finished_at, job.job_id,
        )
        with self._write_lock:
            conn = self.get_conn()
            try:
                self._exec(conn, sql, params)
                conn.commit()
            finally:
                self.put_conn(conn)

    # ---- the ACID transaction -------------------------------------------
    def save_result(self, job: Job, title: str, tracks: List[dict]) -> int:
        """Atomically persist the generated playlist and mark the JOB finished.

        Inserts TRACK rows, one PLAYLIST row, the PLAYLIST_TRACK join rows, and
        updates JOB — all in a single transaction. Any error rolls the whole
        thing back so we never leave a half-written playlist.
        """
        with self._write_lock:
            conn = self.get_conn()
            try:
                cur = conn.cursor()
                # PLAYLIST
                cur.execute(self._q(
                    "INSERT INTO PLAYLIST (job_id, title, created_at) VALUES (?, ?, ?)"
                ), (job.job_id, title, job.finished_at))
                playlist_id = cur.lastrowid

                # TRACK + PLAYLIST_TRACK
                for pos, t in enumerate(tracks, start=1):
                    cur.execute(self._q(
                        "INSERT INTO TRACK (name, artist, spotify_url, tempo, "
                        "valence, energy) VALUES (?, ?, ?, ?, ?, ?)"
                    ), (t["name"], t["artist"], t.get("spotify_url"),
                        t["tempo"], t["valence"], t["energy"]))
                    track_id = cur.lastrowid
                    cur.execute(self._q(
                        "INSERT INTO PLAYLIST_TRACK (playlist_id, track_id, position) "
                        "VALUES (?, ?, ?)"
                    ), (playlist_id, track_id, pos))

                # JOB — mark terminated
                cur.execute(self._q(
                    "UPDATE JOB SET state=?, scheduler=?, started_at=?, finished_at=? "
                    "WHERE job_id=?"
                ), (job.state.value, job.scheduler_name, job.started_at,
                    job.finished_at, job.job_id))

                conn.commit()
                return playlist_id
            except Exception:
                conn.rollback()
                raise
            finally:
                self.put_conn(conn)

    def insert_execution(self, job: Job) -> None:
        sql = self._q(
            "INSERT INTO JOB_EXECUTION (job_id, user_id, tier, scheduler, "
            "waiting_ms, turnaround_ms, response_ms, status, started_at, "
            "finished_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )
        params = (
            job.job_id, job.user_id, job.tier, job.scheduler_name,
            job.waiting_ms, job.turnaround_ms, job.response_ms, "COMPLETED",
            job.started_at, job.finished_at,
        )
        with self._write_lock:
            conn = self.get_conn()
            try:
                self._exec(conn, sql, params)
                conn.commit()
            finally:
                self.put_conn(conn)

    # ---- reads -----------------------------------------------------------
    def list_jobs(self, limit: int = 100) -> List[dict]:
        rows = self._query(
            "SELECT job_id, user_id, owner, tier, request_text, priority, "
            "burst_ms, state, scheduler, created_at FROM JOB "
            "ORDER BY job_id DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in rows]

    def playlist_for_job(self, job_id: int) -> Optional[dict]:
        pl = self._query(self._q(
            "SELECT playlist_id, title FROM PLAYLIST WHERE job_id=? "
            "ORDER BY playlist_id DESC LIMIT 1"), (job_id,))
        if not pl:
            return None
        pl = dict(pl[0])
        tracks = self._query(self._q(
            "SELECT t.name, t.artist, t.spotify_url, t.tempo, t.valence, "
            "t.energy, pt.position FROM PLAYLIST_TRACK pt "
            "JOIN TRACK t ON t.track_id = pt.track_id "
            "WHERE pt.playlist_id=? ORDER BY pt.position"), (pl["playlist_id"],))
        pl["tracks"] = [dict(t) for t in tracks]
        return pl

    def max_job_id(self) -> int:
        rows = self._query("SELECT MAX(job_id) AS m FROM JOB")
        m = rows[0]["m"] if rows else None
        return int(m) if m else 0

    def analytics(self) -> List[dict]:
        rows = self._query(
            "SELECT scheduler, COUNT(*) AS n, AVG(waiting_ms) AS avg_waiting, "
            "AVG(turnaround_ms) AS avg_turnaround, AVG(response_ms) AS avg_response "
            "FROM JOB_EXECUTION GROUP BY scheduler ORDER BY scheduler"
        )
        return [dict(r) for r in rows]

    def analytics_by_tier(self) -> List[dict]:
        """Fairness view: how each service tier is served, per scheduler."""
        rows = self._query(
            "SELECT scheduler, tier, COUNT(*) AS n, AVG(waiting_ms) AS avg_waiting, "
            "AVG(turnaround_ms) AS avg_turnaround, AVG(response_ms) AS avg_response "
            "FROM JOB_EXECUTION GROUP BY scheduler, tier ORDER BY scheduler, tier"
        )
        return [dict(r) for r in rows]

    def analytics_by_user(self) -> List[dict]:
        """Fairness view: per-user service, grouped by scheduler."""
        rows = self._query(
            "SELECT e.user_id, u.name, e.tier, e.scheduler, COUNT(*) AS n, "
            "AVG(e.waiting_ms) AS avg_waiting "
            "FROM JOB_EXECUTION e JOIN USER u ON u.user_id = e.user_id "
            "GROUP BY e.user_id, e.scheduler ORDER BY e.scheduler, avg_waiting DESC"
        )
        return [dict(r) for r in rows]

    def clear_executions(self) -> None:
        with self._write_lock:
            conn = self.get_conn()
            try:
                self._exec(conn, "DELETE FROM JOB_EXECUTION", ())
                conn.commit()
            finally:
                self.put_conn(conn)

    # ---- helpers ---------------------------------------------------------
    def _exec(self, conn, sql, params):
        if self.backend == "sqlite":
            conn.execute(sql, params)
        else:
            cur = conn.cursor()
            cur.execute(sql, params)
            cur.close()

    def _query(self, sql, params=()):
        sql = self._q(sql)
        conn = self.get_conn()
        try:
            if self.backend == "sqlite":
                cur = conn.execute(sql, params)
                rows = cur.fetchall()
            else:
                cur = conn.cursor(dictionary=True)
                cur.execute(sql, params)
                rows = cur.fetchall()
                cur.close()
            return rows
        finally:
            self.put_conn(conn)
