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

CREATE TABLE IF NOT EXISTS extractions (
    post_id INTEGER NOT NULL REFERENCES posts(id),
    prompt_version TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    model TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    status TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (post_id, prompt_version)
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL,
    prompt_version TEXT NOT NULL,
    company_name TEXT,
    company_stage TEXT,
    is_yc TEXT,
    title_raw TEXT,
    title_normalized TEXT,
    seniority TEXT,
    employment_type TEXT,
    salary_min REAL,
    salary_max REAL,
    salary_currency TEXT,
    salary_period TEXT,
    salary_equity TEXT,
    workplace_policy TEXT,
    remote_region TEXT,
    visa_sponsorship TEXT,
    month TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_locations (
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    city TEXT,
    region TEXT,
    country TEXT
);

CREATE TABLE IF NOT EXISTS job_technologies (
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    tech_raw TEXT NOT NULL,
    tech TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS post_classification (
    post_id INTEGER NOT NULL,
    prompt_version TEXT NOT NULL,
    post_type TEXT NOT NULL,
    ai_builds TEXT,
    ai_workflow TEXT,
    ai_skills TEXT,
    PRIMARY KEY (post_id, prompt_version)
);

CREATE INDEX IF NOT EXISTS idx_jobs_month ON jobs(month);
CREATE INDEX IF NOT EXISTS idx_jobs_title ON jobs(title_normalized);
CREATE INDEX IF NOT EXISTS idx_job_tech ON job_technologies(tech);
CREATE INDEX IF NOT EXISTS idx_job_city ON job_locations(city);
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
