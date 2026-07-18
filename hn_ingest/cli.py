"""CLI entry point — parses arguments and dispatches to commands."""

import argparse
import sys

from .commands import cmd_all, cmd_posts, cmd_stats, cmd_threads


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m hn_ingest",
        description="Ingest HN 'Who is hiring?' data into SQLite.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("threads", help="Fetch and store the thread list")

    posts_p = sub.add_parser("posts", help="Fetch top-level comments for threads")
    posts_p.add_argument("--force", action="store_true", help="Re-fetch already-fetched threads")
    posts_p.add_argument(
        "--kind",
        choices=["hiring", "seekers", "freelancer"],
        default="hiring",
        help="Thread kind to fetch (default: hiring)",
    )

    sub.add_parser("stats", help="Print a sanity-check report")
    sub.add_parser("all", help="Run threads + posts + stats")

    args = parser.parse_args()

    if args.command == "threads":
        cmd_threads()
    elif args.command == "posts":
        cmd_posts(force=args.force, kind=args.kind)
    elif args.command == "stats":
        cmd_stats()
    elif args.command == "all":
        cmd_all()
    else:
        parser.print_help()
        sys.exit(1)
