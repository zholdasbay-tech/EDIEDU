"""Хранилище: SQLite через стандартный модуль sqlite3.

SQLite выбран для MVP: один файл, ноль настройки. Все запросы параметризованы
(знаки ?), поэтому SQL-инъекции невозможны. Для продакшена схема переносится
в PostgreSQL без изменения логики.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.environ.get("EDIEDU_DB", Path(__file__).resolve().parent.parent / "edieedu.db"))

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schools (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    is_demo     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS classes (
    id          INTEGER PRIMARY KEY,
    school_id   INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    join_code   TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS users (
    id                 INTEGER PRIMARY KEY,
    username           TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name       TEXT,
    pw_hash            TEXT NOT NULL,
    pw_salt            TEXT NOT NULL,
    role               TEXT NOT NULL DEFAULT 'student' CHECK (role IN ('student', 'staff')),
    school_id          INTEGER REFERENCES schools(id) ON DELETE SET NULL,
    class_id           INTEGER REFERENCES classes(id) ON DELETE SET NULL,
    share_with_school  INTEGER NOT NULL DEFAULT 1,
    is_demo            INTEGER NOT NULL DEFAULT 0,
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS checkins (
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date           TEXT NOT NULL,
    sleep_hours    REAL,
    sleep_quality  INTEGER,
    mood           INTEGER,
    stress         INTEGER,
    energy         INTEGER,
    study_hours    REAL,
    screen_hours   REAL,
    activity_min   INTEGER,
    tags           TEXT NOT NULL DEFAULT '',
    note           TEXT NOT NULL DEFAULT '',
    updated_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, date)
);

CREATE TABLE IF NOT EXISTS experiments (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    metric      TEXT NOT NULL,
    start_date  TEXT NOT NULL,
    days        INTEGER NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_checkins_date ON checkins(date);
CREATE INDEX IF NOT EXISTS idx_users_class ON users(class_id);
"""


def connect() -> sqlite3.Connection:
    # isolation_level=None — режим автокоммита: каждая команда сохраняется сразу.
    # Там, где нужно несколько команд «всё или ничего», используем transaction().
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


@contextmanager
def get_conn():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
