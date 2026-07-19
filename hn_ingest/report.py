"""Post-extraction sanity report."""

from __future__ import annotations

from .db import get_connection


def cmd_report(prompt_version: str = "v1") -> None:
    """Print analytics summary from normalized tables."""
    conn = get_connection()

    print(f"=== HN Hiring Extraction Report (prompt_version={prompt_version}) ===\n")

    # ── extraction status ───────────────────────────────────────────────────────
    status_rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM extractions WHERE prompt_version = ? GROUP BY status",
        (prompt_version,),
    ).fetchall()
    if not status_rows:
        print("No extractions found for this prompt_version. Run 'extract' first.")
        conn.close()
        return

    print("Extraction status:")
    for r in status_rows:
        print(f"  {r['status']:<16} {r['n']:>8,}")

    # ── post_type distribution ──────────────────────────────────────────────────
    type_rows = conn.execute(
        "SELECT post_type, COUNT(*) AS n FROM post_classification "
        "WHERE prompt_version = ? GROUP BY post_type ORDER BY n DESC",
        (prompt_version,),
    ).fetchall()
    print("\nPost types:")
    total_classified = sum(r["n"] for r in type_rows)
    for r in type_rows:
        pct = r["n"] / total_classified * 100 if total_classified else 0
        print(f"  {r['post_type']:<22} {r['n']:>7,}  ({pct:.1f}%)")

    # ── salary / visa coverage ──────────────────────────────────────────────────
    total_jobs = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE prompt_version = ?", (prompt_version,)
    ).fetchone()[0]

    salary_stated = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE prompt_version = ? AND salary_min IS NOT NULL",
        (prompt_version,),
    ).fetchone()[0]

    visa_rows = conn.execute(
        "SELECT visa_sponsorship, COUNT(*) AS n FROM jobs WHERE prompt_version = ? "
        "GROUP BY visa_sponsorship ORDER BY n DESC",
        (prompt_version,),
    ).fetchall()

    print(f"\nJobs total: {total_jobs:,}")
    pct_sal = salary_stated / total_jobs * 100 if total_jobs else 0
    print(f"With salary stated: {salary_stated:,} ({pct_sal:.1f}%)")

    print("\nVisa sponsorship:")
    for r in visa_rows:
        pct = r["n"] / total_jobs * 100 if total_jobs else 0
        label = r["visa_sponsorship"] or "null"
        print(f"  {label:<12} {r['n']:>7,}  ({pct:.1f}%)")

    # ── top technologies ────────────────────────────────────────────────────────
    tech_rows = conn.execute(
        """SELECT jt.tech, COUNT(*) AS n
           FROM job_technologies jt
           JOIN jobs j ON j.id = jt.job_id
           WHERE j.prompt_version = ?
           GROUP BY jt.tech ORDER BY n DESC LIMIT 20""",
        (prompt_version,),
    ).fetchall()
    print("\nTop 20 technologies:")
    for r in tech_rows:
        print(f"  {r['tech']:<30} {r['n']:>7,}")

    # ── top cities ──────────────────────────────────────────────────────────────
    city_rows = conn.execute(
        """SELECT jl.city, COUNT(*) AS n
           FROM job_locations jl
           JOIN jobs j ON j.id = jl.job_id
           WHERE j.prompt_version = ? AND jl.city IS NOT NULL
           GROUP BY jl.city ORDER BY n DESC LIMIT 20""",
        (prompt_version,),
    ).fetchall()
    print("\nTop 20 cities:")
    for r in city_rows:
        print(f"  {r['city']:<30} {r['n']:>7,}")

    # ── top title_normalized ────────────────────────────────────────────────────
    title_rows = conn.execute(
        """SELECT title_normalized, COUNT(*) AS n FROM jobs
           WHERE prompt_version = ? AND title_normalized IS NOT NULL
           GROUP BY title_normalized ORDER BY n DESC LIMIT 10""",
        (prompt_version,),
    ).fetchall()
    print("\nTop 10 normalized titles:")
    for r in title_rows:
        print(f"  {r['title_normalized']:<30} {r['n']:>7,}")

    # ── jobs per month ──────────────────────────────────────────────────────────
    monthly = conn.execute(
        "SELECT month, COUNT(*) AS n FROM jobs WHERE prompt_version = ? "
        "GROUP BY month ORDER BY month",
        (prompt_version,),
    ).fetchall()
    if monthly:
        _SPARK = "▁▂▃▄▅▆▇█"
        counts = [r["n"] for r in monthly]
        mx = max(counts) or 1
        print("\nJobs per month:")
        for r in monthly:
            bar = _SPARK[min(int(r["n"] / mx * (len(_SPARK) - 1)), len(_SPARK) - 1)]
            print(f"  {r['month']}  {bar}  {r['n']:>6,}")

    # ── unmapped tech_raw ───────────────────────────────────────────────────────
    unmapped = conn.execute(
        """SELECT jt.tech_raw, COUNT(*) AS n
           FROM job_technologies jt
           JOIN jobs j ON j.id = jt.job_id
           WHERE j.prompt_version = ? AND jt.aliased = 0
           GROUP BY jt.tech_raw ORDER BY n DESC LIMIT 20""",
        (prompt_version,),
    ).fetchall()
    if unmapped:
        print("\nTop 20 unmapped tech_raw values (consider adding to tech_aliases.yaml):")
        for r in unmapped:
            print(f"  {r['tech_raw']:<30} {r['n']:>7,}")

    conn.close()
