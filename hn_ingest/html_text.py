"""Convert HTML post bodies to plain text for LLM input."""

from __future__ import annotations

from html.parser import HTMLParser

_BLOCK_TAGS = {"p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}


class _TextExtractor(HTMLParser):
    # convert_charrefs=True (Python 3 default) decodes all HTML entities in handle_data
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._pending_href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            attr_dict = dict(attrs)
            self._pending_href = attr_dict.get("href")
        elif tag in _BLOCK_TAGS:
            if self._parts and not self._parts[-1].endswith("\n"):
                self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._pending_href:
            self._parts.append(f" ({self._pending_href})")
            self._pending_href = None
        elif tag in _BLOCK_TAGS:
            if self._parts and not self._parts[-1].endswith("\n"):
                self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts).strip()


def html_to_text(raw_html: str) -> str:
    """Strip HTML tags, decode entities, preserve link URLs as 'text (url)'."""
    if not raw_html:
        return ""
    parser = _TextExtractor()
    parser.feed(raw_html)
    return parser.get_text()
