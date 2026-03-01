"""
Pyvis subgraph visualisation panel for the SEC KG chatbot.

fetch_subgraph(routing) → (nodes, edges)
build_pyvis_html(nodes, edges) → HTML string | None
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config
from neo4j import GraphDatabase

# ── Styling ───────────────────────────────────────────────────────────────────
_COLORS = {
    "Company":          "#2196F3",
    "Filing":           "#4CAF50",
    "FiscalYear":       "#FF9800",
    "GeographicMarket": "#9C27B0",
    "Competitor":       "#F44336",
    "Section":          "#9E9E9E",
    "RiskFactor":       "#E91E63",
    "Product":          "#00BCD4",
    "FinancialMetric":  "#FFC107",
    "ManagementOutlook":"#607D8B",
}
_DEFAULT_COLOR = "#78909C"

_SIZES = {
    "Company":    30,
    "FiscalYear": 22,
    "Filing":     16,
    "Competitor": 13,
    "GeographicMarket": 13,
    "RiskFactor": 12,
}
_DEFAULT_SIZE = 10


def _label(labels: frozenset, props: dict) -> str:
    if "Company" in labels:
        return (props.get("name") or props.get("ticker") or "?")[:25]
    if "FiscalYear" in labels:
        return f"FY{props.get('year', '?')}"
    if "Filing" in labels:
        acc = props.get("accession_number") or props.get("period_of_report") or "?"
        return acc[-10:] if len(acc) > 10 else acc
    if "GeographicMarket" in labels:
        return (props.get("name") or "?")[:20]
    if "Competitor" in labels:
        return (props.get("name") or "?")[:20]
    if "Section" in labels:
        return props.get("section_type") or "Section"
    if "RiskFactor" in labels:
        desc = props.get("description") or ""
        return desc[:22] + "…" if len(desc) > 22 else desc or "Risk"
    if "FinancialMetric" in labels:
        return (props.get("name") or "Metric")[:20]
    if "ManagementOutlook" in labels:
        return "Outlook"
    return (list(labels)[0] if labels else "?")


def _color(labels: frozenset) -> str:
    for lbl in _COLORS:
        if lbl in labels:
            return _COLORS[lbl]
    return _DEFAULT_COLOR


def _size(labels: frozenset) -> int:
    for lbl in _SIZES:
        if lbl in labels:
            return _SIZES[lbl]
    return _DEFAULT_SIZE


def _tooltip(labels: frozenset, props: dict) -> str:
    lines = [f"[{', '.join(sorted(labels))}]"]
    for k, v in props.items():
        if v is not None and not isinstance(v, (dict, list)):
            lines.append(f"{k}: {str(v)[:80]}")
    return "\n".join(lines[:10])


# ── Subgraph fetch ─────────────────────────────────────────────────────────────

def fetch_subgraph(routing: dict) -> tuple[list[dict], list[dict]]:
    """
    Query Neo4j for a context-relevant subgraph based on the router output.
    Returns (nodes_list, edges_list).
    Each node: {id, label, color, size, title}
    Each edge: {from, to, label}
    """
    cik     = routing.get("cik")
    company = routing.get("company")
    years   = routing.get("years") or []
    year_from = years[0] if years else None
    year_to   = (years[1] if len(years) > 1 else year_from) if years else None

    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def _add_node(n) -> str:
        eid = n.element_id
        if eid not in nodes:
            lbls  = frozenset(n.labels)
            props = dict(n.items())
            nodes[eid] = {
                "id":    eid,
                "label": _label(lbls, props),
                "color": _color(lbls),
                "size":  _size(lbls),
                "title": _tooltip(lbls, props),
            }
        return eid

    def _add_rel(rel):
        s = _add_node(rel.start_node)
        e = _add_node(rel.end_node)
        edges.append({"from": s, "to": e, "label": rel.type})

    try:
        driver = GraphDatabase.driver(
            config.NEO4J_URI,
            auth=(config.NEO4J_USER, config.NEO4J_PASSWORD),
        )
        with driver.session(database=config.NEO4J_DATABASE) as sess:
            if cik or company:
                params: dict = {}
                if cik:
                    where = "c.cik = $cik"
                    params["cik"] = str(cik)
                else:
                    where = "toLower(c.name) CONTAINS toLower($company)"
                    params["company"] = company

                year_clause = ""
                if year_from:
                    params.update({"year_from": year_from, "year_to": year_to or year_from})
                    year_clause = "AND fy.year >= $year_from AND fy.year <= $year_to"

                # Company → Filing → FiscalYear
                res = sess.run(
                    f"MATCH (c:Company)<-[r1:FILED_BY]-(f:Filing)-[r2:FILED_IN]->(fy:FiscalYear) "
                    f"WHERE {where} {year_clause} "
                    f"WITH c, r1, f, r2, fy ORDER BY fy.year LIMIT 10 "
                    f"RETURN c, r1, f, r2, fy",
                    **params,
                )
                for rec in res:
                    _add_node(rec["c"])
                    _add_node(rec["f"])
                    _add_node(rec["fy"])
                    _add_rel(rec["r1"])
                    _add_rel(rec["r2"])

                # Competitor links
                res2 = sess.run(
                    f"MATCH (c:Company)-[r:COMPETES_WITH]->(comp:Competitor) "
                    f"WHERE {where} "
                    f"RETURN c, r, comp LIMIT 12",
                    **params,
                )
                for rec in res2:
                    _add_node(rec["c"])
                    _add_node(rec["comp"])
                    _add_rel(rec["r"])

                # Geographic markets
                res3 = sess.run(
                    f"MATCH (c:Company)<-[:FILED_BY]-(f:Filing)-[r:OPERATES_IN]->(geo:GeographicMarket) "
                    f"WHERE {where} {year_clause} "
                    f"WITH c, f, r, geo LIMIT 15 "
                    f"RETURN c, f, r, geo",
                    **params,
                )
                for rec in res3:
                    _add_node(rec["c"])
                    _add_node(rec["f"])
                    _add_node(rec["geo"])
                    _add_rel(rec["r"])

            else:
                # Overview: sample of companies with filings
                res = sess.run(
                    "MATCH (c:Company)<-[r1:FILED_BY]-(f:Filing)-[r2:FILED_IN]->(fy:FiscalYear) "
                    "WITH c, r1, f, r2, fy ORDER BY fy.year DESC LIMIT 25 "
                    "RETURN c, r1, f, r2, fy"
                )
                for rec in res:
                    _add_node(rec["c"])
                    _add_node(rec["f"])
                    _add_node(rec["fy"])
                    _add_rel(rec["r1"])
                    _add_rel(rec["r2"])

        driver.close()

    except Exception:
        return [], []

    return list(nodes.values()), edges


# ── Pyvis render ──────────────────────────────────────────────────────────────

_PYVIS_OPTIONS = """{
  "physics": {
    "barnesHut": {
      "gravitationalConstant": -8000,
      "centralGravity": 0.3,
      "springLength": 130,
      "springConstant": 0.04,
      "damping": 0.09
    },
    "stabilization": {"iterations": 120, "fit": true}
  },
  "edges": {
    "smooth": {"type": "dynamic"},
    "font": {"size": 10, "color": "#aaaaaa"},
    "color": {"color": "#555555", "highlight": "#888888"}
  },
  "interaction": {
    "hover": true,
    "tooltipDelay": 100,
    "navigationButtons": true,
    "keyboard": {"enabled": true}
  },
  "nodes": {
    "borderWidth": 1,
    "borderWidthSelected": 3,
    "font": {"size": 11}
  }
}"""


def build_pyvis_html(nodes: list[dict], edges: list[dict]) -> str | None:
    """
    Render nodes/edges into a self-contained pyvis HTML string.
    Returns None if there's nothing to render or pyvis is unavailable.
    """
    if not nodes:
        return None
    try:
        from pyvis.network import Network
    except ImportError:
        return None

    net = Network(
        height="460px",
        width="100%",
        bgcolor="#1a1a2e",
        font_color="#e0e0e0",
        directed=True,
        notebook=False,
    )
    net.set_options(_PYVIS_OPTIONS)

    for n in nodes:
        net.add_node(
            n["id"],
            label=n["label"],
            color=n["color"],
            size=n["size"],
            title=n.get("title", ""),
        )

    for e in edges:
        net.add_edge(
            e["from"],
            e["to"],
            label=e["label"],
            arrows="to",
        )

    with tempfile.NamedTemporaryFile(
        suffix=".html", delete=False, mode="w", encoding="utf-8"
    ) as f:
        tmppath = f.name
    try:
        net.save_graph(tmppath)
        with open(tmppath, encoding="utf-8") as f:
            html = f.read()
        return html
    finally:
        try:
            os.unlink(tmppath)
        except Exception:
            pass
