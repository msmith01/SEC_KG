"""
Ontology node definitions — Pydantic models for every entity type.

Sections:
  Shared base nodes  (Company, Filing, Section)
  Business Description nodes
  Risk Factors nodes
  MD&A nodes

ID conventions (from design doc):
  Company          : {cik}
  Filing           : {accession_number}
  BusinessSegment  : {cik}_{fiscal_year}_seg_{slug}
  Product          : {cik}_{fiscal_year}_prod_{slug}
  GeographicMarket : geo_{iso_country_code}
  CustomerSegment  : cs_{slug}
  Competitor       : comp_{cik} | comp_{slug}
  Regulation       : reg_{slug}
  RiskFactor       : {cik}_{accession}_risk_{sequence:04d}
  RiskDriver       : rd_{slug}
  RiskConsequence  : rc_{slug}
  Mitigation       : mit_{cik}_{accession}_{sequence:04d}
  FinancialMetric  : {cik}_{accession}_metric_{slug}
  FinancialPeriod  : fp_{cik}_{fiscal_year}_{quarter?}
  Driver           : drv_{slug}
  MacroFactor      : macro_{slug}
  ManagementOutlook: {cik}_{accession}_outlook_{sequence:04d}
"""

from __future__ import annotations

import re
from datetime import date
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# ── Utilities ─────────────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    """Convert arbitrary text to a URL/ID-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")[:60]


# ── Enums ─────────────────────────────────────────────────────────────────────

class MitigationType(str, Enum):
    INSURANCE     = "insurance"
    HEDGING       = "hedging"
    DIVERSIFICATION = "diversification"
    POLICY        = "policy"
    CONTRACT      = "contract"
    OTHER         = "other"


class DirectionEnum(str, Enum):
    INCREASE   = "increase"
    DECREASE   = "decrease"
    FLAT       = "flat"
    NOT_STATED = "not_stated"


class MacroDirection(str, Enum):
    HEADWIND = "headwind"
    TAILWIND = "tailwind"
    NEUTRAL  = "neutral"


class OutlookSentiment(str, Enum):
    POSITIVE  = "positive"
    CAUTIOUS  = "cautious"
    NEGATIVE  = "negative"
    NEUTRAL   = "neutral"


class OutlookHorizon(str, Enum):
    NEAR_TERM  = "near_term"
    FULL_YEAR  = "full_year"
    MULTI_YEAR = "multi_year"


class MetricBasis(str, Enum):
    GAAP     = "GAAP"
    NON_GAAP = "non-GAAP"


class DriverType(str, Enum):
    REVENUE_DRIVER = "revenue_driver"
    COST_DRIVER    = "cost_driver"


# ── Provenance (attached to every node and edge) ──────────────────────────────

class Provenance(BaseModel):
    filing_ref:        str            # accession number
    section_type:      str            # business | risk_factors | mda
    source_sentence:   str            # raw sentence text
    sentence_id:       str            # {accession}_{section}_{line}
    extraction_method: str = "llm"   # llm | rule | manual
    confidence:        float = 1.0
    extracted_at:      Optional[str] = None  # ISO timestamp


# ── Shared base nodes ─────────────────────────────────────────────────────────

class FiscalYear(BaseModel):
    """
    Anchor node for a calendar/fiscal year.
    One per year across all companies — the yearly 'layer' of the graph.
    node_id: fy_{year}
    """
    node_id: str      # fy_{year}
    year:    int

    @classmethod
    def make_id(cls, year: int) -> str:
        return f"fy_{year}"


class Company(BaseModel):
    """Stable across all filings — identified by CIK."""
    node_id:    str                    # {cik}
    cik:        str
    ticker:     Optional[str] = None
    name:       str
    sic_code:   Optional[str] = None
    sic_label:  Optional[str] = None
    exchange:   Optional[str] = None

    @classmethod
    def make_id(cls, cik: str) -> str:
        return cik


class Filing(BaseModel):
    """One 10-K or 10-Q filing."""
    node_id:          str             # {accession_number}
    accession_number: str
    form_type:        str
    filing_date:      date
    fiscal_year_end:  Optional[date] = None
    period_of_report: Optional[date] = None
    cik:              str             # → Company

    @classmethod
    def make_id(cls, accession: str) -> str:
        return accession


class Section(BaseModel):
    """One section within a filing."""
    node_id:      str                 # {cik}_{accession}_{section_type}
    section_type: str
    word_count:   int
    accession:    str                 # → Filing

    @classmethod
    def make_id(cls, cik: str, accession: str, section_type: str) -> str:
        return f"{cik}_{accession}_{section_type}"


# ── Business Description nodes ────────────────────────────────────────────────

class BusinessSegment(BaseModel):
    node_id:      str                 # {cik}_{year}_seg_{slug}
    name:         str
    description:  Optional[str] = None
    revenue_pct:  Optional[float] = None
    segment_type: Optional[str] = None   # taxonomy ref
    as_of_year:   int
    cik:          str
    provenance:   Provenance

    @classmethod
    def make_id(cls, cik: str, year: int, name: str) -> str:
        return f"{cik}_{year}_seg_{slugify(name)}"


class Product(BaseModel):
    node_id:    str                   # {cik}_{year}_prod_{slug}
    name:       str
    category:   Optional[str] = None  # taxonomy ref
    as_of_year: int
    cik:        str
    provenance: Provenance

    @classmethod
    def make_id(cls, cik: str, year: int, name: str) -> str:
        return f"{cik}_{year}_prod_{slugify(name)}"


class GeographicMarket(BaseModel):
    node_id:          str                   # geo_{iso_country_code}
    name:             str
    iso_code:         Optional[str] = None
    level:            str = "country"       # country | region | global
    extraction_source: Optional[str] = None  # "spacy" | "llm"

    @classmethod
    def make_id(cls, iso_code: str) -> str:
        return f"geo_{iso_code.lower()}"


class CustomerSegment(BaseModel):
    node_id: str                      # cs_{slug}
    label:   str                      # Enterprise | Government | SMB | Consumer

    @classmethod
    def make_id(cls, label: str) -> str:
        return f"cs_{slugify(label)}"


class Competitor(BaseModel):
    node_id:          str                      # comp_{cik} | comp_{slug}
    name:             str
    cik:              Optional[str] = None     # None if private
    extraction_source: Optional[str] = None   # "spacy" | "llm"

    @classmethod
    def make_id(cls, name: str, cik: Optional[str] = None) -> str:
        if cik:
            return f"comp_{cik}"
        return f"comp_{slugify(name)}"


class Regulation(BaseModel):
    node_id:      str                 # reg_{slug}
    name:         str
    body:         Optional[str] = None    # SEC, FDA, FTC …
    jurisdiction: Optional[str] = None

    @classmethod
    def make_id(cls, name: str) -> str:
        return f"reg_{slugify(name)}"


# ── Risk Factors nodes ────────────────────────────────────────────────────────

class RiskFactor(BaseModel):
    node_id:     str                  # {cik}_{accession}_risk_{seq:04d}
    title:       str
    description: str
    category:    Optional[str] = None  # taxonomy ref
    is_new:      bool = False
    word_count:  int
    cik:         str
    accession:   str
    as_of_year:  int
    provenance:  Provenance

    @classmethod
    def make_id(cls, cik: str, accession: str, seq: int) -> str:
        return f"{cik}_{accession}_risk_{seq:04d}"


class RiskDriver(BaseModel):
    node_id:  str                     # rd_{slug}
    label:    str
    category: Optional[str] = None

    @classmethod
    def make_id(cls, label: str) -> str:
        return f"rd_{slugify(label)}"


class RiskConsequence(BaseModel):
    node_id: str                      # rc_{slug}
    label:   str

    @classmethod
    def make_id(cls, label: str) -> str:
        return f"rc_{slugify(label)}"


class Mitigation(BaseModel):
    node_id:     str                  # mit_{cik}_{accession}_{seq:04d}
    description: str
    type:        MitigationType = MitigationType.OTHER
    cik:         str
    accession:   str
    provenance:  Provenance

    @classmethod
    def make_id(cls, cik: str, accession: str, seq: int) -> str:
        return f"mit_{cik}_{accession}_{seq:04d}"


# ── MD&A nodes ────────────────────────────────────────────────────────────────

class FinancialPeriod(BaseModel):
    node_id:     str                  # fp_{cik}_{year}_{quarter?}
    fiscal_year: int
    quarter:     Optional[int] = None
    start_date:  Optional[date] = None
    end_date:    Optional[date] = None
    cik:         str

    @classmethod
    def make_id(cls, cik: str, year: int, quarter: Optional[int] = None) -> str:
        base = f"fp_{cik}_{year}"
        return f"{base}_q{quarter}" if quarter else base


class FinancialMetric(BaseModel):
    node_id:    str                   # {cik}_{accession}_metric_{slug}
    name:       str                   # canonical name from glossary
    value:      Optional[float] = None
    unit:       Optional[str] = None  # USD_millions | percent | …
    direction:  DirectionEnum = DirectionEnum.NOT_STATED
    yoy_change: Optional[float] = None
    basis:      MetricBasis = MetricBasis.GAAP
    period_id:  Optional[str] = None  # → FinancialPeriod
    cik:        str
    accession:  str
    as_of_year: int
    provenance: Provenance

    @classmethod
    def make_id(cls, cik: str, accession: str, name: str) -> str:
        return f"{cik}_{accession}_metric_{slugify(name)}"


class Driver(BaseModel):
    node_id:  str                     # drv_{slug}
    label:    str
    type:     DriverType
    category: Optional[str] = None

    @classmethod
    def make_id(cls, label: str) -> str:
        return f"drv_{slugify(label)}"


class MacroFactor(BaseModel):
    node_id:   str                    # macro_{slug}
    label:     str
    direction: MacroDirection = MacroDirection.NEUTRAL

    @classmethod
    def make_id(cls, label: str) -> str:
        return f"macro_{slugify(label)}"


class ManagementOutlook(BaseModel):
    node_id:    str                   # {cik}_{accession}_outlook_{seq:04d}
    text:       str
    sentiment:  OutlookSentiment = OutlookSentiment.NEUTRAL
    horizon:    OutlookHorizon = OutlookHorizon.FULL_YEAR
    metric_ref: Optional[str] = None  # → FinancialMetric
    cik:        str
    accession:  str
    provenance: Provenance

    @classmethod
    def make_id(cls, cik: str, accession: str, seq: int) -> str:
        return f"{cik}_{accession}_outlook_{seq:04d}"
