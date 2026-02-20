"""
Sentence-level tagging:
  1. Coreference pre-tagging — marks sentences that contain "we", "the Company", etc.
  2. Forward-looking flagging — marks sentences with safe-harbour / future-tense language.
"""

from __future__ import annotations

import re
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config


# Compile once at import time
_COREF_RES = [re.compile(pat, re.IGNORECASE) for pat in config.COMPANY_COREFS]
_FL_RES    = [(pat, re.compile(pat, re.IGNORECASE)) for pat in config.FORWARD_LOOKING_PATTERNS]


def has_company_coref(sentence: str) -> bool:
    """Return True if the sentence contains a pronoun/phrase that refers to the filing company."""
    return any(rx.search(sentence) for rx in _COREF_RES)


def forward_looking_indicators(sentence: str) -> list[str]:
    """
    Return the list of forward-looking patterns that matched in the sentence.
    Empty list means no forward-looking language detected.
    """
    return [pat for pat, rx in _FL_RES if rx.search(sentence)]


def is_forward_looking(sentence: str) -> bool:
    """Return True if any forward-looking indicator is present."""
    return bool(forward_looking_indicators(sentence))


def tag_sentence(sentence: str) -> dict:
    """
    Return a dict of tags for a sentence.

    Returns:
        {
            "has_company_coref":  bool,
            "is_forward_looking": bool,
            "fl_indicators":      list[str],
        }
    """
    fl_hits = forward_looking_indicators(sentence)
    return {
        "has_company_coref":  has_company_coref(sentence),
        "is_forward_looking": bool(fl_hits),
        "fl_indicators":      fl_hits,
    }
