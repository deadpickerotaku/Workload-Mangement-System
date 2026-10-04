-- Workload Management System — relational schema (MySQL dialect)
-- Run once:  mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS wms;"
--            mysql -u root -p wms < db/schema_mysql.sql

CREATE TABLE IF NOT EXISTS USER (
    user_id    BIGINT       NOT NULL AUTO_INCREMENT,
    name       VARCHAR(255) NOT NULL UNIQUE,
    tier       VARCHAR(16)  NOT NULL DEFAULT 'FREE',
    created_at DOUBLE,
    PRIMARY KEY (user_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS JOB (
    job_id        BIGINT       NOT NULL,
    user_id       BIGINT       NOT NULL,
    owner         VARCHAR(255) NOT NULL,
    tier          VARCHAR(16)  NOT NULL DEFAULT 'FREE',
    request_text  TEXT         NOT NULL,
    priority      INT          NOT NULL DEFAULT 5,
    burst_ms      INT          NOT NULL,
    state         VARCHAR(16)  NOT NULL,
    scheduler     VARCHAR(32),
    created_at    DOUBLE,
    enqueued_at   DOUBLE,
    started_at    DOUBLE,
    finished_at   DOUBLE,
    PRIMARY KEY (job_id),
    FOREIGN KEY (user_id) REFERENCES USER(user_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS JOB_EXECUTION (
    exec_id       BIGINT      NOT NULL AUTO_INCREMENT,
    job_id        BIGINT      NOT NULL,
    user_id       BIGINT      NOT NULL,
    tier          VARCHAR(16) NOT NULL,
    scheduler     VARCHAR(32) NOT NULL,
    waiting_ms    DOUBLE      NOT NULL,
    turnaround_ms DOUBLE      NOT NULL,
    response_ms   DOUBLE      NOT NULL,
    status        VARCHAR(16) NOT NULL,
    started_at    DOUBLE,
    finished_at   DOUBLE,
    PRIMARY KEY (exec_id),
    KEY idx_exec_scheduler (scheduler),
    KEY idx_exec_tier (tier),
    FOREIGN KEY (job_id)  REFERENCES JOB(job_id),
    FOREIGN KEY (user_id) REFERENCES USER(user_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS TRACK (
    track_id    BIGINT       NOT NULL AUTO_INCREMENT,
    name        VARCHAR(255) NOT NULL,
    artist      VARCHAR(255) NOT NULL,
    spotify_url VARCHAR(512),
    tempo       DOUBLE,
    valence     DOUBLE,
    energy      DOUBLE,
    PRIMARY KEY (track_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS PLAYLIST (
    playlist_id BIGINT       NOT NULL AUTO_INCREMENT,
    job_id      BIGINT       NOT NULL,
    title       VARCHAR(255) NOT NULL,
    created_at  DOUBLE,
    PRIMARY KEY (playlist_id),
    FOREIGN KEY (job_id) REFERENCES JOB(job_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS PLAYLIST_TRACK (
    playlist_id BIGINT NOT NULL,
    track_id    BIGINT NOT NULL,
    position    INT    NOT NULL,
    PRIMARY KEY (playlist_id, track_id),
    FOREIGN KEY (playlist_id) REFERENCES PLAYLIST(playlist_id),
    FOREIGN KEY (track_id)    REFERENCES TRACK(track_id)
) ENGINE=InnoDB;