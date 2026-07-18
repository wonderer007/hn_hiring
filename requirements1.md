# Requirements — HN Hiring Trends

## 1. Project overview

A data analytics website that analyzes the historic job postings from Hacker News "Ask HN: Who is hiring?" monthly threads (2011–present). Think "Google Trends for the HN job market": interactive charts of technology trends, hiring companies, cities, roles, remote work, and the impact of AI on the job market — plus written, data-driven analysis posts.

The site is **not** a job board. It is an analytics and publication site. It may later expand to other sources (weworkremotely.com, jobs.gorails.com), but v1 is HN only.

### Product principles
- Static-first: everything precomputed to JSON; no backend at launch.
- Raw data is sacred: store source data untransformed; all parsing/extraction is reproducible from raw.
- Transparent methodology: a public methodology page; HN readers will scrutinize the numbers.
- Every chart is shareable: permalinks and PNG export.

## 2. Architecture & phases

```
Phase 1: Ingestion      HN Algolia API → SQLite (raw threads + posts)
Phase 2: Extraction     raw posts → LLM structured extraction → normalized tables
Phase 3: Aggregation    normalized data → precomputed JSON datasets
Phase 4: Website        static site (charts + posts) reading those JSON files
```

Each phase is a separate, independently runnable step. Later phases never trigger re-scraping; re-running extraction or aggregation must always be possible from stored raw data.

**Current scope: Phase 1 only.** Phases 2–4 are described at the end for context so that Phase 1 decisions don't paint us into a corner. Do not implement them yet.

## 3. Phase 1 — Ingestion (build this now)

A Python project `hn-hiring-ingest` that scrapes all "Who is hiring?" threads and stores every raw top-level comment in SQLite.

### 3.1 Tech constraints
- Python 3.11+, `uv` for dependency management (`pyproject.toml`)
- Minimal dependencies: `httpx` for HTTP; stdlib `sqlite3` (no ORM)
- Single database file: `data/hn_hiring.db` (gitignored)
- Package with CLI entry point: `python -m hn_ingest <command>`

### 3.2 Data source — HN Algolia API

**Enumerate threads.** All stories by author `whoishiring`:
`https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&hitsPerPage=100`, paginated via `page` until exhausted.

Classify each thread by title into `kind`:
- starts with "Ask HN: Who is hiring?" → `hiring`
- contains "Who wants to be hired?" → `seekers`
- contains "Freelancer" → `freelancer`
- anything else → `other`

Store all threads with their kind. Parse month/year from the title (e.g. "(July 2026)") into `month` as `YYYY-MM`; fall back to the thread's created_at month if unparseable.

**Fetch posts.** For each `hiring` thread: `https://hn.algolia.com/api/v1/items/{thread_id}` returns the full comment tree in one call. Store only **top-level comments** (direct children of the story) — these are the job posts. Ignore nested replies. Other kinds are fetched only when explicitly requested (`--kind seekers` etc.).

The real API response is the source of truth: if field names or shapes differ from this document, inspect the live response and adapt.

### 3.3 Database schema

```sql
CREATE TABLE IF NOT EXISTS threads (
    id INTEGER PRIMARY KEY,          -- HN story id
    title TEXT NOT NULL,
    kind TEXT NOT NULL,              -- hiring | seekers | freelancer | other
    month TEXT,                      -- 'YYYY-MM'
    created_at TEXT NOT NULL,        -- ISO 8601 UTC
    num_comments INTEGER,
    fetched_at TEXT                  -- last comment fetch; NULL if never
);

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY,          -- HN comment id
    thread_id INTEGER NOT NULL REFERENCES threads(id),
    author TEXT,
    created_at TEXT NOT NULL,        -- ISO 8601 UTC
    raw_html TEXT,                   -- comment text exactly as returned
    is_deleted INTEGER NOT NULL DEFAULT 0,
    is_dead INTEGER NOT NULL DEFAULT 0,
    fetched_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_posts_thread ON posts(thread_id);
CREATE INDEX IF NOT EXISTS idx_threads_month ON threads(month, kind);
```

Keep deleted/dead posts with flags set (don't skip them) — monthly post counts are an analytics signal.

### 3.4 Behavior
- **Idempotent & resumable.** Re-running any command is safe (upsert / `INSERT OR REPLACE`). Threads with non-NULL `fetched_at` are skipped unless `--force`. An interrupted run resumes on the next invocation.
- **Rate limiting.** ≤ ~1 request/second. Exponential backoff, 3 retries on 429/5xx/timeout.
- **Logging.** Progress to stdout: current thread, posts found, running totals.

### 3.5 CLI
- `python -m hn_ingest threads` — fetch and store the thread list
- `python -m hn_ingest posts [--force] [--kind hiring|seekers|freelancer]` — fetch top-level comments (default kind: hiring)
- `python -m hn_ingest stats` — sanity report: threads by kind, total posts, posts per month (ASCII table/sparkline — the 2020 and 2023 dips should be visible), date range, 3 random raw posts printed in full
- `python -m hn_ingest all` — threads + posts + stats

### 3.6 Quality bar
- Type hints, small pure functions, docstrings on public functions
- `README.md`: setup (`uv sync`), commands, schema
- Unit tests for the title→kind/month parsing (the only non-trivial pure logic); no full API mocking
- Definition of done: `python -m hn_ingest all` runs end-to-end against the live API and the stats output looks plausible (~180 threads, tens of thousands of posts, visible monthly variation)

## 4. Phase 2 — Extraction (context only, do not build yet)

Each raw post will be run once through an LLM with a structured-output prompt, results cached in new tables keyed by post id + prompt version. Target fields per post: company name, role titles, seniority, locations, remote/onsite/hybrid, visa sponsorship (yes/no/unstated), technologies (normalized names), salary range if stated, application URL/email. A hand-labeled golden set (~30 posts) will be used to evaluate prompt iterations.

Implication for Phase 1: `raw_html` must be stored byte-for-byte as returned, and post ids must be stable — extraction will reference them.

## 5. Phase 3 — Aggregation (context only)

Normalized tables → precomputed JSON: tech mentions per month, company leaderboards, city leaderboards, role counts, remote share over time, tech-comparison series. Output small enough to serve statically.

## 6. Phase 4 — Website (context only)

Static site (framework TBD — likely Astro) with:
- Tech trends explorer: search + compare 2–5 technologies over time (hero feature)
- Leaderboards: companies, cities, technologies per year
- Remote work trend chart
- Written analysis posts embedding the interactive charts
- Methodology page
- Share permalinks + PNG export per chart

## 7. Out of scope (all phases, for now)
- Other job boards, user accounts, alerts, job browsing/search, live current-month freshness guarantees, salary deep-dives.
