"""
Normalisation pass: maps raw extracted dicts to typed ontology nodes and edges.

Responsibilities:
  - Map extracted entity dicts → typed Pydantic ontology nodes
  - Resolve stable IDs (CIK-stable vs filing-scoped)
  - Normalise geographic markets to ISO codes
  - Resolve competitor CIKs where possible (via ticker_to_cik.csv)
  - Deduplicate nodes with the same ID
  - Build Edge objects from raw relation dicts
"""

from __future__ import annotations

import re
import sys
import os
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config
from models.schemas import SectionDocument, SectionType, FilingMetadata
from ontology.nodes import (
    BusinessSegment, Company, Competitor, CustomerSegment,
    Driver, DriverType, Filing, FinancialMetric, FinancialPeriod,
    GeographicMarket, MacroFactor, ManagementOutlook, MetricBasis,
    Mitigation, MitigationType, OutlookHorizon, OutlookSentiment,
    Product, Provenance, Regulation, RiskConsequence, RiskDriver,
    RiskFactor, Section, slugify,
    DirectionEnum, MacroDirection,
)
from ontology.relations import Edge, RelationType


# ── ISO country code lookup (common cases) ────────────────────────────────────
# Expand as needed; the LLM should supply codes but we handle fallbacks.
_ISO_MAP: dict[str, str] = {
    "united states": "US", "us": "US", "usa": "US", "u.s.": "US",
    "united kingdom": "GB", "uk": "GB",
    "china": "CN", "prc": "CN",
    "germany": "DE", "japan": "JP", "india": "IN",
    "canada": "CA", "france": "FR", "south korea": "KR",
    "taiwan": "TW", "israel": "IL", "australia": "AU",
    "brazil": "BR", "mexico": "MX",
    "global": "GLOBAL", "worldwide": "GLOBAL", "international": "INTL",
}


def _to_iso(name: str) -> str:
    return _ISO_MAP.get(name.lower().strip(), name.upper()[:4])


# ── Competitor CIK lookup ─────────────────────────────────────────────────────

_TICKER_TO_CIK: Optional[dict[str, str]] = None


def _get_ticker_map() -> dict[str, str]:
    global _TICKER_TO_CIK
    if _TICKER_TO_CIK is None:
        import pandas as pd
        path = config.TICKER_CIK_FILE
        if path.exists():
            df = pd.read_csv(path, dtype=str)
            _TICKER_TO_CIK = {
                str(row["Ticker"]).upper(): str(row["CIK"])
                for _, row in df.iterrows()
                if isinstance(row["Ticker"], str)
            }
        else:
            _TICKER_TO_CIK = {}
    return _TICKER_TO_CIK


def _resolve_competitor_cik(name: str) -> Optional[str]:
    """Try to find a CIK for a named competitor via ticker lookup."""
    ticker_map = _get_ticker_map()
    # Try the name directly as a ticker
    candidate = name.upper().strip().split()[0]
    return ticker_map.get(candidate)


# ── Provenance factory ────────────────────────────────────────────────────────

def _make_provenance(
    doc: SectionDocument,
    sentence_id: Optional[str] = None,
    confidence: float = 0.85,
    method: str = "llm",
) -> Provenance:
    return Provenance(
        filing_ref=doc.metadata.accession_number,
        section_type=doc.section_type.value,
        source_sentence=sentence_id or "",
        sentence_id=sentence_id or f"{doc.metadata.accession_number}_{doc.section_type.value}_000",
        extraction_method=method,
        confidence=confidence,
        extracted_at=datetime.utcnow().isoformat(),
    )


# ── Main normaliser ───────────────────────────────────────────────────────────

class Normaliser:
    """
    Converts raw extraction output into typed ontology nodes and edges.
    Maintains node registries to deduplicate and enable relation linking.
    """

    def __init__(self, doc: SectionDocument, extraction_method: str = "llm"):
        self.doc              = doc
        self.meta             = doc.metadata
        self._extraction_method = extraction_method
        self._prov = _make_provenance(doc, method=extraction_method)

        # node_id → typed node
        self._nodes: dict[str, object] = {}
        self._edges: list[Edge] = []

        # name → node_id (for relation linking)
        self._name_index: dict[str, str] = {}

        # Risk factor sequence counter
        self._risk_seq    = 0
        self._mitig_seq   = 0
        self._outlook_seq = 0

    # ── Public interface ──────────────────────────────────────────────────────

    def normalise(self, raw: dict) -> tuple[list, list[Edge]]:
        """
        Convert raw {"nodes": [...], "relations": [...]} from the extractor.

        Returns:
            (list of typed ontology node objects, list of Edge objects)
        """
        # Always ensure Company and Filing nodes exist
        self._ensure_company()
        self._ensure_filing()
        self._ensure_section()

        for item in raw.get("nodes", []):
            self._process_node(item)

        for rel in raw.get("relations", []):
            self._process_relation(rel)

        return list(self._nodes.values()), self._edges

    # ── Shared nodes ──────────────────────────────────────────────────────────

    def _ensure_company(self):
        nid = Company.make_id(self.meta.cik)
        if nid not in self._nodes:
            node = Company(
                node_id=nid,
                cik=self.meta.cik,
                ticker=self.meta.ticker,
                name=self.meta.company_name,
            )
            self._nodes[nid] = node
            self._name_index[self.meta.company_name.lower()] = nid

    def _ensure_filing(self):
        nid = Filing.make_id(self.meta.accession_number)
        if nid not in self._nodes:
            node = Filing(
                node_id=nid,
                accession_number=self.meta.accession_number,
                form_type=self.meta.form_type,
                filing_date=self.meta.filing_date,
                cik=self.meta.cik,
            )
            self._nodes[nid] = node
            # Filing → Company edge
            self._add_edge(nid, RelationType.FILED_BY, Company.make_id(self.meta.cik))

    def _ensure_section(self):
        nid = Section.make_id(self.meta.cik, self.meta.accession_number, self.doc.section_type.value)
        if nid not in self._nodes:
            node = Section(
                node_id=nid,
                section_type=self.doc.section_type.value,
                word_count=self.doc.word_count,
                accession=self.meta.accession_number,
            )
            self._nodes[nid] = node
            self._add_edge(
                Filing.make_id(self.meta.accession_number),
                RelationType.HAS_SECTION,
                nid,
            )

    # ── Node dispatch ─────────────────────────────────────────────────────────

    def _process_node(self, item: dict) -> Optional[str]:
        """Map a raw dict to a typed node. Returns the node_id or None."""
        t = item.get("type", "")
        if t == "RiskFactor":
            return self._add_risk_factor(item)
        elif t == "RiskDriver":
            return self._add_risk_driver(item)
        elif t == "RiskConsequence":
            return self._add_risk_consequence(item)
        elif t == "Mitigation":
            return self._add_mitigation(item)
        elif t == "BusinessSegment":
            return self._add_business_segment(item)
        elif t == "Product":
            return self._add_product(item)
        elif t == "GeographicMarket":
            return self._add_geo_market(item)
        elif t == "CustomerSegment":
            return self._add_customer_segment(item)
        elif t == "Competitor":
            return self._add_competitor(item)
        elif t == "Regulation":
            return self._add_regulation(item)
        elif t == "FinancialMetric":
            return self._add_financial_metric(item)
        elif t == "Driver":
            return self._add_driver(item)
        elif t == "MacroFactor":
            return self._add_macro_factor(item)
        elif t == "ManagementOutlook":
            return self._add_management_outlook(item)
        return None

    # ── Risk Factors nodes ────────────────────────────────────────────────────

    def _add_risk_factor(self, item: dict) -> str:
        self._risk_seq += 1
        nid = RiskFactor.make_id(self.meta.cik, self.meta.accession_number, self._risk_seq)
        title = item.get("title", "Untitled Risk")
        node = RiskFactor(
            node_id=nid,
            title=title,
            description=item.get("description", ""),
            category=item.get("category"),
            is_new=bool(item.get("is_new", False)),
            word_count=len(item.get("description", "").split()),
            cik=self.meta.cik,
            accession=self.meta.accession_number,
            as_of_year=self.meta.fiscal_year,
            provenance=self._prov,
        )
        self._nodes[nid] = node
        self._name_index[title.lower()] = nid
        # Company → RiskFactor edge
        self._add_edge(Company.make_id(self.meta.cik), RelationType.HAS_RISK, nid)
        return nid

    def _add_risk_driver(self, item: dict) -> str:
        label = item.get("title") or item.get("name", "Unknown Driver")
        nid = RiskDriver.make_id(label)
        if nid not in self._nodes:
            self._nodes[nid] = RiskDriver(node_id=nid, label=label)
            self._name_index[label.lower()] = nid
        return nid

    def _add_risk_consequence(self, item: dict) -> str:
        label = item.get("title") or item.get("name", "Unknown Consequence")
        nid = RiskConsequence.make_id(label)
        if nid not in self._nodes:
            self._nodes[nid] = RiskConsequence(node_id=nid, label=label)
            self._name_index[label.lower()] = nid
        return nid

    def _add_mitigation(self, item: dict) -> str:
        self._mitig_seq += 1
        nid = Mitigation.make_id(self.meta.cik, self.meta.accession_number, self._mitig_seq)
        desc = item.get("description") or item.get("title", "")
        raw_type = item.get("type", "other").lower()
        try:
            mit_type = MitigationType(raw_type)
        except ValueError:
            mit_type = MitigationType.OTHER
        node = Mitigation(
            node_id=nid,
            description=desc,
            type=mit_type,
            cik=self.meta.cik,
            accession=self.meta.accession_number,
            provenance=self._prov,
        )
        self._nodes[nid] = node
        self._name_index[(desc or nid).lower()[:60]] = nid
        return nid

    # ── Business Description nodes ────────────────────────────────────────────

    def _add_business_segment(self, item: dict) -> str:
        name = item.get("name", "Unknown Segment")
        nid = BusinessSegment.make_id(self.meta.cik, self.meta.fiscal_year, name)
        if nid not in self._nodes:
            node = BusinessSegment(
                node_id=nid,
                name=name,
                description=item.get("description"),
                revenue_pct=item.get("revenue_pct"),
                segment_type=item.get("segment_type"),
                as_of_year=self.meta.fiscal_year,
                cik=self.meta.cik,
                provenance=self._prov,
            )
            self._nodes[nid] = node
            self._name_index[name.lower()] = nid
        return nid

    def _add_product(self, item: dict) -> str:
        name = item.get("name", "Unknown Product")
        nid = Product.make_id(self.meta.cik, self.meta.fiscal_year, name)
        if nid not in self._nodes:
            self._nodes[nid] = Product(
                node_id=nid,
                name=name,
                category=item.get("category"),
                as_of_year=self.meta.fiscal_year,
                cik=self.meta.cik,
                provenance=self._prov,
            )
            self._name_index[name.lower()] = nid
        return nid

    def _add_geo_market(self, item: dict) -> str:
        name = item.get("name", "")
        iso = item.get("iso_code") or _to_iso(name)
        nid = GeographicMarket.make_id(iso)
        if nid not in self._nodes:
            self._nodes[nid] = GeographicMarket(
                node_id=nid,
                name=name or iso,
                iso_code=iso,
                level=item.get("level", "country"),
                extraction_source=self._extraction_method,
            )
            self._name_index[name.lower()] = nid
        return nid

    def _add_customer_segment(self, item: dict) -> str:
        label = item.get("name") or item.get("label", "Unknown")
        nid = CustomerSegment.make_id(label)
        if nid not in self._nodes:
            self._nodes[nid] = CustomerSegment(node_id=nid, label=label)
            self._name_index[label.lower()] = nid
        return nid

    def _add_competitor(self, item: dict) -> str:
        name = item.get("name", "Unknown Competitor")
        cik = _resolve_competitor_cik(name)
        nid = Competitor.make_id(name, cik)
        if nid not in self._nodes:
            self._nodes[nid] = Competitor(
                node_id=nid, name=name, cik=cik,
                extraction_source=self._extraction_method,
            )
            self._name_index[name.lower()] = nid
        return nid

    def _add_regulation(self, item: dict) -> str:
        name = item.get("name", "Unknown Regulation")
        nid = Regulation.make_id(name)
        if nid not in self._nodes:
            self._nodes[nid] = Regulation(
                node_id=nid,
                name=name,
                body=item.get("body"),
                jurisdiction=item.get("jurisdiction"),
            )
            self._name_index[name.lower()] = nid
        return nid

    # ── MD&A nodes ────────────────────────────────────────────────────────────

    def _add_financial_metric(self, item: dict) -> str:
        name = item.get("name", "Unknown Metric")
        nid = FinancialMetric.make_id(self.meta.cik, self.meta.accession_number, name)
        if nid not in self._nodes:
            try:
                direction = DirectionEnum(item.get("direction", "not_stated"))
            except ValueError:
                direction = DirectionEnum.NOT_STATED
            try:
                basis = MetricBasis(item.get("basis", "GAAP"))
            except ValueError:
                basis = MetricBasis.GAAP
            node = FinancialMetric(
                node_id=nid,
                name=name,
                value=item.get("value"),
                unit=item.get("unit"),
                direction=direction,
                yoy_change=item.get("yoy_change"),
                basis=basis,
                cik=self.meta.cik,
                accession=self.meta.accession_number,
                as_of_year=self.meta.fiscal_year,
                provenance=self._prov,
            )
            self._nodes[nid] = node
            self._name_index[name.lower()] = nid
            self._add_edge(Company.make_id(self.meta.cik), RelationType.REPORTS, nid)
        return nid

    def _add_driver(self, item: dict) -> str:
        name = item.get("name", "Unknown Driver")
        nid = Driver.make_id(name)
        if nid not in self._nodes:
            raw_type = item.get("driver_type", "revenue_driver")
            try:
                dtype = DriverType(raw_type)
            except ValueError:
                dtype = DriverType.REVENUE_DRIVER
            self._nodes[nid] = Driver(node_id=nid, label=name, type=dtype)
            self._name_index[name.lower()] = nid
        return nid

    def _add_macro_factor(self, item: dict) -> str:
        name = item.get("name", "Unknown Factor")
        nid = MacroFactor.make_id(name)
        if nid not in self._nodes:
            try:
                direction = MacroDirection(item.get("direction", "neutral"))
            except ValueError:
                direction = MacroDirection.NEUTRAL
            self._nodes[nid] = MacroFactor(
                node_id=nid,
                label=name,
                direction=direction,
            )
            self._name_index[name.lower()] = nid
        return nid

    def _add_management_outlook(self, item: dict) -> str:
        self._outlook_seq += 1
        nid = ManagementOutlook.make_id(
            self.meta.cik, self.meta.accession_number, self._outlook_seq
        )
        try:
            sentiment = OutlookSentiment(item.get("sentiment", "neutral"))
        except ValueError:
            sentiment = OutlookSentiment.NEUTRAL
        try:
            horizon = OutlookHorizon(item.get("horizon", "full_year"))
        except ValueError:
            horizon = OutlookHorizon.FULL_YEAR
        text = item.get("text") or item.get("name") or item.get("description", "")
        node = ManagementOutlook(
            node_id=nid,
            text=text,
            sentiment=sentiment,
            horizon=horizon,
            cik=self.meta.cik,
            accession=self.meta.accession_number,
            provenance=self._prov,
        )
        self._nodes[nid] = node
        self._name_index[text[:40].lower()] = nid
        self._add_edge(Company.make_id(self.meta.cik), RelationType.HAS_OUTLOOK, nid)
        return nid

    # ── Relation resolution ───────────────────────────────────────────────────

    def _process_relation(self, rel: dict) -> None:
        subject_title = rel.get("subject_title", "").lower()
        object_title  = rel.get("object_title", "").lower()
        rel_str       = rel.get("relation", "")

        try:
            rel_type = RelationType(rel_str)
        except ValueError:
            return  # unknown relation type — skip

        subject_id = self._resolve_name(subject_title)
        object_id  = self._resolve_name(object_title)

        if subject_id and object_id:
            self._add_edge(subject_id, rel_type, object_id)

    def _resolve_name(self, name: str) -> Optional[str]:
        """Look up a node_id by name (exact or prefix match)."""
        if not name:
            return None
        # Exact match
        if name in self._name_index:
            return self._name_index[name]
        # Company name heuristic
        company_name = self.meta.company_name.lower()
        if name in company_name or company_name in name:
            return Company.make_id(self.meta.cik)
        # Prefix match
        for key, nid in self._name_index.items():
            if key.startswith(name[:20]):
                return nid
        return None

    def _add_edge(self, subject_id: str, rel_type: RelationType, object_id: str) -> None:
        edge = Edge(
            subject_id=subject_id,
            relation_type=rel_type,
            object_id=object_id,
            provenance=self._prov,
            as_of_year=self.meta.fiscal_year,
            filing_ref=self.meta.accession_number,
        )
        self._edges.append(edge)
