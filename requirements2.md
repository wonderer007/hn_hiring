# Requirements — Phase 2: AI Extraction & Normalization

## 1. Overview

Phase 1 (complete) stored every raw "Who is hiring?" post in SQLite (`data/hn_hiring.db`,
tables `threads` and `posts`). Phase 2 turns each raw post into structured job data using
an LLM, then normalizes it for analytics.

Extend the existing project (`hn-hiring-ingest`) — same repo, same database file, same
conventions (Python 3.11+, uv, httpx, stdlib sqlite3, no ORM, CLI via `python -m hn_ingest`).

Provider: **OpenAI** first, via the official `openai` Python SDK, using Structured Outputs
(JSON schema mode) so responses are guaranteed-valid JSON. Design the client behind a thin
interface (one module, one function signature) so a second provider (e.g. Anthropic) can be
added later without touching the pipeline. Model name must be configurable
(env var `EXTRACTION_MODEL`, default a cheap capable model, e.g. `gpt-4o-mini` — check
current model lineup and pick the best cheap option at implementation time). API key from
`OPENAI_API_KEY` env var; never stored in the repo or DB.

## 2. Architecture principles (non-negotiable)

1. **Raw data is never modified.** Phase 2 only reads `posts.raw_html` and writes to new tables.
2. **Two normalization layers.** The LLM outputs raw strings PLUS its best-guess labels;
   deterministic post-processing in code applies alias tables we control. Fixing a
   normalization bug must NEVER require re-running the LLM.
3. **`unstated` ≠ `no`, everywhere.** Any field a post doesn't mention is `unstated`/null,
   never defaulted to a negative. Tri-state enums (yes/no/unstated), no booleans for
   anything that can be unmentioned.
4. **Version everything.** Every extraction row records `prompt_version`, `schema_version`,
   `model`, and timestamp. Multiple versions of the same post's extraction can coexist.
5. **Idempotent & resumable.** Safe to interrupt and re-run; already-extracted posts
   (for the current prompt_version) are skipped unless `--force`.

## 3. Extraction schema (LLM output, schema_version = 1)

The LLM returns exactly this JSON per post:

```json
{
  "post_type": "job_posting | seeking_work | meta_or_other",

  "company": {
    "name": "string | null",
    "url": "string | null",
    "description": "string | null  (<= 1 sentence)",
    "stage": "bootstrapped | pre_seed | seed | series_a | series_b | series_c_plus | public | unstated",
    "is_yc": "yes | no | unstated",
    "industry_tags": ["string", "..."]
  },

  "locations": [
    {"city": "string|null", "region": "string|null", "country_raw": "string|null"}
  ],

  "workplace": {
    "policy": "onsite | remote | hybrid | multiple_options | unstated",
    "remote_region_raw": "string | null"
  },

  "visa_sponsorship": "yes | no | unstated",

  "roles": [
    {
      "title_raw": "string (as written)",
      "title_guess": "software_engineer | frontend | backend | fullstack | ml_engineer | data_engineer | data_scientist | devops_sre | security | mobile | embedded | qa | product_manager | designer | engineering_manager | cto | founding_engineer | other",
      "seniority": "intern | junior | mid | senior | staff_plus | lead | manager | executive | unstated",
      "employment_type": "full_time | part_time | contract | internship | cofounder | unstated",
      "salary": {
        "min": "number | null",
        "max": "number | null",
        "currency_raw": "string | null",
        "period": "year | month | day | hour | unstated",
        "equity": "yes | no | equity_only | unstated"
      }
    }
  ],

  "technologies_raw": ["string (as written, lowercased)", "..."],

  "ai_signals": {
    "company_builds_ai": "yes | no | unstated",
    "ai_tools_in_workflow": "yes | no | unstated",
    "ai_skills_required": "yes | no | unstated"
  },

  "application": {"url": "string|null", "email": "string|null"},
  "hiring_count_hint": "string | null"
}
```

Prompt rules to encode (system prompt, stored in repo as a versioned file
`prompts/extract_v1.md`):
- Input is the post's text with HTML converted to plain text (strip tags, decode entities,
  preserve link URLs as `text (url)`).
- Location/workplace/visa are post-level defaults. Only include per-role deviations if the
  post explicitly states them (v1: do not model per-role overrides; note it as a limitation).
- Salary: extract only explicitly stated compensation. Interpret "150-250k" style shorthand
  (→ 150000–250000). Do not guess currency from location; if not stated, currency_raw=null.
- One post can contain multiple roles → multiple entries in `roles`. A generic
  "hiring engineers" with no distinct titles = one role entry.
- `seeking_work`: the author is offering their own labor (freelancer/job seeker posting in
  the wrong thread). `meta_or_other`: questions, replies, complaints, thread meta.
- Never infer `no` from silence. Silence = `unstated`/null.
- Technologies: only technologies mentioned as part of the stack or requirements, not
  incidental product names.

## 4. Database schema (new tables)

```sql
CREATE TABLE IF NOT EXISTS extractions (
    post_id INTEGER NOT NULL REFERENCES posts(id),
    prompt_version TEXT NOT NULL,      -- e.g. 'v1'
    schema_version INTEGER NOT NULL,
    model TEXT NOT NULL,
    raw_json TEXT NOT NULL,            -- exact LLM output
    input_tokens INTEGER,
    output_tokens INTEGER,
    status TEXT NOT NULL,              -- ok | error | skipped_empty
    error TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (post_id, prompt_version)
);

-- Normalized layer, derived deterministically from extractions.raw_json.
-- Rebuildable at any time via `normalize` command; safe to DROP and recreate.
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
    salary_min REAL, salary_max REAL, salary_currency TEXT, salary_period TEXT,
    salary_equity TEXT,
    workplace_policy TEXT,
    remote_region TEXT,               -- worldwide | us_only | eu_only | timezone_bound | other | null
    visa_sponsorship TEXT,
    month TEXT NOT NULL               -- denormalized from threads for query convenience
);

CREATE TABLE IF NOT EXISTS job_locations (
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    city TEXT, region TEXT, country TEXT   -- country = ISO 3166-1 alpha-2 after normalization
);

CREATE TABLE IF NOT EXISTS job_technologies (
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    tech_raw TEXT NOT NULL,
    tech TEXT NOT NULL                 -- canonical name after alias mapping
);

CREATE TABLE IF NOT EXISTS post_classification (
    post_id INTEGER NOT NULL,
    prompt_version TEXT NOT NULL,
    post_type TEXT NOT NULL,
    ai_builds TEXT, ai_workflow TEXT, ai_skills TEXT,
    PRIMARY KEY (post_id, prompt_version)
);
```

Indexes on jobs(month), jobs(title_normalized), job_technologies(tech), job_locations(city).

## 5. Normalization layer (pure code, no LLM)

A module `normalize.py` with data-driven alias tables stored as YAML/JSON files in
`normalization/` (checked into the repo, easy to extend):

- `tech_aliases`: e.g. golang→go, reactjs/react.js→react, node/node.js→nodejs,
  postgres/postgresql/psql→postgresql, k8s→kubernetes, js→javascript, ts→typescript,
  ruby on rails/rails→rails, aws services grouped sensibly. Unknown techs pass through
  lowercased; log a frequency report of unmapped values so the table can grow.
- `city_aliases`: SF/San Fran→San Francisco, NYC/New York City→New York, etc., plus
  city→country inference for well-known cities (only when country missing).
- `country_aliases`: map country_raw strings to ISO 3166-1 alpha-2 (USA/US/United States→US).
- `currency`: map currency_raw ($, USD, €, EUR, £, k$) to ISO codes. If null but the
  amounts are clearly US-style and all locations are US → leave null anyway in v1
  (no guessing; note as limitation).
- `remote_region`: map free text ("worldwide", "US only", "REMOTE (US)", "CET",
  "overlaps US mornings") to the enum; timezone mentions → timezone_bound.
- Salary sanity: normalize k-shorthand if the LLM missed it (values < 1000 with
  period=year → multiply by 1000), swap min/max if inverted, null out absurd values
  (> 2,000,000/yr) with a warning log.

`normalize` command drops and rebuilds jobs/job_locations/job_technologies/
post_classification from stored extractions for a given prompt_version. Must run in
seconds — it is pure local computation.

## 6. Pipeline behavior

- **Input preparation:** HTML→text conversion for each post (strip tags, decode entities,
  keep URLs). Truncate inputs over ~6000 tokens (log which posts were truncated).
- **Concurrency:** async with a configurable concurrency limit (default 5) and retry with
  exponential backoff on rate limits/5xx (respect Retry-After). Handle OpenAI rate limit
  errors gracefully.
- **Ordering:** process newest threads first by default (most relevant data first),
  `--month YYYY-MM` to target one thread, `--limit N` for test runs.
- **Skip logic:** skip posts that are deleted/dead or whose text is < 50 chars
  (status=skipped_empty). Skip posts already extracted with the current prompt_version
  unless `--force`.
- **Cost visibility:** accumulate token counts; print running cost estimate using a
  configurable price table (`normalization/model_prices.json`). Print total at the end.
  A `--dry-run` flag prints post count and rough cost estimate without calling the API.
- **Failure policy:** individual post failures are recorded (status=error) and don't stop
  the run. Exit non-zero if error rate > 5%.

## 7. Golden set & evaluation

- `golden/` directory: ~30 hand-labeled posts as individual JSON files
  ({post_id, expected: <schema>}). Create the tooling; I will do the labeling:
  `python -m hn_ingest golden sample --n 30` selects a stratified random sample
  (spread across years, include at least 2 known seeking_work/meta posts) and writes
  skeleton files pre-filled with the LLM's current output for me to correct.
- `python -m hn_ingest golden eval [--prompt-version v1]` runs extraction on golden posts
  and reports per-field accuracy: post_type, company.name (exact match), workplace.policy,
  visa_sponsorship, salary min/max (exact), roles count, title_guess, technologies
  (precision/recall as sets after normalization). Output a table comparing versions if
  multiple prompt_versions have been evaluated.
- Evaluation runs must never write into the main extractions table (separate eval table
  or in-memory only).

## 8. CLI additions

- `python -m hn_ingest extract [--limit N] [--month YYYY-MM] [--force] [--dry-run] [--concurrency N]`
- `python -m hn_ingest normalize [--prompt-version v1]`
- `python -m hn_ingest golden sample --n 30`
- `python -m hn_ingest golden eval [--prompt-version v1]`
- `python -m hn_ingest report` — post-extraction sanity report: post_type distribution,
  % with salary, % visa yes/no/unstated, top 20 technologies, top 20 cities, top 10
  title_normalized, jobs per month, top 20 unmapped tech_raw values

## 9. Quality bar / definition of done

- Type hints, small pure functions; normalization functions are pure and unit-tested
  (alias mapping, salary sanity, k-shorthand, remote_region mapping, ISO country mapping).
- Unit tests for HTML→text conversion.
- README section: how to run extraction, env vars, cost expectations, how versioning works,
  how to add aliases.
- Definition of done: `extract --limit 200` runs against the live API on real posts from
  at least 3 different years, then `normalize` and `report` produce plausible output with
  < 5% errors, and `report` shows non-trivial unstated percentages for visa and salary
  (if visa shows 0% unstated, something is wrong).

## 10. Explicit non-goals (v1)

- No per-role location/visa overrides, no benefits extraction, no investor names,
  no salary currency guessing, no re-processing of seekers/freelancer threads
  (structure must not preclude it later), no aggregation/JSON export (that's Phase 3).