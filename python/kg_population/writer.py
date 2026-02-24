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

    def write_document(
        self,
        nodes: list,
        edges: list[Edge],
        accession_number: str,
        fiscal_year: int,
    ) -> tuple[int, int]:
        """
        Write nodes, edges, and FiscalYear wiring for one document in a single
        Neo4j session.  Returns (nodes_written, edges_written).
        """
        from collections import defaultdict

        # Group nodes by label
        nodes_by_label: dict[str, list] = defaultdict(list)
        for node in nodes:
            label = _LABEL_MAP.get(type(node))
            if label is None:
                print(f"[writer] Unknown node type: {type(node)}", file=sys.stderr)
                continue
            props = node_to_props(node)
            nodes_by_label[label].append(
                {k: v for k, v in props.items() if v is not None}
            )

        # Group edges by relation type
        edges_by_type: dict[str, list] = defaultdict(list)
        for edge in edges:
            edges_by_type[edge.relation_type.value].append({
                "subject_id":  edge.subject_id,
                "object_id":   edge.object_id,
                "filing_ref":  edge.filing_ref,
                "as_of_year":  edge.as_of_year,
                "confidence":  edge.provenance.confidence,
                "sentence_id": edge.provenance.sentence_id,
                "weight":      edge.weight,
            })

        return self._g.write_document(
            dict(nodes_by_label),
            dict(edges_by_type),
            accession_number,
            fiscal_year,
        )
