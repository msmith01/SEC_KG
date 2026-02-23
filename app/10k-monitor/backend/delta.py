"""
Delta engine: compares two risk-factor SectionDocument JSON files and
produces a structured diff with severity scoring.
"""
import difflib
import json
import re
from pathlib import Path

# ── Severity patterns ─────────────────────────────────────────────────────────

HIGH_PATTERNS = [
    r"going[\s\-]concern",
    r"material\s+weakness",
    r"\bcovenants?\b",
    r"\bbreach\b",
    r"\bdefault\b",
    r"liquidity\s+risk",
    r"\binsolvency\b",
    r"\bbankruptcy\b",
    r"regulatory\s+action",
    r"\brestatement\b",
    r"class[\s\-]action",
    r"securities\s+litigation",
    r"\bsanctions?\b",
    r"cyberattack",
    r"data\s+breach",
    r"material\s+adverse",
]

MED_PATTERNS = [
    r"\buncertain",
    r"significant\s+risk",
    r"material\s+risk",
    r"\bcybersecurity\b",
    r"intellectual\s+property",
    r"concentration\s+risk",
    r"key\s+personnel",
    r"market\s+risk",
    r"supply\s+chain",
    r"regulatory\s+compliance",
    r"competitive\s+pressur",
    r"interest\s+rate",
    r"foreign\s+currency",
    r"climate\s+change",
]


def score_severity(text: str) -> str:
    t = text.lower()
    for p in HIGH_PATTERNS:
        if re.search(p, t):
            return "HIGH"
    for p in MED_PATTERNS:
        if re.search(p, t):
            return "MED"
    return "LOW"


def _why_it_matters(text: str, change_type: str) -> str:
    t = text.lower()
    if re.search(r"going[\s\-]concern", t):
        return "Going concern language — potential viability risk"
    if re.search(r"material\s+weakness", t):
        return "Material weakness in internal controls"
    if re.search(r"\bcovenants?\b|\bbreach\b|\bdefault\b", t):
        return "Covenant or credit facility risk"
    if re.search(r"data\s+breach|cyberattack|cybersecurity", t):
        return "Cybersecurity / data breach risk escalation"
    if re.search(r"class[\s\-]action|securities\s+litigation", t):
        return "Securities litigation risk"
    if re.search(r"\bsanctions?\b", t):
        return "Regulatory sanctions risk"
    if re.search(r"\bliquidity\b", t):
        return "Liquidity position or financing risk"
    if re.search(r"supply\s+chain", t):
        return "Supply chain disruption risk"
    if re.search(r"\brestatement\b", t):
        return "Financial restatement risk"
    if re.search(r"material\s+adverse", t):
        return "Material adverse change disclosed"
    if change_type == "added":
        return "New risk disclosure added"
    return "Risk disclosure removed or changed"


# ── Diff computation ──────────────────────────────────────────────────────────

CONTEXT_LINES = 3  # sentences of context to show around changes


def _collapse_equal(sentences: list[str]) -> list[dict]:
    """Turn an unchanged run into context + optional collapsed block."""
    if len(sentences) <= CONTEXT_LINES * 2 + 1:
        return [{"type": "context", "text": s} for s in sentences]

    blocks: list[dict] = []
    for s in sentences[:CONTEXT_LINES]:
        blocks.append({"type": "context", "text": s})
    blocks.append({"type": "collapsed", "count": len(sentences) - CONTEXT_LINES * 2})
    for s in sentences[-CONTEXT_LINES:]:
        blocks.append({"type": "context", "text": s})
    return blocks


def compute_diff(sentences_a: list[str], sentences_b: list[str]) -> list[dict]:
    """
    sentences_a = PREVIOUS filing sentences
    sentences_b = LATEST   filing sentences
    Returns list of diff blocks: context | removed | added | collapsed
    """
    matcher = difflib.SequenceMatcher(None, sentences_a, sentences_b, autojunk=False)
    blocks: list[dict] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            blocks.extend(_collapse_equal(sentences_a[i1:i2]))
        elif tag == "delete":
            for s in sentences_a[i1:i2]:
                blocks.append({"type": "removed", "text": s, "severity": score_severity(s)})
        elif tag == "insert":
            for s in sentences_b[j1:j2]:
                blocks.append({"type": "added", "text": s, "severity": score_severity(s)})
        elif tag == "replace":
            for s in sentences_a[i1:i2]:
                blocks.append({"type": "removed", "text": s, "severity": score_severity(s)})
            for s in sentences_b[j1:j2]:
                blocks.append({"type": "added", "text": s, "severity": score_severity(s)})

    return blocks


def overall_severity(diff_blocks: list[dict]) -> str:
    sevs = [b.get("severity") for b in diff_blocks if b["type"] in ("added", "removed")]
    if "HIGH" in sevs:
        return "HIGH"
    if "MED" in sevs:
        return "MED"
    if sevs:
        return "LOW"
    return "NONE"


def extract_top_changes(diff_blocks: list[dict], n: int = 5) -> list[dict]:
    changed = [b for b in diff_blocks if b["type"] in ("added", "removed")]
    changed.sort(key=lambda b: {"HIGH": 0, "MED": 1, "LOW": 2}[b.get("severity", "LOW")])
    return [
        {
            "severity": b.get("severity", "LOW"),
            "type": b["type"],
            "text": b["text"][:600],
            "why": _why_it_matters(b["text"], b["type"]),
        }
        for b in changed[:n]
    ]


# ── File loading ──────────────────────────────────────────────────────────────

def load_sentences(file_path: str) -> list[str]:
    with open(file_path, "r", encoding="utf-8") as f:
        doc = json.load(f)
    return [
        s["text"].strip()
        for s in doc.get("sentences", [])
        if s.get("text", "").strip()
    ]


def build_delta(latest: dict, previous: dict) -> dict:
    """
    latest / previous are filing rows (dicts) from SQLite.
    Returns the full delta payload sent to the frontend.
    """
    sents_prev   = load_sentences(previous["file_path"])
    sents_latest = load_sentences(latest["file_path"])

    diff_blocks  = compute_diff(sents_prev, sents_latest)
    top_changes  = extract_top_changes(diff_blocks)
    severity     = overall_severity(diff_blocks)

    added     = sum(1 for b in diff_blocks if b["type"] == "added")
    removed   = sum(1 for b in diff_blocks if b["type"] == "removed")
    unchanged = sum(1 for b in diff_blocks if b["type"] == "context")

    return {
        "company": {
            "cik":    latest["cik"],
            "ticker": latest["ticker"],
            "name":   latest["company_name"],
        },
        "latest_filing": {
            "accession":   latest["accession"],
            "filing_date": latest["filing_date"],
            "fiscal_year": latest["fiscal_year"],
            "form_type":   latest["form_type"],
        },
        "previous_filing": {
            "accession":   previous["accession"],
            "filing_date": previous["filing_date"],
            "fiscal_year": previous["fiscal_year"],
            "form_type":   previous["form_type"],
        },
        "section": "risk_factors",
        "severity_score": severity,
        "stats": {
            "added_sentences":     added,
            "removed_sentences":   removed,
            "unchanged_sentences": unchanged,
            "total_changes":       added + removed,
        },
        "top_changes": top_changes,
        "diff_blocks":  diff_blocks,
    }
