"""
Text-to-Cypher pipeline: question → Cypher → Neo4j → structured results.
"""
from __future__ import annotations

import re
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config
from neo4j import GraphDatabase
from models.llm_client import LLMClient
from chatbot.prompts import (
    GRAPH_SCHEMA, CYPHER_EXAMPLES,
    CYPHER_SYSTEM, CYPHER_TEMPLATE,
)


# Cypher queries that could mutate data — block them
_FORBIDDEN = re.compile(
    r"\b(DELETE|DETACH|DROP|CREATE|MERGE|SET|REMOVE|CALL\s+apoc\.periodic)\b",
    re.IGNORECASE,
)


class GraphQA:
    def __init__(self, llm: LLMClient):
        self.llm = llm
        self.driver = GraphDatabase.driver(
            config.NEO4J_URI,
            auth=(config.NEO4J_USER, config.NEO4J_PASSWORD),
        )

    def close(self):
        self.driver.close()

    def run(
        self,
        question: str,
        routing: dict,
    ) -> tuple[str | None, list[dict]]:
        """
        Generate and execute a Cypher query.
        Returns (cypher_string, list_of_row_dicts).
        """
        cypher = self._generate_cypher(question, routing)
        if not cypher:
            return None, []

        rows = self._execute(cypher)

        # On error: retry once with LLM fix
        if rows and rows[0].get("error"):
            fixed = self._fix_cypher(cypher, rows[0]["error"])
            if fixed:
                rows = self._execute(fixed)
                cypher = fixed

        # On empty results: try to explain what IS available for this company/year
        if not rows or (rows and rows[0].get("error")):
            fallback = self._diagnostic_fallback(routing)
            return cypher, fallback

        return cypher, rows

    # ── Cypher generation ─────────────────────────────────────────────────────

    def _generate_cypher(self, question: str, routing: dict) -> str | None:
        years = routing.get("years") or []
        year_from = years[0] if len(years) > 0 else "any"
        year_to   = years[1] if len(years) > 1 else "any"

        prompt = CYPHER_TEMPLATE.format(
            schema=GRAPH_SCHEMA,
            examples=CYPHER_EXAMPLES,
            intent=routing.get("intent", ""),
            company=routing.get("company") or "any",
            cik=routing.get("cik") or "any",
            years=f"{year_from}–{year_to}" if years else "any",
            topic=routing.get("topic") or "any",
            cypher_hint=routing.get("cypher_hint", ""),
            question=question,
            year_from=year_from,
            year_to=year_to,
        )

        raw = self.llm.complete(prompt, system=CYPHER_SYSTEM)
        cypher = self._clean_cypher(raw)
        return cypher if self._is_safe(cypher) else None

    def _fix_cypher(self, cypher: str, error: str) -> str | None:
        """Ask the LLM to fix a broken Cypher query. Returns fixed query or None."""
        prompt = (
            f"This Cypher query failed with an error:\n\n"
            f"Query:\n{cypher}\n\n"
            f"Error: {error}\n\n"
            f"Fix the query. Output only the corrected Cypher, nothing else."
        )
        raw = self.llm.complete(prompt, system=CYPHER_SYSTEM)
        fixed = self._clean_cypher(raw)
        return fixed if fixed and self._is_safe(fixed) and fixed != cypher else None

    def _diagnostic_fallback(self, routing: dict) -> list[dict]:
        """When the main query returns nothing, return targeted diagnostic info.
        If we know the company, show which years they have filings for.
        Otherwise fall back to a graph-wide node count overview.
        """
        cik = routing.get("cik")
        company = routing.get("company")

        if cik:
            # Show what years this specific company has in the graph
            years_rows = self._execute_params(
                "MATCH (c:Company)<-[:FILED_BY]-(f:Filing)-[:FILED_IN]->(fy:FiscalYear) "
                "WHERE c.cik = $cik "
                "RETURN c.name AS company, c.ticker AS ticker, "
                "collect(DISTINCT fy.year) AS available_years",
                {"cik": str(cik)},
            )
            if years_rows and not years_rows[0].get("error"):
                return [{"_diagnostic": True, "_type": "available_years", **r} for r in years_rows]
        elif company:
            years_rows = self._execute_params(
                "MATCH (c:Company)<-[:FILED_BY]-(f:Filing)-[:FILED_IN]->(fy:FiscalYear) "
                "WHERE toLower(c.name) CONTAINS toLower($company) "
                "RETURN c.name AS company, c.ticker AS ticker, "
                "collect(DISTINCT fy.year) AS available_years",
                {"company": company},
            )
            if years_rows and not years_rows[0].get("error"):
                return [{"_diagnostic": True, "_type": "available_years", **r} for r in years_rows]

        # No company — generic overview
        overview = self._execute(
            "MATCH (n) RETURN labels(n)[0] AS type, count(n) AS count ORDER BY count DESC"
        )
        return [{"_overview": True, **r} for r in overview]

    def _clean_cypher(self, raw: str) -> str:
        """Strip markdown fences and whitespace."""
        raw = raw.strip()
        raw = re.sub(r"^```(?:cypher)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
        return raw.strip()

    def _is_safe(self, cypher: str) -> bool:
        if _FORBIDDEN.search(cypher):
            return False
        if not re.match(r"^\s*(MATCH|CALL|WITH|RETURN|OPTIONAL)", cypher, re.IGNORECASE):
            return False
        return True

    # ── Execution ─────────────────────────────────────────────────────────────

    def _execute(self, cypher: str) -> list[dict]:
        try:
            with self.driver.session(database=config.NEO4J_DATABASE) as s:
                result = s.run(cypher)
                return [dict(r) for r in result][:50]
        except Exception as e:
            return [{"error": str(e)}]

    def _execute_params(self, cypher: str, params: dict) -> list[dict]:
        try:
            with self.driver.session(database=config.NEO4J_DATABASE) as s:
                result = s.run(cypher, **params)
                return [dict(r) for r in result][:50]
        except Exception as e:
            return [{"error": str(e)}]


def format_graph_rows(rows: list[dict]) -> str:
    """Convert Neo4j row dicts to a readable bullet list for the synthesiser."""
    if not rows:
        return "(no graph results)"
    if rows and rows[0].get("error"):
        return f"(graph query error: {rows[0]['error']})"

    overview_rows    = [r for r in rows if r.get("_overview")]
    diagnostic_rows  = [r for r in rows if r.get("_diagnostic")]
    data_rows        = [r for r in rows if not r.get("_overview") and not r.get("_diagnostic")]

    lines = []

    if diagnostic_rows:
        dtype = diagnostic_rows[0].get("_type")
        if dtype == "available_years":
            lines.append("No results found for that query. Available data for this company:")
            for r in diagnostic_rows:
                company = r.get("company", "?")
                ticker  = r.get("ticker", "")
                years   = sorted(r.get("available_years") or [])
                years_str = ", ".join(str(y) for y in years) if years else "none"
                lines.append(f"  {company} ({ticker}): filings available for years {years_str}")

    if overview_rows:
        lines.append("Graph currently contains:")
        for r in overview_rows:
            lines.append(f"  - {r.get('type', '?')}: {r.get('count', '?')} nodes")

    for r in data_rows[:30]:
        clean = {k: v for k, v in r.items() if v is not None and k != "_overview"}
        lines.append("• " + "  |  ".join(f"{k}: {v}" for k, v in clean.items()))

    return "\n".join(lines) if lines else "(no graph results)"
