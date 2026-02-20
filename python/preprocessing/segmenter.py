"""
Sentence segmentation using spaCy.
Splits cleaned text into sentences while preserving paragraph boundaries.
Falls back to a simple regex splitter if spaCy is unavailable.
"""

from __future__ import annotations

import re
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config
from typing import Generator


# ── spaCy loader (lazy, cached) ───────────────────────────────────────────────

_nlp = None


def _get_nlp():
    global _nlp
    if _nlp is not None:
        return _nlp

    try:
        import spacy
        try:
            _nlp = spacy.load(config.SPACY_MODEL)
        except OSError:
            # Try smaller model before giving up
            try:
                _nlp = spacy.load("en_core_web_sm")
                print(
                    f"[segmenter] Could not load '{config.SPACY_MODEL}', "
                    "fell back to 'en_core_web_sm'.",
                    file=sys.stderr,
                )
            except OSError:
                print(
                    "[segmenter] No spaCy model found. "
                    "Run: python -m spacy download en_core_web_lg",
                    file=sys.stderr,
                )
                _nlp = None
    except ImportError:
        print("[segmenter] spaCy not installed. Using regex fallback.", file=sys.stderr)

    return _nlp


# ── Regex fallback ────────────────────────────────────────────────────────────

_SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def _regex_split(text: str) -> list[str]:
    return [s.strip() for s in _SENT_RE.split(text) if s.strip()]


# ── Public interface ──────────────────────────────────────────────────────────

def split_into_paragraphs(text: str) -> list[str]:
    """
    Split text on blank lines to get paragraphs.
    Filters out paragraphs that are too short to be meaningful (<10 chars).
    """
    paragraphs = re.split(r"\n{2,}", text)
    return [p.strip() for p in paragraphs if len(p.strip()) >= 10]


def sentences_from_paragraph(paragraph: str) -> list[str]:
    """
    Segment a single paragraph into sentences.
    Uses spaCy when available; falls back to regex.
    """
    nlp = _get_nlp()
    if nlp is not None:
        doc = nlp(paragraph)
        return [sent.text.strip() for sent in doc.sents if sent.text.strip()]
    return _regex_split(paragraph)


def iter_sentences(
    text: str,
) -> Generator[tuple[int, int, str], None, None]:
    """
    Yield (paragraph_index, sentence_index_within_paragraph, sentence_text)
    for every sentence in the text.
    """
    paragraphs = split_into_paragraphs(text)
    for para_idx, paragraph in enumerate(paragraphs):
        for sent_idx, sentence in enumerate(sentences_from_paragraph(paragraph)):
            if sentence:
                yield para_idx, sent_idx, sentence
