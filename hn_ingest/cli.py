"""CLI entry point — parses arguments and dispatches to commands."""

from __future__ import annotations

import argparse
import sys

from .commands import cmd_all, cmd_posts, cmd_stats, cmd_threads


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m hn_ingest",
        description="Ingest and analyze HN 'Who is hiring?' data.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── Phase 1 commands ────────────────────────────────────────────────────────
    sub.add_parser("threads", help="Fetch and store the thread list")

    posts_p = sub.add_parser("posts", help="Fetch top-level comments for threads")
    posts_p.add_argument("--force", action="store_true", help="Re-fetch already-fetched threads")
    posts_p.add_argument(
        "--kind",
        choices=["hiring", "seekers", "freelancer"],
        default="hiring",
        help="Thread kind to fetch (default: hiring)",
    )
    posts_p.add_argument(
        "--thread-id",
        type=int,
        default=None,
        metavar="ID",
        help="Fetch posts for a single thread by HN story id",
    )

    sub.add_parser("stats", help="Print Phase 1 sanity report")
    sub.add_parser("all", help="Run threads + posts + stats")

    # ── Phase 2 commands ────────────────────────────────────────────────────────
    extract_p = sub.add_parser("extract", help="Extract structured data from raw posts via LLM")
    extract_p.add_argument("--limit", type=int, default=None, metavar="N",
                           help="Cap total posts processed")
    extract_p.add_argument("--month", default=None, metavar="YYYY-MM",
                           help="Only process posts from this month")
    extract_p.add_argument("--force", action="store_true",
                           help="Re-extract already-extracted posts")
    extract_p.add_argument("--dry-run", action="store_true",
                           help="Print post count and cost estimate without calling the API")
    extract_p.add_argument("--concurrency", type=int, default=5, metavar="N",
                           help="Max concurrent API calls (default: 5)")
    extract_p.add_argument("--prompt-version", default="v1", metavar="VER",
                           help="Prompt version to use (default: v1)")

    normalize_p = sub.add_parser("normalize",
                                 help="Rebuild normalized tables from stored extractions")
    normalize_p.add_argument("--prompt-version", default="v1", metavar="VER",
                              help="Prompt version to normalize (default: v1)")

    golden_p = sub.add_parser("golden", help="Golden set sampling and evaluation")
    golden_sub = golden_p.add_subparsers(dest="golden_command", required=True)

    sample_p = golden_sub.add_parser("sample", help="Generate golden skeleton files")
    sample_p.add_argument("--n", type=int, default=30, metavar="N",
                          help="Number of posts to sample (default: 30)")

    eval_p = golden_sub.add_parser("eval", help="Evaluate extraction against labeled golden set")
    eval_p.add_argument("--prompt-version", default="v1", metavar="VER",
                        help="Prompt version to evaluate (default: v1)")

    report_p = sub.add_parser("report", help="Post-extraction analytics report")
    report_p.add_argument("--prompt-version", default="v1", metavar="VER",
                           help="Prompt version to report on (default: v1)")

    args = parser.parse_args()

    if args.command == "threads":
        cmd_threads()
    elif args.command == "posts":
        cmd_posts(force=args.force, kind=args.kind, thread_id=args.thread_id)
    elif args.command == "stats":
        cmd_stats()
    elif args.command == "all":
        cmd_all()
    elif args.command == "extract":
        from .extract import cmd_extract
        cmd_extract(
            limit=args.limit,
            month=args.month,
            force=args.force,
            dry_run=args.dry_run,
            concurrency=args.concurrency,
            prompt_version=args.prompt_version,
        )
    elif args.command == "normalize":
        from .normalize import cmd_normalize
        cmd_normalize(prompt_version=args.prompt_version)
    elif args.command == "golden":
        if args.golden_command == "sample":
            from .golden import cmd_golden_sample
            cmd_golden_sample(n=args.n)
        elif args.golden_command == "eval":
            from .golden import cmd_golden_eval
            cmd_golden_eval(prompt_version=args.prompt_version)
    elif args.command == "report":
        from .report import cmd_report
        cmd_report(prompt_version=args.prompt_version)
    else:
        parser.print_help()
        sys.exit(1)
