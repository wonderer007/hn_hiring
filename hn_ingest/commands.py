"""CLI command implementations."""

import random
import sqlite3
from datetime import datetime, timezone

from .api import fetch_thread_items, fetch_whoishiring_threads
from .db import get_connection, mark_thread_fetched, upsert_post, upsert_thread
from .parse import classify_kind, parse_month

_SPARK = "▁▂▃▄▅▆▇█"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def cmd_threads() -> None:
    """Fetch the whoishiring thread list and store it in the database."""
    conn = get_connection()
    print("Fetching whoishiring threads…")
    hits = fetch_whoishiring_threads()

    stored = 0
    for hit in hits:
        thread_id = int(hit["objectID"])
        title: str = hit.get("title") or ""
        created_at: str = hit.get("created_at") or ""
        fallback = created_at[:7] if len(created_at) >= 7 else None
        upsert_thread(conn, {
            "id": thread_id,
            "title": title,
            "kind": classify_kind(title),
            "month": parse_month(title, fallback),
            "created_at": created_at,
            "num_comments": hit.get("num_comments"),
        })
        stored += 1

    conn.commit()
    conn.close()
    print(f"Done. {stored} threads stored.")


def cmd_posts(force: bool = False, kind: str = "hiring") -> None:
    """Fetch top-level comments for threads of the given kind."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, title, month FROM threads WHERE kind = ? ORDER BY month",
        (kind,),
    ).fetchall()

    if not rows:
        print(f"No threads with kind='{kind}' found. Run 'threads' first.")
        conn.close()
        return

    total_posts = 0
    fetched_threads = 0

    for row in rows:
        thread_id: int = row["id"]
        title: str = row["title"]
        month: str = row["month"] or "?"

        # Skip already-fetched unless --force
        existing = conn.execute(
            "SELECT fetched_at FROM threads WHERE id = ?", (thread_id,)
        ).fetchone()
        if existing and existing["fetched_at"] and not force:
            print(f"  [{month}] {title[:60]} — already fetched, skipping")
            continue

        print(f"  [{month}] {title[:60]}")
        item = fetch_thread_items(thread_id)

        children: list[dict] = item.get("children") or []
        fetched_at = _now_iso()
        post_count = 0

        for child in children:
            if child is None:
                continue
            upsert_post(conn, {
                "id": child["id"],
                "thread_id": thread_id,
                "author": child.get("author"),
                "created_at": child.get("created_at") or fetched_at,
                "raw_html": child.get("text"),
                "is_deleted": int(bool(child.get("deleted"))),
                "is_dead": int(bool(child.get("dead"))),
                "fetched_at": fetched_at,
            })
            post_count += 1

        mark_thread_fetched(conn, thread_id, fetched_at)
        conn.commit()

        total_posts += post_count
        fetched_threads += 1
        print(f"    → {post_count} posts (running total: {total_posts})")

    conn.close()
    print(f"\nDone. Fetched {fetched_threads} threads, {total_posts} new posts stored.")


def cmd_stats() -> None:
    """Print a sanity-check report: counts, date range, sparkline, sample posts."""
    conn = get_connection()

    # --- threads by kind ---
    kind_rows = conn.execute(
        "SELECT kind, COUNT(*) AS n FROM threads GROUP BY kind ORDER BY n DESC"
    ).fetchall()
    print("=== HN Hiring Ingest — Stats ===\n")
    print("Threads by kind:")
    for r in kind_rows:
        print(f"  {r['kind']:<12} {r['n']:>5}")

    # --- total posts ---
    total = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    print(f"\nTotal posts: {total:,}")

    # --- date range ---
    date_range = conn.execute(
        "SELECT MIN(month), MAX(month) FROM threads WHERE kind = 'hiring' AND month IS NOT NULL"
    ).fetchone()
    print(f"Date range (hiring):  {date_range[0]} → {date_range[1]}")

    # --- posts per month sparkline ---
    monthly = conn.execute(
        """
        SELECT t.month, COUNT(p.id) AS n
        FROM threads t
        LEFT JOIN posts p ON p.thread_id = t.id
        WHERE t.kind = 'hiring' AND t.month IS NOT NULL
        GROUP BY t.month
        ORDER BY t.month
        """
    ).fetchall()

    if monthly:
        print("\nPosts per month (hiring):")
        counts = [r["n"] for r in monthly]
        mx = max(counts) or 1
        for r in monthly:
            bar = _SPARK[min(int(r["n"] / mx * (len(_SPARK) - 1)), len(_SPARK) - 1)]
            print(f"  {r['month']}  {bar}  {r['n']:>5}")

    # --- 3 random raw posts ---
    samples = conn.execute(
        "SELECT id, author, created_at, raw_html FROM posts WHERE raw_html IS NOT NULL ORDER BY RANDOM() LIMIT 3"
    ).fetchall()

    print(f"\n{'─' * 60}")
    print("3 random raw posts:")
    for i, s in enumerate(samples, 1):
        print(f"\n[{i}] id={s['id']}  author={s['author']}  date={s['created_at'][:10]}")
        text = (s["raw_html"] or "").replace("<p>", "\n").replace("</p>", "")
        # strip remaining tags for readability
        import re
        text = re.sub(r"<[^>]+>", "", text).strip()
        print(text[:500] + ("…" if len(text) > 500 else ""))

    conn.close()


def cmd_all() -> None:
    """Run threads → posts → stats in sequence."""
    cmd_threads()
    print()
    cmd_posts()
    print()
    cmd_stats()
