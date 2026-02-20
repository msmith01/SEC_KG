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
            f"MERGE (a)-[r:{edge.relation_type.value} {{filing_ref: $filing_ref}}]->(b) "
            f"SET r.as_of_year   = $as_of_year, "
            f"    r.confidence   = $confidence, "
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
        """Batch edge upsert."""
        for edge in edges:
            self.upsert_edge(edge)

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
