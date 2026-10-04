-- Workload Management System — relational schema (SQLite dialect)
-- Tables: USER, JOB, JOB_EXECUTION, TRACK, PLAYLIST, PLAYLIST_TRACK

CREATE TABLE IF NOT EXISTS USER (
    user_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    tier       TEXT NOT NULL DEFAULT 'FREE',   -- FREE | PREMIUM
    created_at REAL
);

CREATE TABLE IF NOT EXISTS JOB (
    job_id        INTEGER PRIMARY KEY,
    user_id       INTEGER NOT NULL,
    owner         TEXT    NOT NULL,             -- denormalized name for display
    tier          TEXT    NOT NULL DEFAULT 'FREE',
    request_text  TEXT    NOT NULL,
    priority      INTEGER NOT NULL DEFAULT 5,   -- lower value = higher priority
    burst_ms      INTEGER NOT NULL,             -- estimated service time
    state         TEXT    NOT NULL,             -- NEW | QUEUED | RUNNING | TERMINATED
    scheduler     TEXT,
    created_at    REAL,
    enqueued_at   REAL,
    started_at    REAL,
    finished_at   REAL,
    FOREIGN KEY (user_id) REFERENCES USER(user_id)
);

CREATE TABLE IF NOT EXISTS JOB_EXECUTION (
    exec_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id        INTEGER NOT NULL,
    user_id       INTEGER NOT NULL,
    tier          TEXT    NOT NULL,
    scheduler     TEXT    NOT NULL,
    waiting_ms    REAL    NOT NULL,
    turnaround_ms REAL    NOT NULL,
    response_ms   REAL    NOT NULL,
    status        TEXT    NOT NULL,
    started_at    REAL,
    finished_at   REAL,
    FOREIGN KEY (job_id)  REFERENCES JOB(job_id),
    FOREIGN KEY (user_id) REFERENCES USER(user_id)
);

CREATE TABLE IF NOT EXISTS TRACK (
    track_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT NOT NULL,
    artist   TEXT NOT NULL,
    spotify_url TEXT,
    tempo    REAL,
    valence  REAL,
    energy   REAL
);

CREATE TABLE IF NOT EXISTS PLAYLIST (
    playlist_id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      INTEGER NOT NULL,
    title       TEXT    NOT NULL,
    created_at  REAL,
    FOREIGN KEY (job_id) REFERENCES JOB(job_id)
);

CREATE TABLE IF NOT EXISTS PLAYLIST_TRACK (
    playlist_id INTEGER NOT NULL,
    track_id    INTEGER NOT NULL,
    position    INTEGER NOT NULL,
    PRIMARY KEY (playlist_id, track_id),
    FOREIGN KEY (playlist_id) REFERENCES PLAYLIST(playlist_id),
    FOREIGN KEY (track_id)    REFERENCES TRACK(track_id)
);

CREATE INDEX IF NOT EXISTS idx_exec_scheduler ON JOB_EXECUTION(scheduler);
CREATE INDEX IF NOT EXISTS idx_exec_tier      ON JOB_EXECUTION(tier);
CREATE INDEX IF NOT EXISTS idx_job_state      ON JOB(state);