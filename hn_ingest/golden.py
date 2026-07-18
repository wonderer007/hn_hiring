"""Golden set tooling — stratified sampling and extraction accuracy evaluation."""

from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path

import anyio

from .db import get_connection
from .html_text import html_to_text
from .llm import extract_post
from .normalize import (
    apply_tech_alias,
    map_remote_region,
    _load_aliases,
)

_GOLDEN_DIR = Path(__file__).parent.parent / "golden"
_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "extract_v1.md"


def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text()


# ── sample command ─────────────────────────────────────────────────────────────


async def _extract_in_memory(posts: list[dict], system_prompt: str) -> dict[int, dict]:
    """Run extraction for a list of posts; return {post_id: parsed_dict}."""
    results: dict[int, dict] = {}

    async def _one(post: dict) -> None:
        text = html_to_text(post["raw_html"] or "")
        if len(text.strip()) < 50:
            results[post["id"]] = {}
            return
        try:
            parsed, _, _ = await extract_post(text, system_prompt)
            results[post["id"]] = parsed
        except Exception as e:
            print(f"  [golden] error on post {post['id']}: {e}")
            results[post["id"]] = {}

    async with anyio.create_task_group() as tg:
        for post in posts:
            tg.start_soon(_one, post)

    return results


def cmd_golden_sample(n: int = 30) -> None:
    """Sample n posts stratified by year; write skeleton golden files for labeling."""
    _GOLDEN_DIR.mkdir(exist_ok=True)
    conn = get_connection()
    system_prompt = _load_system_prompt()

    # Stratified: pool by year
    all_posts = conn.execute(
        """SELECT p.id, p.raw_html, p.author, p.created_at, t.month
           FROM posts p
           JOIN threads t ON t.id = p.thread_id
           WHERE t.kind = 'hiring'
             AND p.is_deleted = 0 AND p.is_dead = 0
             AND p.raw_html IS NOT NULL AND LENGTH(p.raw_html) > 100
           ORDER BY RANDOM()""",
    ).fetchall()
    conn.close()

    # Group by year
    by_year: dict[str, list] = defaultdict(list)
    for row in all_posts:
        year = (row["month"] or "0000")[:4]
        by_year[year].append(dict(row))

    years = sorted(by_year.keys())
    selected: list[dict] = []
    per_year = max(1, n // max(len(years), 1))
    for year in years:
        selected.extend(random.sample(by_year[year], min(per_year, len(by_year[year]))))
    # trim/top-up to exactly n
    random.shuffle(selected)
    selected = selected[:n]

    print(f"Running LLM extraction on {len(selected)} sampled posts (in-memory only)…")
    llm_outputs = anyio.run(_extract_in_memory, selected, system_prompt)

    written = 0
    for post in selected:
        post_id = post["id"]
        golden_file = _GOLDEN_DIR / f"{post_id}.json"
        if golden_file.exists():
            print(f"  skip {post_id}.json (already exists)")
            continue
        llm_out = llm_outputs.get(post_id, {})
        skeleton = {
            "post_id": post_id,
            "month": post["month"],
            "raw_html": post["raw_html"],
            "llm_output": llm_out,
            "expected": llm_out,  # human: correct this field
        }
        golden_file.write_text(json.dumps(skeleton, indent=2))
        written += 1

    print(f"Wrote {written} golden files to {_GOLDEN_DIR}/")
    print("Edit the 'expected' field in each file to create ground truth labels.")


# ── eval command ───────────────────────────────────────────────────────────────


def _field_accuracy(pred: Any, expected: Any) -> bool:  # type: ignore[name-defined]
    return pred == expected


def _tech_precision_recall(pred_list: list[str], exp_list: list[str],
                           tech_aliases: dict) -> tuple[float, float]:
    pred_set = {apply_tech_alias(t, tech_aliases) for t in pred_list}
    exp_set = {apply_tech_alias(t, tech_aliases) for t in exp_list}
    if not pred_set and not exp_set:
        return 1.0, 1.0
    precision = len(pred_set & exp_set) / max(len(pred_set), 1)
    recall = len(pred_set & exp_set) / max(len(exp_set), 1)
    return precision, recall


async def _eval_posts(posts: list[dict], system_prompt: str) -> dict[int, dict]:
    return await _extract_in_memory(posts, system_prompt)


def cmd_golden_eval(prompt_version: str = "v1") -> None:
    """Evaluate extraction against labeled golden files; print per-field accuracy."""
    aliases = _load_aliases()
    tech_aliases = aliases["tech"]
    remote_rules = aliases["remote"]

    golden_files = sorted(_GOLDEN_DIR.glob("*.json"))
    labeled = []
    for f in golden_files:
        data = json.loads(f.read_text())
        if data.get("expected") and data["expected"] != data.get("llm_output"):
            labeled.append(data)

    if not labeled:
        print("No labeled golden files found. Edit the 'expected' field in golden/*.json first.")
        return

    print(f"Evaluating {len(labeled)} labeled golden posts…")
    system_prompt = _load_system_prompt()

    posts = [{"id": d["post_id"], "raw_html": d["raw_html"]} for d in labeled]
    predictions = anyio.run(_eval_posts, posts, system_prompt)

    metrics: dict[str, list] = defaultdict(list)

    for item in labeled:
        post_id = item["post_id"]
        pred = predictions.get(post_id) or {}
        exp = item["expected"]

        metrics["post_type"].append(pred.get("post_type") == exp.get("post_type"))

        comp_pred = pred.get("company") or {}
        comp_exp = exp.get("company") or {}
        metrics["company_name"].append(comp_pred.get("name") == comp_exp.get("name"))

        wp_pred = pred.get("workplace") or {}
        wp_exp = exp.get("workplace") or {}
        metrics["workplace_policy"].append(wp_pred.get("policy") == wp_exp.get("policy"))

        metrics["visa_sponsorship"].append(pred.get("visa_sponsorship") == exp.get("visa_sponsorship"))

        # salary (first role)
        roles_pred = pred.get("roles") or [{}]
        roles_exp = exp.get("roles") or [{}]
        sal_p = (roles_pred[0].get("salary") or {}) if roles_pred else {}
        sal_e = (roles_exp[0].get("salary") or {}) if roles_exp else {}
        metrics["salary_min"].append(sal_p.get("min") == sal_e.get("min"))
        metrics["salary_max"].append(sal_p.get("max") == sal_e.get("max"))
        metrics["roles_count"].append(len(roles_pred) == len(roles_exp))

        # title_guess (first role)
        t_pred = roles_pred[0].get("title_guess") if roles_pred else None
        t_exp = roles_exp[0].get("title_guess") if roles_exp else None
        metrics["title_guess"].append(t_pred == t_exp)

        # technology precision/recall
        p, r = _tech_precision_recall(
            pred.get("technologies_raw") or [],
            exp.get("technologies_raw") or [],
            tech_aliases,
        )
        metrics["tech_precision"].append(p)
        metrics["tech_recall"].append(r)

    print(f"\n{'Field':<22} {'Accuracy':>10}  (n={len(labeled)})")
    print("─" * 40)
    for field, values in metrics.items():
        avg = sum(values) / len(values)
        label = "precision" if "precision" in field else ("recall" if "recall" in field else "accuracy")
        print(f"  {field:<20} {avg:>9.1%}")


# type alias fix for standalone use
from typing import Any  # noqa: E402  (after function that references it)
