"""Deterministic normalization layer — builds jobs tables from stored extractions."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import yaml

_NORM_DIR = Path(__file__).parent.parent / "normalization"

# ── alias loading ──────────────────────────────────────────────────────────────


def _load_yaml(name: str) -> dict:
    return yaml.safe_load((_NORM_DIR / name).read_text()) or {}


def _load_aliases() -> dict:
    tech = _load_yaml("tech_aliases.yaml")
    city_data = _load_yaml("city_aliases.yaml")
    country = _load_yaml("country_aliases.yaml")
    currency = _load_yaml("currency_aliases.yaml")
    remote = _load_yaml("remote_region_aliases.yaml")
    return {
        "tech": {k.lower(): v for k, v in tech.items()},
        "city": {k.lower(): v for k, v in (city_data.get("aliases") or {}).items()},
        "city_country": city_data.get("city_country") or {},
        "country": {k.lower(): v for k, v in country.items()},
        "currency": {k.lower(): v for k, v in currency.items()},
        "remote": remote,
    }


# ── pure normalization functions (unit-tested) ─────────────────────────────────


def apply_tech_alias(raw: str, aliases: dict[str, str]) -> str:
    """Map a raw tech string to its canonical name; passthrough if unknown."""
    return aliases.get(raw.strip().lower(), raw.strip().lower())


def apply_city_alias(raw: str, aliases: dict[str, str]) -> str:
    """Normalize city name variant to canonical form."""
    return aliases.get(raw.strip().lower(), raw.strip())


def apply_country_alias(raw: str | None, aliases: dict[str, str]) -> str | None:
    """Map a raw country string to ISO 3166-1 alpha-2; passthrough if unknown."""
    if not raw:
        return None
    return aliases.get(raw.strip().lower(), raw.strip())


def apply_currency_alias(raw: str | None, aliases: dict[str, str]) -> str | None:
    """Map a raw currency string to ISO 4217; passthrough if unknown."""
    if not raw:
        return None
    return aliases.get(raw.strip().lower(), raw.strip().upper())


def normalize_salary(
    min_val: float | None,
    max_val: float | None,
    period: str,
) -> tuple[float | None, float | None]:
    """Apply k-shorthand expansion, swap inverted min/max, null out absurd values."""
    if period == "year":
        if min_val is not None and min_val < 1000:
            min_val = min_val * 1000
        if max_val is not None and max_val < 1000:
            max_val = max_val * 1000

    # swap if inverted
    if min_val is not None and max_val is not None and min_val > max_val:
        min_val, max_val = max_val, min_val

    # null out absurd annual values
    if period == "year":
        if min_val is not None and min_val > 2_000_000:
            print(f"  [WARN] absurd salary min {min_val}, nulling")
            min_val = None
        if max_val is not None and max_val > 2_000_000:
            print(f"  [WARN] absurd salary max {max_val}, nulling")
            max_val = None

    return min_val, max_val


def map_remote_region(raw: str | None, rules: dict) -> str | None:
    """Map a free-text remote region string to the canonical enum value."""
    if not raw:
        return None
    lower = raw.lower()
    for region_key in ("worldwide", "us_only", "eu_only", "timezone_bound"):
        patterns: list[str] = rules.get(region_key) or []
        if any(p in lower for p in patterns):
            return region_key
    return "other"


def infer_country_from_city(city: str | None, city_country: dict) -> str | None:
    """Return ISO country code for a well-known city, else None."""
    if not city:
        return None
    return city_country.get(city)


# ── normalization command ──────────────────────────────────────────────────────

_DROP_ORDER = [
    "job_technologies", "job_locations", "jobs", "post_classification",
]


def _recreate_normalized_tables(conn: sqlite3.Connection) -> None:
    for table in _DROP_ORDER:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.executescript("""
    CREATE TABLE jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL,
        prompt_version TEXT NOT NULL,
        company_name TEXT, company_stage TEXT, is_yc TEXT,
        title_raw TEXT, title_normalized TEXT, seniority TEXT,
        employment_type TEXT,
        salary_min REAL, salary_max REAL, salary_currency TEXT,
        salary_period TEXT, salary_equity TEXT,
        workplace_policy TEXT, remote_region TEXT,
        visa_sponsorship TEXT, month TEXT NOT NULL
    );
    CREATE TABLE job_locations (
        job_id INTEGER NOT NULL REFERENCES jobs(id),
        city TEXT, region TEXT, country TEXT
    );
    CREATE TABLE job_technologies (
        job_id INTEGER NOT NULL REFERENCES jobs(id),
        tech_raw TEXT NOT NULL,
        tech TEXT NOT NULL,
        aliased INTEGER NOT NULL DEFAULT 0  -- 1 if found in tech_aliases.yaml, 0 if passthrough
    );
    CREATE TABLE post_classification (
        post_id INTEGER NOT NULL,
        prompt_version TEXT NOT NULL,
        post_type TEXT NOT NULL,
        ai_builds TEXT, ai_workflow TEXT, ai_skills TEXT,
        PRIMARY KEY (post_id, prompt_version)
    );
    CREATE INDEX idx_jobs_month ON jobs(month);
    CREATE INDEX idx_jobs_title ON jobs(title_normalized);
    CREATE INDEX idx_job_tech ON job_technologies(tech);
    CREATE INDEX idx_job_city ON job_locations(city);
    """)
    conn.commit()


def cmd_normalize(prompt_version: str = "v1") -> None:
    """Rebuild normalized tables from stored extractions for the given prompt version."""
    from .db import get_connection

    conn = get_connection()
    aliases = _load_aliases()
    tech_aliases = aliases["tech"]
    city_aliases = aliases["city"]
    city_country = aliases["city_country"]
    country_aliases = aliases["country"]
    currency_aliases = aliases["currency"]
    remote_rules = aliases["remote"]

    print(f"Dropping and recreating normalized tables…")
    _recreate_normalized_tables(conn)

    rows = conn.execute(
        """SELECT e.post_id, e.raw_json, t.month
           FROM extractions e
           JOIN posts p ON p.id = e.post_id
           JOIN threads t ON t.id = p.thread_id
           WHERE e.prompt_version = ? AND e.status = 'ok'
           ORDER BY e.post_id""",
        (prompt_version,),
    ).fetchall()

    print(f"Normalizing {len(rows)} extractions (prompt_version={prompt_version})…")

    unmapped_tech: dict[str, int] = {}
    processed = 0

    for row in rows:
        post_id: int = row["post_id"]
        month: str = row["month"] or "unknown"
        try:
            data: dict = json.loads(row["raw_json"])
        except Exception:
            continue

        # post_classification
        ais = data.get("ai_signals") or {}
        conn.execute(
            """INSERT OR REPLACE INTO post_classification
               (post_id, prompt_version, post_type, ai_builds, ai_workflow, ai_skills)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (post_id, prompt_version, data.get("post_type", "job_posting"),
             ais.get("company_builds_ai"), ais.get("ai_tools_in_workflow"),
             ais.get("ai_skills_required")),
        )

        # locations (post-level)
        locations = data.get("locations") or []
        wp = data.get("workplace") or {}
        remote_raw = wp.get("remote_region_raw")
        remote_region = map_remote_region(remote_raw, remote_rules)

        # company
        company = data.get("company") or {}
        company_name = company.get("name")
        company_stage = company.get("stage")
        is_yc = company.get("is_yc")

        # technologies (post-level, shared across all roles)
        techs_raw: list[str] = data.get("technologies_raw") or []

        # roles
        roles = data.get("roles") or []
        if not roles:
            roles = [{}]  # ensure at least one job row per ok post

        for role in roles:
            sal = role.get("salary") or {}
            sal_min, sal_max = normalize_salary(sal.get("min"), sal.get("max"),
                                               sal.get("period") or "unstated")
            sal_currency = apply_currency_alias(sal.get("currency_raw"), currency_aliases)

            cur = conn.execute(
                """INSERT INTO jobs
                   (post_id, prompt_version, company_name, company_stage, is_yc,
                    title_raw, title_normalized, seniority, employment_type,
                    salary_min, salary_max, salary_currency, salary_period, salary_equity,
                    workplace_policy, remote_region, visa_sponsorship, month)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (post_id, prompt_version, company_name, company_stage, is_yc,
                 role.get("title_raw"), role.get("title_guess"),
                 role.get("seniority"), role.get("employment_type"),
                 sal_min, sal_max, sal_currency,
                 sal.get("period"), sal.get("equity"),
                 wp.get("policy"), remote_region,
                 data.get("visa_sponsorship"), month),
            )
            job_id = cur.lastrowid

            # locations
            for loc in locations:
                city_raw = loc.get("city")
                city = apply_city_alias(city_raw, city_aliases) if city_raw else None
                country_raw = loc.get("country_raw")
                country = apply_country_alias(country_raw, country_aliases)
                if not country and city:
                    country = infer_country_from_city(city, city_country)
                conn.execute(
                    "INSERT INTO job_locations (job_id, city, region, country) VALUES (?,?,?,?)",
                    (job_id, city, loc.get("region"), country),
                )

            # technologies
            for tech_raw in techs_raw:
                raw_lower = tech_raw.strip().lower()
                in_aliases = raw_lower in tech_aliases
                tech = tech_aliases[raw_lower] if in_aliases else raw_lower
                if not in_aliases:
                    unmapped_tech[raw_lower] = unmapped_tech.get(raw_lower, 0) + 1
                conn.execute(
                    "INSERT INTO job_technologies (job_id, tech_raw, tech, aliased) VALUES (?,?,?,?)",
                    (job_id, tech_raw, tech, int(in_aliases)),
                )

        processed += 1
        if processed % 1000 == 0:
            conn.commit()
            print(f"  {processed}/{len(rows)}…")

    conn.commit()
    conn.close()

    print(f"\nDone. {processed} posts normalized → jobs/locations/technologies/classifications rebuilt.")

    if unmapped_tech:
        top = sorted(unmapped_tech.items(), key=lambda x: -x[1])[:20]
        print("\nTop unmapped tech_raw values (consider adding to tech_aliases.yaml):")
        for raw, count in top:
            print(f"  {count:>5}  {raw}")
