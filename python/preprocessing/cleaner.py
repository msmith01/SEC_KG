"""
Text cleaning: strips HTML/XBRL markup and normalises whitespace.
Handles both raw filing text and already-extracted section text.
"""

from __future__ import annotations

import re
from bs4 import BeautifulSoup


# Boilerplate patterns that appear at the start/end of extracted sections
# and add no semantic value.
_BOILERPLATE_PATTERNS = [
    re.compile(r"Table of Contents", re.IGNORECASE),
    re.compile(r"forward[- ]looking statements?", re.IGNORECASE),  # header only
    re.compile(r"^\s*page\s+\d+\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*\d+\s*$", re.MULTILINE),   # standalone page numbers
]

# Non-ASCII and control characters to replace
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MULTI_SPACE = re.compile(r"[ \t]+")
_MULTI_NL    = re.compile(r"\n{3,}")


def strip_html(text: str) -> str:
    """
    Remove HTML and XBRL markup; preserve plain text and table content.
    If no HTML tags are detected, returns the text unchanged.
    """
    if not re.search(r"<[a-zA-Z][^>]*>", text):
        return text

    soup = BeautifulSoup(text, "lxml")

    # Remove script/style blocks entirely
    for tag in soup(["script", "style", "head"]):
        tag.decompose()

    # Convert <br> and </p> to newlines so sentence boundaries survive
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for p in soup.find_all("p"):
        p.insert_after("\n\n")

    # Tables: convert to a simple key:value representation
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        lines = []
        for row in rows:
            cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
            if any(cells):
                lines.append(" | ".join(cells))
        table.replace_with("\n".join(lines) + "\n")

    return soup.get_text(separator=" ")


def normalise_whitespace(text: str) -> str:
    """Collapse runs of spaces/tabs; reduce 3+ blank lines to 2."""
    text = _CONTROL_RE.sub(" ", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _MULTI_SPACE.sub(" ", text)
    text = _MULTI_NL.sub("\n\n", text)
    return text.strip()


def remove_boilerplate(text: str) -> str:
    """Strip common non-content patterns (page numbers, etc.)."""
    for pat in _BOILERPLATE_PATTERNS:
        text = pat.sub("", text)
    return text


def clean(text: str) -> str:
    """Full cleaning pass: HTML strip → whitespace normalise → boilerplate remove."""
    text = strip_html(text)
    text = normalise_whitespace(text)
    text = remove_boilerplate(text)
    return text
