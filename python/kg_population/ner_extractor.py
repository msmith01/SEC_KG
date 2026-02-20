"""
Fast NER-based entity extraction using spaCy — no LLM required.

Extracts from preprocessed sentences:
  - Organisations         → Competitor nodes (when not the filing company)
  - GPE / LOC            → GeographicMarket nodes
  - Money / Percent       → FinancialMetric stubs
  - Forward-looking sents → ManagementOutlook stubs

This gives the graph real content for the demo even when the LLM
is unavailable (GPU down, no API key, etc.).
The LLM extractor is a richer layer on top — not a prerequisite.
"""

from __future__ import annotations

import re
import sys
import os
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config
from models.schemas import SectionDocument, SectionType, TaggedSentence


_nlp = None

def _get_nlp():
    global _nlp
    if _nlp is None:
        import spacy
        try:
            _nlp = spacy.load(config.SPACY_MODEL)
        except OSError:
            _nlp = spacy.load("en_core_web_sm")
    return _nlp


# ── Helpers ───────────────────────────────────────────────────────────────────

_MONEY_RE   = re.compile(r"\$[\d,.]+ ?(?:million|billion|trillion)?", re.IGNORECASE)
_PERCENT_RE = re.compile(r"\d+\.?\d*\s*%")

# Words that indicate the filing company — not a competitor
_SELF_REFS = {"company", "corporation", "registrant", "we", "our", "us", "firm"}


def _is_self_ref(name: str, company_name: str) -> bool:
    low = name.lower()
    if low in _SELF_REFS:
        return True
    # Fuzzy check: does the name appear as a substring of the company name?
    company_words = set(company_name.lower().split())
    name_words    = set(low.split())
    return bool(name_words & company_words)


# ── Main extractor ────────────────────────────────────────────────────────────

class NERExtractor:
    """
    Runs spaCy NER over every sentence in a SectionDocument and
    returns raw entity/relation dicts in the same format as KGExtractor
    (so Normaliser can consume it without changes).
    """

    def extract(self, doc: SectionDocument) -> dict:
        nlp = _get_nlp()
        company_name = doc.metadata.company_name

        nodes:     list[dict] = []
        relations: list[dict] = []

        seen_orgs: set[str]  = set()
        seen_geos: set[str]  = set()
        seen_metrics: set[str] = set()

        for sent in doc.sentences:
            spacy_doc = nlp(sent.text)

            for ent in spacy_doc.ents:
                label = ent.label_
                text  = ent.text.strip()

                # Organisations → Competitor (if not the filing company)
                if label == "ORG" and not _is_self_ref(text, company_name):
                    key = text.lower()
                    if key not in seen_orgs:
                        seen_orgs.add(key)
                        nodes.append({"type": "Competitor", "name": text})
                        relations.append({
                            "subject_type":  "Company",
                            "subject_title": company_name,
                            "relation":      "COMPETES_WITH",
                            "object_type":   "Competitor",
                            "object_title":  text,
                        })

                # Geopolitical / Location → GeographicMarket
                elif label in ("GPE", "LOC"):
                    key = text.lower()
                    if key not in seen_geos:
                        seen_geos.add(key)
                        nodes.append({"type": "GeographicMarket", "name": text})
                        relations.append({
                            "subject_type":  "Company",
                            "subject_title": company_name,
                            "relation":      "OPERATES_IN",
                            "object_type":   "GeographicMarket",
                            "object_title":  text,
                        })

            # Money / Percent → FinancialMetric stubs (MD&A only)
            if doc.section_type == SectionType.MDA:
                for m in _MONEY_RE.finditer(sent.text):
                    raw = m.group().strip()
                    # Try to grab the noun before/after as the metric name
                    context = sent.text[max(0, m.start()-40):m.end()+40]
                    metric_name = self._extract_metric_name(context, raw)
                    key = metric_name.lower()
                    if key not in seen_metrics and len(metric_name) > 3:
                        seen_metrics.add(key)
                        nodes.append({
                            "type":      "FinancialMetric",
                            "name":      metric_name,
                            "direction": self._infer_direction(sent.text),
                        })
                        relations.append({
                            "subject_type":  "Company",
                            "subject_title": company_name,
                            "relation":      "REPORTS",
                            "object_type":   "FinancialMetric",
                            "object_title":  metric_name,
                        })

            # Forward-looking sentences → ManagementOutlook (MD&A only)
            if doc.section_type == SectionType.MDA and sent.is_forward_looking:
                nodes.append({
                    "type":      "ManagementOutlook",
                    "text":      sent.text,
                    "sentiment": self._infer_sentiment(sent.text),
                    "horizon":   "full_year",
                })
                relations.append({
                    "subject_type":  "Company",
                    "subject_title": company_name,
                    "relation":      "HAS_OUTLOOK",
                    "object_type":   "ManagementOutlook",
                    "object_title":  sent.text[:40],
                })

        return {"nodes": nodes, "relations": relations}

    @staticmethod
    def _extract_metric_name(context: str, value: str) -> str:
        """Heuristic: grab the last noun phrase before the dollar amount."""
        before = context[:context.find(value)].strip()
        words  = before.split()
        # Take last 3 words as the metric name
        name = " ".join(words[-3:]).strip(".,;:()")
        return name or "revenue"

    @staticmethod
    def _infer_direction(text: str) -> str:
        t = text.lower()
        if any(w in t for w in ["increased", "grew", "higher", "growth", "improvement"]):
            return "increase"
        if any(w in t for w in ["decreased", "declined", "lower", "reduction", "fell"]):
            return "decrease"
        return "not_stated"

    @staticmethod
    def _infer_sentiment(text: str) -> str:
        t = text.lower()
        if any(w in t for w in ["expect growth", "confident", "strong", "opportunit",
                                  "positive", "increase", "expand"]):
            return "positive"
        if any(w in t for w in ["risk", "uncertain", "challenge", "headwind",
                                  "difficult", "pressure"]):
            return "cautious"
        return "neutral"
