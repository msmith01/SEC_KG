"""
Pydantic schemas for every stage of the pipeline.

Hierarchy:
  FilingMetadata            — one per filing
  SectionDocument           — one per section per filing (output of preprocessing)
    └── TaggedSentence      — one per sentence

  GlossaryTerm              — one per canonical term (output of glossary extraction)
  GlossaryStore             — the full glossary (collection of terms)
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, model_validator


# ── Enums ─────────────────────────────────────────────────────────────────────

class SectionType(str, Enum):
    BUSINESS     = "business"
    RISK_FACTORS = "risk_factors"
    MDA          = "mda"
    EIGHT_K      = "8k"


class FormType(str, Enum):
    K10    = "10-K"
    K10405 = "10-K405"
    KSB10  = "10KSB"
    KSB10_ = "10-KSB"
    KSB1040 = "10KSB40"


class DomainTag(str, Enum):
    FINANCIAL    = "financial"
    OPERATIONAL  = "operational"
    REGULATORY   = "regulatory"
    TECHNOLOGY   = "technology"
    MARKET       = "market"
    RISK         = "risk"
    LEGAL        = "legal"
    OTHER        = "other"


# ── Filing metadata ───────────────────────────────────────────────────────────

class FilingMetadata(BaseModel):
    """Provenance bound to every entity in the pipeline."""

    cik:              str
    ticker:           Optional[str]    = None
    company_name:     str
    form_type:        str
    accession_number: str
    filing_date:      date
    fiscal_year:      int              # derived from filing_date year

    @model_validator(mode="before")
    @classmethod
    def _derive_fiscal_year(cls, values):
        if "fiscal_year" not in values or values.get("fiscal_year") is None:
            fd = values.get("filing_date")
            if fd:
                if isinstance(fd, str):
                    from datetime import datetime
                    fd = datetime.strptime(fd, "%Y-%m-%d").date()
                # 10-Ks filed in Q1 usually report on prior fiscal year
                values["fiscal_year"] = fd.year - 1 if fd.month <= 3 else fd.year
        return values


# ── Sentence ──────────────────────────────────────────────────────────────────

class TaggedSentence(BaseModel):
    """A single sentence with all annotations attached."""

    sentence_id:        str            # {accession}_{section_type}_{seq:04d}
    text:               str            # cleaned sentence text
    paragraph_index:    int            # which paragraph this came from
    sentence_index:     int            # position within paragraph
    word_count:         int

    # Tags
    has_company_coref:  bool = False   # contains "we", "the Company", etc.
    is_forward_looking: bool = False   # safe-harbour / future-tense language
    fl_indicators:      list[str] = Field(default_factory=list)

    # Provenance (duplicated from parent for flat-file access)
    cik:              str
    ticker:           Optional[str] = None
    company_name:     str
    accession_number: str
    filing_date:      date
    fiscal_year:      int
    section_type:     SectionType


# ── Section document ──────────────────────────────────────────────────────────

class SectionDocument(BaseModel):
    """
    One preprocessed section (Business / Risk Factors / MDA) for one filing.
    This is the primary output of the Preprocessing layer.
    """

    section_id:   str            # {cik}_{accession}_{section_type}
    section_type: SectionType
    metadata:     FilingMetadata

    sentences:      list[TaggedSentence]
    word_count:     int = 0
    sentence_count: int = 0

    source_file:    Optional[str] = None

    @model_validator(mode="after")
    def _compute_counts(self):
        self.word_count     = sum(s.word_count for s in self.sentences)
        self.sentence_count = len(self.sentences)
        return self


# ── Glossary ──────────────────────────────────────────────────────────────────

class GlossarySource(BaseModel):
    """Provenance for a single occurrence of a glossary term."""
    cik:            str
    accession:      str
    section_type:   SectionType
    sentence_id:    str
    sentence_text:  str


class GlossaryTerm(BaseModel):
    """
    One canonical glossary entry.
    The term is the normalised, lowercase, singular surface form.
    """
    term:           str                        # canonical form
    aliases:        list[str] = Field(default_factory=list)
    definition:     Optional[str] = None       # extracted or synthesised
    sources:        list[GlossarySource] = Field(default_factory=list)
    frequency:      int = 1                    # number of distinct filings
    section_scope:  list[SectionType] = Field(default_factory=list)
    domain_tags:    list[DomainTag] = Field(default_factory=list)
    is_acronym:     bool = False
    expansion:      Optional[str] = None       # e.g. "ARR" → "annual recurring revenue"

    def merge(self, other: "GlossaryTerm") -> "GlossaryTerm":
        """
        Merge another GlossaryTerm into this one (cross-company unification).
        The canonical term and definition of self are preserved.
        """
        seen_aliases = set(self.aliases)
        for alias in [other.term] + other.aliases:
            if alias != self.term and alias not in seen_aliases:
                self.aliases.append(alias)
                seen_aliases.add(alias)

        seen_sources = {s.sentence_id for s in self.sources}
        for src in other.sources:
            if src.sentence_id not in seen_sources:
                self.sources.append(src)
                seen_sources.add(src.sentence_id)

        seen_scopes = set(self.section_scope)
        for sc in other.section_scope:
            if sc not in seen_scopes:
                self.section_scope.append(sc)
                seen_scopes.add(sc)

        seen_tags = set(self.domain_tags)
        for tag in other.domain_tags:
            if tag not in seen_tags:
                self.domain_tags.append(tag)
                seen_tags.add(tag)

        # Frequency = distinct CIKs across both entries
        all_ciks = {s.cik for s in self.sources}
        self.frequency = len(all_ciks)

        if self.definition is None and other.definition:
            self.definition = other.definition
        if self.expansion is None and other.expansion:
            self.expansion = other.expansion

        return self


class GlossaryStore(BaseModel):
    """The full cross-company glossary — a dict keyed by canonical term."""
    terms: dict[str, GlossaryTerm] = Field(default_factory=dict)

    def upsert(self, term: GlossaryTerm) -> None:
        """Add a term, merging if the canonical form already exists."""
        key = term.term.lower().strip()
        if key in self.terms:
            self.terms[key].merge(term)
        else:
            self.terms[key] = term

    def get(self, term: str) -> Optional[GlossaryTerm]:
        return self.terms.get(term.lower().strip())

    def __len__(self) -> int:
        return len(self.terms)
