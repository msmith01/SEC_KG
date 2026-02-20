"""
Graph writer: takes normalised ontology nodes and edges, writes them to Neo4j.

Handles:
  - Node label routing (Company → "Company" Cypher label, etc.)
  - Batch upserts for efficiency
  - Idempotent writes (MERGE on node_id)
"""

from __future__ import annotations

import sys
import os
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from ontology.neo4j_schema import Neo4jGraph, node_to_props
from ontology.nodes import (
    BusinessSegment, Company, Competitor, CustomerSegment,
    Driver, Filing, FinancialMetric, FinancialPeriod, FiscalYear,
    GeographicMarket, MacroFactor, ManagementOutlook,
    Mitigation, Product, Regulation,
    RiskConsequence, RiskDriver, RiskFactor, Section,
)
from ontology.relations import Edge, RelationType


# Map Python class → Neo4j label
_LABEL_MAP: dict[type, str] = {
    FiscalYear:        "FiscalYear",
    Company:           "Company",
    Filing:            "Filing",
    Section:           "Section",
    BusinessSegment:   "BusinessSegment",
    Product:           "Product",
    GeographicMarket:  "GeographicMarket",
    CustomerSegment:   "CustomerSegment",
    Competitor:        "Competitor",
    Regulation:        "Regulation",
    RiskFactor:        "RiskFactor",
    RiskDriver:        "RiskDriver",
    RiskConsequence:   "RiskConsequence",
    Mitigation:        "Mitigation",
    FinancialPeriod:   "FinancialPeriod",
    FinancialMetric:   "FinancialMetric",
    Driver:            "Driver",
    MacroFactor:       "MacroFactor",
    ManagementOutlook: "ManagementOutlook",
}


class GraphWriter:
    """
    Writes typed ontology objects to Neo4j.
    Can be used standalone or as part of the full population pipeline.
    """

    def __init__(self, graph: Neo4jGraph):
        self._g = graph

    def write_nodes(self, nodes: list) -> int:
        """
        Write a list of typed ontology node objects to Neo4j.
        Returns count written.
        """
        # Group by label for batch upserts
        by_label: dict[str, list[dict[str, Any]]] = {}
        for node in nodes:
            label = _LABEL_MAP.get(type(node))
            if label is None:
                print(f"[writer] Unknown node type: {type(node)}", file=sys.stderr)
                continue
            props = node_to_props(node)
            by_label.setdefault(label, []).append(props)

        total = 0
        for label, props_list in by_label.items():
            self._g.upsert_nodes(label, props_list)
            total += len(props_list)

        return total

    def write_edges(self, edges: list[Edge]) -> int:
        """Write a list of edges to Neo4j. Returns count written."""
        self._g.upsert_edges(edges)
        return len(edges)

    def write(self, nodes: list, edges: list[Edge]) -> tuple[int, int]:
        """Write both nodes and edges. Returns (nodes_written, edges_written)."""
        n = self.write_nodes(nodes)
        e = self.write_edges(edges)
        return n, e

    def ensure_fiscal_year_chain(self, fiscal_year: int) -> None:
        """
        MERGE a FiscalYear node for the given year and wire up the PRECEDES
        chain to the previous year (if it exists).  Idempotent — safe to call
        repeatedly.
        """
        fy_id   = FiscalYear.make_id(fiscal_year)
        prev_id = FiscalYear.make_id(fiscal_year - 1)

        # Upsert this year's node
        self._g.upsert_node("FiscalYear", {"node_id": fy_id, "year": fiscal_year})

        # Link previous year → this year (only if previous year node exists)
        self._g.query(
            "MATCH (prev:FiscalYear {node_id: $prev_id}) "
            "MATCH (curr:FiscalYear {node_id: $curr_id}) "
            "MERGE (prev)-[:PRECEDES]->(curr)",
            prev_id=prev_id,
            curr_id=fy_id,
        )

    def link_filing_to_fiscal_year(self, accession_number: str, fiscal_year: int) -> None:
        """Create FILED_IN edge from a Filing to its FiscalYear node."""
        fy_id = FiscalYear.make_id(fiscal_year)
        self._g.query(
            "MATCH (f:Filing {node_id: $acc}) "
            "MATCH (fy:FiscalYear {node_id: $fy_id}) "
            "MERGE (f)-[:FILED_IN]->(fy)",
            acc=accession_number,
            fy_id=fy_id,
        )
