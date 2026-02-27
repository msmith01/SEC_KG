"""
Neo4j schema management: constraints, indexes, and the graph writer.

The schema is idempotent — safe to run on an existing database.

Usage:
    from ontology.neo4j_schema import Neo4jGraph

    g = Neo4jGraph()
    g.apply_schema()              # create constraints + indexes
    g.upsert_node("Company", {"node_id": "2488", "name": "AMD", ...})
    g.upsert_edge(edge)
    g.close()
"""

from __future__ import annotations

import sys
import os
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config
from ontology.nodes import (
    BusinessSegment, Company, Competitor, CustomerSegment,
    Driver, Filing, FinancialMetric, FinancialPeriod, FiscalYear,
    GeographicMarket, MacroFactor, ManagementOutlook,
    Mitigation, Product, Provenance, Regulation,
    RiskConsequence, RiskDriver, RiskFactor, Section,
)
from ontology.relations import Edge


# ── Relation endpoint labels ───────────────────────────────────────────────────
#
# Maps each RelationType value → (source_label, target_label).
# Used in write_document to add label hints to MATCH patterns so that
# Neo4j can use the per-label uniqueness-constraint indexes instead of
# doing a full node_id scan across all labels.

_REL_LABELS: dict[str, tuple[str, str]] = {
    "FILED_BY":        ("Filing",            "Company"),
    "HAS_SECTION":     ("Filing",            "Section"),
    "FILED_IN":        ("Filing",            "FiscalYear"),
    "PRECEDES":        ("FiscalYear",        "FiscalYear"),
    "HAS_SEGMENT":     ("Company",           "BusinessSegment"),
    "OFFERS":          ("Company",           "Product"),
    "OPERATES_IN":     ("Company",           "GeographicMarket"),
    "TARGETS":         ("Company",           "CustomerSegment"),
    "COMPETES_WITH":   ("Company",           "Competitor"),
    "SUBJECT_TO":      ("Company",           "Regulation"),
    "INCLUDES":        ("BusinessSegment",   "Product"),
    "HAS_RISK":        ("Company",           "RiskFactor"),
    "CAUSED_BY":       ("RiskFactor",        "RiskDriver"),
    "MAY_RESULT_IN":   ("RiskFactor",        "RiskConsequence"),
    "MITIGATED_BY":    ("RiskFactor",        "Mitigation"),
    "RELATED_TO":      ("RiskFactor",        "RiskFactor"),
    "SUPERSEDES":      ("RiskFactor",        "RiskFactor"),
    "REPORTS":         ("Company",           "FinancialMetric"),
    "ATTRIBUTED_TO":   ("FinancialMetric",   "BusinessSegment"),
    "DRIVEN_BY":       ("FinancialMetric",   "Driver"),
    "IMPACTED_BY":     ("FinancialMetric",   "MacroFactor"),
    "HAS_OUTLOOK":     ("Company",           "ManagementOutlook"),
    "REFERENCES":      ("ManagementOutlook", "FinancialMetric"),
    "AFFECTS":         ("RiskFactor",        "BusinessSegment"),
    "MATERIALISED_AS": ("RiskFactor",        "FinancialMetric"),
    "CITED_IN":        ("MacroFactor",       "RiskFactor"),
    "REPORTED_IN":     ("BusinessSegment",   "FinancialMetric"),
}


# ── Constraint / index definitions ────────────────────────────────────────────
#
# Each tuple: (node_label, property_name)
# A uniqueness constraint implies an index in Neo4j 5+.

UNIQUENESS_CONSTRAINTS = [
    ("FiscalYear",        "node_id"),
    ("Company",           "node_id"),
    ("Filing",            "node_id"),
    ("Section",           "node_id"),
    ("BusinessSegment",   "node_id"),
    ("Product",           "node_id"),
    ("GeographicMarket",  "node_id"),
    ("CustomerSegment",   "node_id"),
    ("Competitor",        "node_id"),
    ("Regulation",        "node_id"),
    ("RiskFactor",        "node_id"),
    ("RiskDriver",        "node_id"),
    ("RiskConsequence",   "node_id"),
    ("Mitigation",        "node_id"),
    ("FinancialPeriod",   "node_id"),
    ("FinancialMetric",   "node_id"),
    ("Driver",            "node_id"),
    ("MacroFactor",       "node_id"),
    ("ManagementOutlook", "node_id"),
]

ADDITIONAL_INDEXES = [
    ("FiscalYear",      "year"),
    ("Company",         "cik"),
    ("Company",         "ticker"),
    ("Filing",          "accession_number"),
    ("RiskFactor",      "cik"),
    ("RiskFactor",      "as_of_year"),
    ("FinancialMetric", "cik"),
    ("FinancialMetric", "as_of_year"),
]


# ── Neo4j driver wrapper ──────────────────────────────────────────────────────

class Neo4jGraph:
    """
    Thin wrapper around the official neo4j Python driver.
    All writes use MERGE for idempotency.
    """

    def __init__(
        self,
        uri:      Optional[str] = None,
        user:     Optional[str] = None,
        password: Optional[str] = None,
        database: Optional[str] = None,
    ):
        from neo4j import GraphDatabase
        self._driver = GraphDatabase.driver(
            uri      or config.NEO4J_URI,
            auth=(
                user     or config.NEO4J_USER,
                password or config.NEO4J_PASSWORD,
            ),
        )
        self._database = database or config.NEO4J_DATABASE

    # ── Schema ────────────────────────────────────────────────────────────────

    def apply_schema(self) -> None:
        """Create all uniqueness constraints and indexes (idempotent)."""
        with self._driver.session(database=self._database) as session:
            for label, prop in UNIQUENESS_CONSTRAINTS:
                name = f"uq_{label.lower()}_{prop}"
                session.run(
                    f"CREATE CONSTRAINT {name} IF NOT EXISTS "
                    f"FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
                )

            for label, prop in ADDITIONAL_INDEXES:
                name = f"idx_{label.lower()}_{prop}"
                session.run(
                    f"CREATE INDEX {name} IF NOT EXISTS "
                    f"FOR (n:{label}) ON (n.{prop})"
                )
        print(f"[neo4j] Schema applied: "
              f"{len(UNIQUENESS_CONSTRAINTS)} constraints, "
              f"{len(ADDITIONAL_INDEXES)} indexes.")
        self.setup_fiscal_years()

    def setup_fiscal_years(self, start: int = 1993, end: int = 2027) -> None:
        """
        Pre-create all FiscalYear nodes and PRECEDES chain for years [start, end].

        Called once during schema setup and again before a parallel run.
        Pre-creating these nodes eliminates the most common source of deadlock
        in parallel KG population: concurrent MERGE on the PRECEDES relationship
        locks both FiscalYear endpoints simultaneously across all workers.
        """
        with self._driver.session(database=self._database) as session:
            for year in range(start, end + 1):
                session.run(
                    "MERGE (n:FiscalYear {node_id: $id}) SET n.year = $year",
                    id=f"fy_{year}", year=year,
                )
            for year in range(start, end):
                session.run(
                    "MATCH (prev:FiscalYear {node_id: $prev_id}) "
                    "MATCH (curr:FiscalYear {node_id: $curr_id}) "
                    "MERGE (prev)-[:PRECEDES]->(curr)",
                    prev_id=f"fy_{year}", curr_id=f"fy_{year + 1}",
                )
        print(f"[neo4j] FiscalYear nodes {start}–{end} and PRECEDES chain ready.")

    # ── Node upsert ───────────────────────────────────────────────────────────

    def upsert_node(self, label: str, props: dict[str, Any]) -> None:
        """
        MERGE on node_id, then SET all properties.
        Idempotent — safe to call repeatedly with the same data.
        """
        cypher = (
            f"MERGE (n:{label} {{node_id: $node_id}}) "
            f"SET n += $props"
        )
        props_clean = {k: v for k, v in props.items() if v is not None}
        with self._driver.session(database=self._database) as session:
            session.run(cypher, node_id=props["node_id"], props=props_clean)

    def upsert_nodes(self, label: str, props_list: list[dict[str, Any]]) -> None:
        """Batch upsert — more efficient than individual calls for large loads."""
        cypher = (
            f"UNWIND $batch AS row "
            f"MERGE (n:{label} {{node_id: row.node_id}}) "
            f"SET n += row"
        )
        batch = [{k: v for k, v in p.items() if v is not None} for p in props_list]
        with self._driver.session(database=self._database) as session:
            session.run(cypher, batch=batch)

    # ── Edge upsert ───────────────────────────────────────────────────────────

    def upsert_edge(self, edge: Edge) -> None:
        """
        MERGE the relationship between two nodes.
        Uniqueness is on (subject_id, relation_type, object_id, filing_ref).
        """
        cypher = (
            f"MATCH (a {{node_id: $subject_id}}) "
            f"MATCH (b {{node_id: $object_id}}) "
            f"MERGE (a)-[r:{edge.relation_type.value}]->(b) "
            f"SET r.as_of_year   = $as_of_year, "
            f"    r.confidence   = $confidence, "
            f"    r.filing_ref   = $filing_ref, "
            f"    r.sentence_id  = $sentence_id, "
            f"    r.weight       = $weight"
        )
        with self._driver.session(database=self._database) as session:
            session.run(
                cypher,
                subject_id  = edge.subject_id,
                object_id   = edge.object_id,
                filing_ref  = edge.filing_ref,
                as_of_year  = edge.as_of_year,
                confidence  = edge.provenance.confidence,
                sentence_id = edge.provenance.sentence_id,
                weight      = edge.weight,
            )

    def upsert_edges(self, edges: list[Edge]) -> None:
        """Batch edge upsert — groups by relation type and uses UNWIND."""
        from collections import defaultdict
        by_type: dict[str, list[Edge]] = defaultdict(list)
        for edge in edges:
            by_type[edge.relation_type.value].append(edge)

        with self._driver.session(database=self._database) as session:
            for rel_type, rel_edges in by_type.items():
                labels = _REL_LABELS.get(rel_type)
                if labels:
                    src_lbl, tgt_lbl = labels
                    cypher = (
                        f"UNWIND $batch AS row "
                        f"MATCH (a:{src_lbl} {{node_id: row.subject_id}}) "
                        f"MATCH (b:{tgt_lbl} {{node_id: row.object_id}}) "
                        f"MERGE (a)-[r:{rel_type}]->(b) "
                        f"SET r.as_of_year  = row.as_of_year, "
                        f"    r.confidence  = row.confidence, "
                        f"    r.filing_ref  = row.filing_ref, "
                        f"    r.sentence_id = row.sentence_id, "
                        f"    r.weight      = row.weight"
                    )
                else:
                    cypher = (
                        f"UNWIND $batch AS row "
                        f"MATCH (a {{node_id: row.subject_id}}) "
                        f"MATCH (b {{node_id: row.object_id}}) "
                        f"MERGE (a)-[r:{rel_type}]->(b) "
                        f"SET r.as_of_year  = row.as_of_year, "
                        f"    r.confidence  = row.confidence, "
                        f"    r.filing_ref  = row.filing_ref, "
                        f"    r.sentence_id = row.sentence_id, "
                        f"    r.weight      = row.weight"
                    )
                batch = [
                    {
                        "subject_id":  e.subject_id,
                        "object_id":   e.object_id,
                        "filing_ref":  e.filing_ref,
                        "as_of_year":  e.as_of_year,
                        "confidence":  e.provenance.confidence,
                        "sentence_id": e.provenance.sentence_id,
                        "weight":      e.weight,
                    }
                    for e in rel_edges
                ]
                session.run(cypher, batch=batch)

    def write_document(
        self,
        nodes_by_label: dict[str, list[dict[str, Any]]],
        edges_by_type:  dict[str, list[dict[str, Any]]],
        accession_number: str,
        fiscal_year: int,
    ) -> tuple[int, int]:
        """
        Write all nodes, edges, and FiscalYear wiring for one document in a
        single explicit transaction — eliminates per-call session overhead and
        allows the Neo4j driver to retry automatically on TransientError
        (deadlock), which can occur when multiple workers MERGE shared nodes
        (Company, FiscalYear) concurrently.
        Returns (nodes_written, edges_written).
        """
        fy_id   = f"fy_{fiscal_year}"
        prev_id = f"fy_{fiscal_year - 1}"
        n_nodes = sum(len(v) for v in nodes_by_label.values())
        n_edges = sum(len(v) for v in edges_by_type.values())

        with self._driver.session(database=self._database) as session:
            # Nodes — one UNWIND per label
            for label, batch in nodes_by_label.items():
                session.run(
                    f"UNWIND $batch AS row "
                    f"MERGE (n:{label} {{node_id: row.node_id}}) "
                    f"SET n += row",
                    batch=batch,
                )

            # Edges — one UNWIND per relation type, with label hints so Neo4j
            # uses the per-label uniqueness-constraint indexes instead of
            # scanning all nodes by node_id.
            for rel_type, batch in edges_by_type.items():
                labels = _REL_LABELS.get(rel_type)
                if labels:
                    src_lbl, tgt_lbl = labels
                    cypher = (
                        f"UNWIND $batch AS row "
                        f"MATCH (a:{src_lbl} {{node_id: row.subject_id}}) "
                        f"MATCH (b:{tgt_lbl} {{node_id: row.object_id}}) "
                        f"MERGE (a)-[r:{rel_type}]->(b) "
                        f"SET r.as_of_year  = row.as_of_year, "
                        f"    r.confidence  = row.confidence, "
                        f"    r.filing_ref  = row.filing_ref, "
                        f"    r.sentence_id = row.sentence_id, "
                        f"    r.weight      = row.weight"
                    )
                else:
                    cypher = (
                        f"UNWIND $batch AS row "
                        f"MATCH (a {{node_id: row.subject_id}}) "
                        f"MATCH (b {{node_id: row.object_id}}) "
                        f"MERGE (a)-[r:{rel_type}]->(b) "
                        f"SET r.as_of_year  = row.as_of_year, "
                        f"    r.confidence  = row.confidence, "
                        f"    r.filing_ref  = row.filing_ref, "
                        f"    r.sentence_id = row.sentence_id, "
                        f"    r.weight      = row.weight"
                    )
                session.run(cypher, batch=batch)

            # Filing → FiscalYear edge
            # FiscalYear nodes are pre-created by setup_fiscal_years().
            session.run(
                "MATCH (f:Filing {node_id: $acc}) "
                "MATCH (fy:FiscalYear {node_id: $fy_id}) "
                "MERGE (f)-[:FILED_IN]->(fy)",
                acc=accession_number, fy_id=fy_id,
            )

        return n_nodes, n_edges

    # ── Queries ───────────────────────────────────────────────────────────────

    def query(self, cypher: str, **params) -> list[dict]:
        """Run an arbitrary read query and return records as dicts."""
        with self._driver.session(database=self._database) as session:
            result = session.run(cypher, **params)
            return [dict(record) for record in result]

    def node_count(self) -> int:
        rows = self.query("MATCH (n) RETURN count(n) AS cnt")
        return rows[0]["cnt"] if rows else 0

    def edge_count(self) -> int:
        rows = self.query("MATCH ()-[r]->() RETURN count(r) AS cnt")
        return rows[0]["cnt"] if rows else 0

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        self._driver.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# ── Helper: serialize a Pydantic node to a flat dict for Neo4j ───────────────

def node_to_props(node) -> dict[str, Any]:
    """
    Convert a Pydantic ontology node to a flat property dict suitable for Neo4j.
    Nested Provenance objects are flattened with a 'prov_' prefix.
    Dates are converted to ISO strings.
    """
    data = node.model_dump()
    flat: dict[str, Any] = {}

    for k, v in data.items():
        if isinstance(v, dict):
            # Flatten nested objects (e.g. provenance)
            for nk, nv in v.items():
                flat[f"{k}_{nk}"] = _coerce(nv)
        else:
            flat[k] = _coerce(v)

    return flat


def _coerce(v: Any) -> Any:
    """Convert types that Neo4j can't handle natively."""
    from datetime import date
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, list):
        return [_coerce(i) for i in v]
    return v
