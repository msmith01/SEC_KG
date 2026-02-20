"""
Glossary extraction from preprocessed SectionDocuments.

Strategy:
  1. Rule-based pass — captures explicitly defined terms and acronyms
     without needing an LLM call (fast, deterministic, no cost).
  2. LLM pass — sends batches of sentences to the LLM to extract
     domain-specific jargon and synthesise definitions.

The two passes are merged into a single GlossaryStore per section/company,
then accumulated across all companies into a cross-company GlossaryStore.
"""

from __future__ import annotations

import json
import re
import sys
import os
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config
from models.schemas import (
    DomainTag,
    GlossarySource,
    GlossaryStore,
    GlossaryTerm,
    SectionDocument,
    SectionType,
    TaggedSentence,
)
from models.llm_client import LLMClient


# ── Rule-based patterns ───────────────────────────────────────────────────────

# Explicit definition: "X means Y", "X refers to Y", "we define X as Y", etc.
_EXPLICIT_DEF = re.compile(
    r'(?P<term>[A-Za-z][A-Za-z0-9 \-]{1,50}?)'
    r'\s+(?:means|refers to|is defined as|defined as|we define.*?as|shall mean)\s+'
    r'(?P<definition>[^.;]{10,200})',
    re.IGNORECASE,
)

# Acronym definitions: "Annual Recurring Revenue (ARR)"
_ACRONYM = re.compile(
    r'(?P<expansion>[A-Z][A-Za-z][A-Za-z0-9 \-]{2,50}?)\s*\((?P<acronym>[A-Z]{2,8})\)',
)

# Quoted terms (often definitions in legal/SEC text): '"adjusted EBITDA"'
_QUOTED_TERM = re.compile(r'"([A-Za-z][A-Za-z0-9 \-]{2,50}?)"')


def _normalise_term(raw: str) -> str:
    """Lowercase, strip leading articles and whitespace."""
    term = raw.lower().strip()
    for article in ("the ", "a ", "an "):
        if term.startswith(article):
            term = term[len(article):]
    return term.strip()


def _domain_tags_from_term(term: str) -> list[DomainTag]:
    """Heuristic domain tagging based on common keyword signals."""
    term_lower = term.lower()
    tags = []
    if any(k in term_lower for k in ["revenue", "profit", "loss", "ebitda", "margin",
                                      "cash", "debt", "equity", "income", "expense"]):
        tags.append(DomainTag.FINANCIAL)
    if any(k in term_lower for k in ["risk", "exposure", "uncertainty", "volatility"]):
        tags.append(DomainTag.RISK)
    if any(k in term_lower for k in ["regulat", "compliance", "law", "act", "sec",
                                      "fda", "ftc", "gdpr"]):
        tags.append(DomainTag.REGULATORY)
    if any(k in term_lower for k in ["software", "platform", "cloud", "ai", "ml",
                                      "data", "cyber", "technology", "tech"]):
        tags.append(DomainTag.TECHNOLOGY)
    if any(k in term_lower for k in ["market", "customer", "segment", "competitor",
                                      "industry", "demand"]):
        tags.append(DomainTag.MARKET)
    if any(k in term_lower for k in ["operation", "supply chain", "logistics",
                                      "manufactur", "headcount"]):
        tags.append(DomainTag.OPERATIONAL)
    if any(k in term_lower for k in ["contract", "agreement", "litigation",
                                      "lawsuit", "intellectual property"]):
        tags.append(DomainTag.LEGAL)
    return tags or [DomainTag.OTHER]


# ── Rule-based extractor ──────────────────────────────────────────────────────

class RuleBasedExtractor:
    """Fast, deterministic extraction of explicitly defined terms and acronyms."""

    def extract(
        self,
        doc: SectionDocument,
    ) -> list[GlossaryTerm]:
        results: list[GlossaryTerm] = []

        for sent in doc.sentences:
            results.extend(self._extract_explicit(sent, doc.section_type))
            results.extend(self._extract_acronyms(sent, doc.section_type))

        return results

    def _source(self, sent: TaggedSentence, section_type: SectionType) -> GlossarySource:
        return GlossarySource(
            cik=sent.cik,
            accession=sent.accession_number,
            section_type=section_type,
            sentence_id=sent.sentence_id,
            sentence_text=sent.text,
        )

    def _extract_explicit(
        self, sent: TaggedSentence, section_type: SectionType
    ) -> list[GlossaryTerm]:
        terms = []
        for m in _EXPLICIT_DEF.finditer(sent.text):
            raw_term = m.group("term").strip()
            definition = m.group("definition").strip()
            if len(raw_term.split()) > 6:
                continue  # too long to be a term
            canonical = _normalise_term(raw_term)
            if len(canonical) < 3:
                continue
            terms.append(
                GlossaryTerm(
                    term=canonical,
                    definition=definition,
                    sources=[self._source(sent, section_type)],
                    section_scope=[section_type],
                    domain_tags=_domain_tags_from_term(canonical),
                    frequency=1,
                )
            )
        return terms

    def _extract_acronyms(
        self, sent: TaggedSentence, section_type: SectionType
    ) -> list[GlossaryTerm]:
        terms = []
        for m in _ACRONYM.finditer(sent.text):
            acronym = m.group("acronym").strip()
            expansion = m.group("expansion").strip()
            canonical = _normalise_term(acronym)
            terms.append(
                GlossaryTerm(
                    term=canonical,
                    aliases=[_normalise_term(expansion)],
                    expansion=expansion.lower(),
                    is_acronym=True,
                    sources=[self._source(sent, section_type)],
                    section_scope=[section_type],
                    domain_tags=_domain_tags_from_term(expansion),
                    frequency=1,
                )
            )
        return terms


# ── LLM-based extractor ───────────────────────────────────────────────────────

_LLM_SYSTEM = """\
You are a financial NLP specialist extracting domain terminology from SEC 10-K filings.
Your output must be valid JSON only — no prose, no markdown fences.
"""

_LLM_PROMPT_TEMPLATE = """\
Extract domain-specific terminology from the following sentences taken from the \
{section_type} section of a 10-K filing by {company_name}.

Focus on:
- Industry-specific jargon (e.g. "adjusted EBITDA", "net revenue retention", "churn rate")
- Recurring noun phrases that describe business concepts
- Terms that a financial analyst would want defined

For each term return:
  term        : canonical lowercase singular form
  definition  : one-sentence definition as used in this filing
  domain_tags : list from [financial, operational, regulatory, technology, market, risk, legal, other]
  aliases     : other surface forms seen (if any)

Return a JSON array of objects with exactly these keys.
Return an empty array [] if no significant terms are found.

Sentences:
{sentences}
"""

_BATCH_SIZE = 20  # sentences per LLM call


class LLMExtractor:
    """LLM-assisted extraction of domain jargon and implicit definitions."""

    def __init__(self, client: Optional[LLMClient] = None):
        self._client = client or LLMClient()

    def extract(
        self,
        doc: SectionDocument,
        batch_size: int = _BATCH_SIZE,
    ) -> list[GlossaryTerm]:
        results: list[GlossaryTerm] = []

        # Only process sentences that don't look like boilerplate
        candidate_sents = [
            s for s in doc.sentences
            if s.word_count >= 8
        ]

        for i in range(0, len(candidate_sents), batch_size):
            batch = candidate_sents[i : i + batch_size]
            batch_results = self._process_batch(
                batch, doc.section_type, doc.metadata.company_name
            )
            results.extend(batch_results)

        return results

    def _process_batch(
        self,
        sentences: list[TaggedSentence],
        section_type: SectionType,
        company_name: str,
    ) -> list[GlossaryTerm]:
        if not sentences:
            return []

        sent_block = "\n".join(
            f"[{s.sentence_id}] {s.text}" for s in sentences
        )
        prompt = _LLM_PROMPT_TEMPLATE.format(
            section_type=section_type.value,
            company_name=company_name,
            sentences=sent_block,
        )

        try:
            raw = self._client.complete(prompt, system=_LLM_SYSTEM)
            # Strip any accidental markdown fences
            raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
            raw = re.sub(r"\s*```$", "", raw.strip())
            items = json.loads(raw)
        except (json.JSONDecodeError, Exception) as e:
            print(f"[LLMExtractor] Parse error: {e}", file=sys.stderr)
            return []

        if not isinstance(items, list):
            return []

        terms = []
        sent_map = {s.sentence_id: s for s in sentences}

        for item in items:
            raw_term = item.get("term", "").strip()
            if not raw_term or len(raw_term) < 3:
                continue

            canonical = _normalise_term(raw_term)
            raw_tags = item.get("domain_tags", [])
            domain_tags = []
            for t in raw_tags:
                try:
                    domain_tags.append(DomainTag(t.lower()))
                except ValueError:
                    domain_tags.append(DomainTag.OTHER)

            # Use the first sentence in the batch as provenance
            first_sent = sentences[0]
            source = GlossarySource(
                cik=first_sent.cik,
                accession=first_sent.accession_number,
                section_type=section_type,
                sentence_id=first_sent.sentence_id,
                sentence_text=first_sent.text,
            )

            terms.append(
                GlossaryTerm(
                    term=canonical,
                    aliases=[_normalise_term(a) for a in item.get("aliases", [])],
                    definition=item.get("definition"),
                    sources=[source],
                    section_scope=[section_type],
                    domain_tags=domain_tags or [DomainTag.OTHER],
                    frequency=1,
                )
            )

        return terms


# ── GlossaryBuilder — combines both passes ────────────────────────────────────

class GlossaryBuilder:
    """
    Orchestrates rule-based + LLM extraction and accumulates results
    into a GlossaryStore.
    """

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        use_llm: bool = True,
    ):
        self._rule_extractor = RuleBasedExtractor()
        self._llm_extractor  = LLMExtractor(llm_client) if use_llm else None
        self.store = GlossaryStore()

    def process_document(self, doc: SectionDocument) -> int:
        """
        Extract terms from one SectionDocument and add them to the store.
        Returns the number of new/updated terms.
        """
        before = len(self.store)

        # Rule-based pass (always)
        rule_terms = self._rule_extractor.extract(doc)
        for t in rule_terms:
            self.store.upsert(t)

        # LLM pass (optional)
        if self._llm_extractor:
            llm_terms = self._llm_extractor.extract(doc)
            for t in llm_terms:
                self.store.upsert(t)

        return len(self.store) - before

    def process_documents(self, docs: list[SectionDocument]) -> GlossaryStore:
        """Process a list of SectionDocuments and return the accumulated store."""
        for doc in docs:
            added = self.process_document(doc)
            print(
                f"[glossary] {doc.metadata.company_name} "
                f"({doc.section_type.value}): +{added} terms "
                f"[total: {len(self.store)}]"
            )
        return self.store

    def save(self, path: Optional[Path] = None) -> Path:
        """Persist the GlossaryStore to JSON."""
        if path is None:
            path = config.GLOSSARY_DIR / "glossary.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.store.model_dump_json(indent=2), encoding="utf-8")
        print(f"[glossary] Saved {len(self.store)} terms → {path}")
        return path

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "GlossaryBuilder":
        """Load an existing GlossaryStore from disk."""
        if path is None:
            path = config.GLOSSARY_DIR / "glossary.json"
        builder = cls(use_llm=False)
        if path.exists():
            builder.store = GlossaryStore.model_validate_json(path.read_text())
        return builder
