# hn-hiring-ingest

Ingests all "Ask HN: Who is hiring?" threads and their top-level job postings into SQLite, then extracts structured job data via an LLM and normalizes it for analytics. Part of the HN Hiring Trends project.

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

---

## Phase 1 — Ingestion

```bash
# Fetch and store the thread list (~180 threads, 2011–present)
python -m hn_ingest threads

# Fetch all top-level job posts for hiring threads
python -m hn_ingest posts

# Re-fetch already-fetched threads
python -m hn_ingest posts --force

# Fetch a different thread kind
python -m hn_ingest posts --kind seekers

# Fetch posts for a single thread by HN story id
python -m hn_ingest posts --thread-id 42830922

# Print a stats report (counts, sparkline, sample posts)
python -m hn_ingest stats

# Run everything: threads + posts + stats
python -m hn_ingest all
```

---

## Phase 2 — Extraction & Normalization

### Environment variables

| Variable | Description | Default |
|---|---|---|
| `OPENAI_API_KEY` | OpenAI API key (required for `extract` and `golden`) | — |
| `EXTRACTION_MODEL` | Model to use for extraction | `gpt-4o-mini` |

### Commands

```bash
# Check how many posts would be extracted and estimate cost (no API calls)
python -m hn_ingest extract --dry-run

# Extract structured data from all hiring posts
python -m hn_ingest extract

# Extract only posts from a specific month
python -m hn_ingest extract --month 2024-01

# Extract a limited number of posts (useful for testing)
python -m hn_ingest extract --limit 200

# Re-extract already-extracted posts
python -m hn_ingest extract --force

# Control concurrency (default: 5 parallel API calls)
python -m hn_ingest extract --concurrency 10

# Rebuild normalized tables from stored extractions (fast, no API calls)
python -m hn_ingest normalize

# Normalize a specific prompt version
python -m hn_ingest normalize --prompt-version v1

# Print extraction analytics report
python -m hn_ingest report
```

### Cost expectations

With `gpt-4o-mini` (~$0.15/1M input, ~$0.60/1M output):
- Average post: ~400 input tokens, ~200 output tokens
- Full corpus (~200k posts): roughly $12–20 total
- Test run of 200 posts: ~$0.02

### How prompt versioning works

The system prompt lives in `prompts/extract_v1.md`. Every extraction row records `prompt_version` and `model`, so results from different versions coexist in the database.

To iterate on the prompt:
1. Copy `prompts/extract_v1.md` → `prompts/extract_v2.md` and edit it
2. Update `PROMPT_VERSION = "v2"` in `hn_ingest/extract.py`
3. Run `python -m hn_ingest extract --prompt-version v2`
4. Run `python -m hn_ingest normalize --prompt-version v2`
5. Compare reports between versions

### Golden set (evaluation)

```bash
# Generate 30 skeleton golden files (runs LLM in-memory, does NOT write to extractions table)
python -m hn_ingest golden sample --n 30

# Edit golden/{post_id}.json — correct the "expected" field to match ground truth

# Evaluate extraction accuracy against labeled golden files
python -m hn_ingest golden eval
```

### How to add alias mappings

All alias tables live in `normalization/` as YAML files. Edit the relevant file and re-run `normalize` to apply:

| File | Maps |
|---|---|
| `tech_aliases.yaml` | Raw tech strings → canonical names (`golang → go`) |
| `city_aliases.yaml` | City variants → canonical names, city → country inference |
| `country_aliases.yaml` | Country names → ISO 3166-1 alpha-2 |
| `currency_aliases.yaml` | Currency symbols/names → ISO 4217 |
| `remote_region_aliases.yaml` | Free-text remote constraints → enum values |

After editing:
```bash
python -m hn_ingest normalize
```

---

## Database schema

### Phase 1 tables

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

### Phase 2 tables

```sql
CREATE TABLE extractions (
    post_id INTEGER NOT NULL REFERENCES posts(id),
    prompt_version TEXT NOT NULL,   -- e.g. 'v1'
    schema_version INTEGER NOT NULL,
    model TEXT NOT NULL,
    raw_json TEXT NOT NULL,         -- exact LLM output
    input_tokens INTEGER,
    output_tokens INTEGER,
    status TEXT NOT NULL,           -- ok | error | skipped_empty
    error TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (post_id, prompt_version)
);

-- Rebuilt by `normalize` command; safe to DROP and recreate at any time
CREATE TABLE jobs ( ... );
CREATE TABLE job_locations ( ... );
CREATE TABLE job_technologies ( ... );
CREATE TABLE post_classification ( ... );
```

`raw_json` is stored byte-for-byte. Re-running `normalize` always rebuilds from it — no LLM calls needed.

---

## Tests

```bash
uv run pytest
```

Tests cover:
- Title parsing (`classify_kind`, `parse_month`)
- HTML → plain text conversion (`html_to_text`)
- Normalization pure functions (tech/city/country/currency aliases, salary sanity, remote region mapping)
