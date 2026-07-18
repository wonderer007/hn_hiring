"""Async extraction pipeline — turns raw posts into structured JSON via OpenAI."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import anyio

from .db import get_connection
from .html_text import html_to_text
from .llm import EXTRACTION_MODEL, extract_post
from .schema import SCHEMA_VERSION

PROMPT_VERSION = "v1"
_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "extract_v1.md"
_PRICES_PATH = Path(__file__).parent.parent / "normalization" / "model_prices.json"
MAX_INPUT_CHARS = 24_000  # ~6 k tokens


def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text()


def _load_prices() -> dict:
    try:
        return json.loads(_PRICES_PATH.read_text())
    except Exception:
        return {}


def _estimate_cost(input_tok: int, output_tok: int, prices: dict) -> float:
    p = prices.get(EXTRACTION_MODEL, {})
    return (
        input_tok / 1_000_000 * p.get("input_per_1m", 0)
        + output_tok / 1_000_000 * p.get("output_per_1m", 0)
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _record_extraction(conn, post_id: int, status: str, raw_json: str,
                        in_tok: int | None, out_tok: int | None, error: str | None,
                        prompt_version: str) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO extractions
           (post_id, prompt_version, schema_version, model, raw_json,
            input_tokens, output_tokens, status, error, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (post_id, prompt_version, SCHEMA_VERSION, EXTRACTION_MODEL,
         raw_json, in_tok, out_tok, status, error, _now_iso()),
    )
    conn.commit()


async def _process_one(post: dict, system_prompt: str, limiter: anyio.CapacityLimiter,
                        state: dict, prompt_version: str) -> None:
    """Extract a single post and write the result to the DB."""
    async with limiter:
        post_id: int = post["id"]
        raw_html: str = post["raw_html"] or ""
        text = html_to_text(raw_html)

        if post["is_deleted"] or post["is_dead"] or len(text.strip()) < 50:
            _record_extraction(state["conn"], post_id, "skipped_empty", "{}",
                               None, None, None, prompt_version)
            state["skipped"] += 1
            _print_progress(state)
            return

        if len(text) > MAX_INPUT_CHARS:
            print(f"  [WARN] post {post_id} truncated from {len(text)} to {MAX_INPUT_CHARS} chars")
            text = text[:MAX_INPUT_CHARS]

        # retry loop
        from openai import RateLimitError, APIStatusError
        backoff = 2.0
        last_err: str | None = None
        success = False

        for attempt in range(3):
            try:
                parsed, in_tok, out_tok = await extract_post(text, system_prompt)
                _record_extraction(state["conn"], post_id, "ok",
                                   json.dumps(parsed), in_tok, out_tok, None, prompt_version)
                state["ok"] += 1
                state["input_tokens"] += in_tok
                state["output_tokens"] += out_tok
                success = True
                break
            except RateLimitError as e:
                retry_after = float(getattr(e, "retry_after", None) or backoff)
                print(f"  Rate limit hit, sleeping {retry_after:.0f}s…")
                await anyio.sleep(retry_after)
                backoff = max(backoff * 2, retry_after)
            except Exception as e:
                last_err = str(e)
                if attempt < 2:
                    await anyio.sleep(backoff)
                    backoff *= 2

        if not success:
            _record_extraction(state["conn"], post_id, "error", "{}",
                               None, None, last_err, prompt_version)
            state["errors"] += 1
            print(f"  ERROR post {post_id}: {(last_err or '')[:100]}")

        _print_progress(state)


def _print_progress(state: dict) -> None:
    done = state["ok"] + state["errors"] + state["skipped"]
    total = state["total"]
    if done % 50 == 0 or done == total:
        cost = _estimate_cost(state["input_tokens"], state["output_tokens"], state["prices"])
        print(
            f"  [{done}/{total}] ok={state['ok']} err={state['errors']} "
            f"skip={state['skipped']} cost≈${cost:.4f}"
        )


async def _run(posts: list[dict], system_prompt: str, concurrency: int,
               state: dict, prompt_version: str) -> None:
    limiter = anyio.CapacityLimiter(concurrency)
    async with anyio.create_task_group() as tg:
        for post in posts:
            tg.start_soon(_process_one, post, system_prompt, limiter, state, prompt_version)


def cmd_extract(
    limit: int | None = None,
    month: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    concurrency: int = 5,
    prompt_version: str = PROMPT_VERSION,
) -> None:
    """Extract structured data from raw posts via LLM."""
    system_prompt = _load_system_prompt()
    prices = _load_prices()
    conn = get_connection()

    where: list[str] = ["t.kind = 'hiring'"]
    params: list = []

    if month:
        where.append("t.month = ?")
        params.append(month)

    if not force:
        where.append(
            "NOT EXISTS ("
            "  SELECT 1 FROM extractions e"
            "  WHERE e.post_id = p.id AND e.prompt_version = ?"
            ")"
        )
        params.append(prompt_version)

    query = (
        "SELECT p.id, p.raw_html, p.is_deleted, p.is_dead "
        "FROM posts p JOIN threads t ON t.id = p.thread_id "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY t.month DESC, p.id"
    )
    if limit:
        query += f" LIMIT {limit}"

    posts = [dict(r) for r in conn.execute(query, params).fetchall()]

    if dry_run:
        est_in = len(posts) * 500
        est_out = len(posts) * 200
        cost = _estimate_cost(est_in, est_out, prices)
        print(f"Dry run: {len(posts)} posts to process")
        print(f"Cost estimate: ${cost:.2f} (~500 in / ~200 out tokens per post)")
        conn.close()
        return

    if not posts:
        print("No posts to extract. Already done? Use --force to re-run.")
        conn.close()
        return

    print(f"Extracting {len(posts)} posts "
          f"[model={EXTRACTION_MODEL}, concurrency={concurrency}, prompt={prompt_version}]")

    state: dict = {
        "ok": 0, "errors": 0, "skipped": 0,
        "input_tokens": 0, "output_tokens": 0,
        "total": len(posts), "conn": conn, "prices": prices,
    }

    anyio.run(_run, posts, system_prompt, concurrency, state, prompt_version)

    conn.close()

    cost = _estimate_cost(state["input_tokens"], state["output_tokens"], prices)
    print(
        f"\nDone. ok={state['ok']} errors={state['errors']} "
        f"skipped={state['skipped']} total_cost≈${cost:.4f}"
    )

    error_rate = state["errors"] / max(len(posts), 1)
    if error_rate > 0.05:
        print(f"ERROR: error rate {error_rate:.1%} exceeds 5% threshold.", file=sys.stderr)
        sys.exit(1)
