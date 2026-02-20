"""
Edge (relationship) definitions for the knowledge graph.

Every edge carries:
  - subject_id    : source node ID
  - relation_type : one of the RelationType enum values
  - object_id     : target node ID
  - provenance    : full provenance (sentence, confidence, etc.)
  - as_of_year    : fiscal year (enables temporal queries)
  - filing_ref    : accession number

Relation types are grouped by section.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel

from ontology.nodes import Provenance


# ── Relation types ────────────────────────────────────────────────────────────

class RelationType(str, Enum):
    # ── Shared ──
    FILED_BY      = "FILED_BY"         # Filing → Company
    HAS_SECTION   = "HAS_SECTION"      # Filing → Section
    FILED_IN      = "FILED_IN"         # Filing → FiscalYear
    PRECEDES      = "PRECEDES"         # FiscalYear(N) → FiscalYear(N+1)

    # ── Business Description ──
    HAS_SEGMENT   = "HAS_SEGMENT"      # Company → BusinessSegment
    OFFERS        = "OFFERS"           # Company → Product
    OPERATES_IN   = "OPERATES_IN"      # Company → GeographicMarket
    TARGETS       = "TARGETS"          # Company → CustomerSegment
    COMPETES_WITH = "COMPETES_WITH"    # Company → Competitor
    SUBJECT_TO    = "SUBJECT_TO"       # Company → Regulation
    INCLUDES      = "INCLUDES"         # BusinessSegment → Product

    # ── Risk Factors ──
    HAS_RISK      = "HAS_RISK"         # Company → RiskFactor
    CAUSED_BY     = "CAUSED_BY"        # RiskFactor → RiskDriver
    MAY_RESULT_IN = "MAY_RESULT_IN"    # RiskFactor → RiskConsequence
    MITIGATED_BY  = "MITIGATED_BY"     # RiskFactor → Mitigation
    RELATED_TO    = "RELATED_TO"       # RiskFactor ↔ RiskFactor
    SUPERSEDES    = "SUPERSEDES"       # RiskFactor (yr N) → RiskFactor (yr N-1)

    # ── MD&A ──
    REPORTS       = "REPORTS"          # Company → FinancialMetric
    ATTRIBUTED_TO = "ATTRIBUTED_TO"    # FinancialMetric → BusinessSegment
    DRIVEN_BY     = "DRIVEN_BY"        # FinancialMetric → Driver
    IMPACTED_BY   = "IMPACTED_BY"      # FinancialMetric → MacroFactor
    HAS_OUTLOOK   = "HAS_OUTLOOK"      # Company → ManagementOutlook
    REFERENCES    = "REFERENCES"       # ManagementOutlook → FinancialMetric

    # ── Cross-section (reserved — not built yet) ──
    AFFECTS           = "AFFECTS"           # RiskFactor → BusinessSegment
    MATERIALISED_AS   = "MATERIALISED_AS"   # RiskFactor → FinancialMetric
    CITED_IN          = "CITED_IN"          # MacroFactor → RiskFactor
    REPORTED_IN       = "REPORTED_IN"       # BusinessSegment → FinancialMetric


# ── Edge model ────────────────────────────────────────────────────────────────

class Edge(BaseModel):
    """A typed, provenanced directed edge between two nodes."""

    subject_id:    str
    relation_type: RelationType
    object_id:     str
    provenance:    Provenance
    as_of_year:    int
    filing_ref:    str           # accession number (redundant with provenance, for fast filtering)
    weight:        float = 1.0   # optional edge weight / confidence

    @property
    def edge_id(self) -> str:
        """Deterministic ID for idempotent upserts."""
        return f"{self.subject_id}__{self.relation_type.value}__{self.object_id}__{self.filing_ref}"
