# hn-hiring-ingest

Ingests all "Ask HN: Who is hiring?" threads and their top-level job postings into a local SQLite database. Phase 1 of the HN Hiring Trends analytics project.

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

## Commands

```bash
# Fetch and store the thread list (~180 threads, 2011–present)
python -m hn_ingest threads

# Fetch all top-level job posts for hiring threads
python -m hn_ingest posts

# Re-fetch already-fetched threads
python -m hn_ingest posts --force

# Fetch a different thread kind
python -m hn_ingest posts --kind seekers

# Print a stats report (counts, sparkline, sample posts)
python -m hn_ingest stats

# Run everything: threads + posts + stats
python -m hn_ingest all
```

## Schema

```sql
CREATE TABLE threads (
    id INTEGER PRIMARY KEY,     -- HN story id
    title TEXT NOT NULL,
    kind TEXT NOT NULL,         -- hiring | seekers | freelancer | other
    month TEXT,                 -- 'YYYY-MM'
    created_at TEXT NOT NULL,   -- ISO 8601 UTC
    num_comments INTEGER,
    fetched_at TEXT             -- NULL until posts have been fetched
);

CREATE TABLE posts (
    id INTEGER PRIMARY KEY,     -- HN comment id
    thread_id INTEGER NOT NULL REFERENCES threads(id),
    author TEXT,
    created_at TEXT NOT NULL,
    raw_html TEXT,              -- comment body exactly as returned by API
    is_deleted INTEGER NOT NULL DEFAULT 0,
    is_dead INTEGER NOT NULL DEFAULT 0,
    fetched_at TEXT NOT NULL
);
```

The database lives at `data/hn_hiring.db` (gitignored). All commands are **idempotent**: re-running is safe. Threads already fetched are skipped unless `--force` is passed.

## Tests

```bash
uv run pytest
```

Tests cover the pure title-parsing logic (`classify_kind`, `parse_month`).
# hn_hiring
