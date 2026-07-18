"""Database initialisation and upsert helpers."""

import sqlite3
from pathlib import Path

DB_PATH = Path("data/hn_hiring.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS threads (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    kind TEXT NOT NULL,
    month TEXT,
    created_at TEXT NOT NULL,
    num_comments INTEGER,
    fetched_at TEXT
);

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY,
    thread_id INTEGER NOT NULL REFERENCES threads(id),
    author TEXT,
    created_at TEXT NOT NULL,
    raw_html TEXT,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    is_dead INTEGER NOT NULL DEFAULT 0,
    fetched_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_posts_thread ON posts(thread_id);
CREATE INDEX IF NOT EXISTS idx_threads_month ON threads(month, kind);
"""


def get_connection() -> sqlite3.Connection:
    """Open (or create) the SQLite database and return a connection."""
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def upsert_thread(conn: sqlite3.Connection, thread: dict) -> None:
    """Insert or update a thread row, preserving fetched_at on conflict."""
    conn.execute(
        """
        INSERT INTO threads (id, title, kind, month, created_at, num_comments, fetched_at)
        VALUES (:id, :title, :kind, :month, :created_at, :num_comments, NULL)
        ON CONFLICT(id) DO UPDATE SET
            title        = excluded.title,
            kind         = excluded.kind,
            month        = excluded.month,
            created_at   = excluded.created_at,
            num_comments = excluded.num_comments
        """,
        thread,
    )


def mark_thread_fetched(conn: sqlite3.Connection, thread_id: int, fetched_at: str) -> None:
    """Set fetched_at on a thread after its posts have been downloaded."""
    conn.execute(
        "UPDATE threads SET fetched_at = ? WHERE id = ?",
        (fetched_at, thread_id),
    )


def upsert_post(conn: sqlite3.Connection, post: dict) -> None:
    """Insert or replace a post row."""
    conn.execute(
        """
        INSERT OR REPLACE INTO posts
            (id, thread_id, author, created_at, raw_html, is_deleted, is_dead, fetched_at)
        VALUES
            (:id, :thread_id, :author, :created_at, :raw_html, :is_deleted, :is_dead, :fetched_at)
        """,
        post,
    )
