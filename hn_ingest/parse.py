"""Pure functions for classifying and parsing HN whoishiring thread titles."""

import re

_MONTH_NAMES: dict[str, int] = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

_MONTH_RE = re.compile(r'\((\w+)\s+(\d{4})\)')


def classify_kind(title: str) -> str:
    """Return the thread kind based on its title."""
    if title.startswith("Ask HN: Who is hiring?"):
        return "hiring"
    if "Who wants to be hired?" in title:
        return "seekers"
    if "Freelancer" in title:
        return "freelancer"
    return "other"


def parse_month(title: str, fallback: str | None) -> str | None:
    """Extract YYYY-MM from a title like '... (July 2026)'.

    Falls back to `fallback` (expected as 'YYYY-MM' prefix of an ISO timestamp)
    if the title contains no recognizable month/year parenthetical.
    """
    m = _MONTH_RE.search(title)
    if m:
        month_num = _MONTH_NAMES.get(m.group(1).lower())
        if month_num:
            return f"{m.group(2)}-{month_num:02d}"
    return fallback
