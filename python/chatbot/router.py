"""
Query router — classifies intent and extracts entities from the question.
Uses the LLM to output structured JSON, then resolves company names against
the graph.
"""
from __future__ import annotations

import json
import re
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config
from neo4j import GraphDatabase
from models.llm_client import LLMClient
from chatbot.memory import ConversationState
from chatbot.prompts import ROUTER_SYSTEM, ROUTER_TEMPLATE


# Fallback: load ticker→name map for alias resolution
def _load_ticker_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    try:
        import csv
        with open(config.TICKER_CIK_FILE) as f:
            for row in csv.DictReader(f):
                ticker = row.get("ticker", "").upper().strip()
                cik    = row.get("cik", "").strip().lstrip("0")
                if ticker and cik:
                    mapping[ticker] = cik
    except Exception:
        pass
    return mapping


_TICKER_MAP = _load_ticker_map()


class Router:
    def __init__(self, llm: LLMClient):
        self.llm = llm
        try:
            self._driver = GraphDatabase.driver(
                config.NEO4J_URI,
                auth=(config.NEO4J_USER, config.NEO4J_PASSWORD),
            )
        except Exception:
            self._driver = None

    def route(self, question: str, state: ConversationState) -> dict:
        """
        Returns a routing dict:
        {
          intent, company, cik, years, topic, cypher_hint
        }
        """
        prompt = ROUTER_TEMPLATE.format(
            context_summary=state.context_summary(),
            history=state.history_text(),
            question=question,
        )

        raw = self.llm.complete(prompt, system=ROUTER_SYSTEM, temperature=0.0)
        routing = self._parse_json(raw)

        # Resolve ticker alias to CIK if we got a ticker-like company
        routing = self._resolve_company(routing)

        # Fill blanks from conversation state
        routing = self._fill_from_context(routing, state)

        # Decide whether graph or semantic search should be primary
        routing["primary_source"] = self._detect_primary_source(routing, question)

        return routing

    def _parse_json(self, raw: str) -> dict:
        raw = raw.strip()
        # Strip markdown fences
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Try to extract first JSON object
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group())
                except Exception:
                    pass
        return {
            "intent": "company",
            "company": None,
            "cik": None,
            "years": None,
            "topic": None,
            "cypher_hint": "general company query",
        }

    def _resolve_company(self, routing: dict) -> dict:
        company = routing.get("company")
        if not company:
            return routing
        upper = company.upper().strip()

        # Step 1: ticker CSV → CIK
        if upper in _TICKER_MAP:
            routing["cik"] = _TICKER_MAP[upper]

        # Step 2: Neo4j canonical lookup — snap to exact graph name + CIK
        resolved = self._neo4j_resolve(company, routing.get("cik"))
        if resolved:
            canonical_name, cik = resolved
            routing["company"] = canonical_name
            routing["cik"] = cik

        return routing

    def _neo4j_resolve(self, term: str, cik: str | None) -> tuple[str, str] | None:
        """Look up canonical company name and CIK from Neo4j.
        Tries CIK first (exact), then ticker, then name CONTAINS.
        Returns (canonical_name, cik) or None.
        """
        if not self._driver:
            return None
        try:
            with self._driver.session(database=config.NEO4J_DATABASE) as s:
                # Prefer exact CIK match if we already have one
                if cik:
                    rows = list(s.run(
                        "MATCH (c:Company) WHERE c.cik = $cik "
                        "RETURN c.name AS name, c.cik AS cik LIMIT 1",
                        cik=str(cik)
                    ))
                    if rows:
                        return rows[0]["name"], rows[0]["cik"]
                # Fall back to ticker or name CONTAINS
                rows = list(s.run(
                    "MATCH (c:Company) "
                    "WHERE toLower(c.ticker) = toLower($term) "
                    "   OR toLower(c.name) CONTAINS toLower($term) "
                    "RETURN c.name AS name, c.cik AS cik "
                    "ORDER BY size(c.name) LIMIT 1",
                    term=term
                ))
                if rows:
                    return rows[0]["name"], rows[0]["cik"]
        except Exception:
            pass
        return None

    def _detect_primary_source(self, routing: dict, question: str) -> str:
        """Return 'semantic' for narrative/opinion/MD&A questions; 'graph' for structured queries."""
        q = question.lower()
        topic = (routing.get("topic") or "").lower()
        semantic_signals = {
            "mda", "md&a", "management discussion", "management opinion",
            "outlook", "opinion", "narrative", "tone", "sentiment",
            "what did management say", "what does management think",
            "how did they describe", "what was said about",
            "supply chain risk", "risk mention", "risk factor",
        }
        graph_signals = {
            "competitor", "competes with", "geographic", "market", "country",
            "metric", "revenue", "filing count", "how many", "which companies",
            "list", "most common", "top ", "compare",
        }
        q_semantic = sum(1 for s in semantic_signals if s in q or s in topic)
        q_graph    = sum(1 for s in graph_signals    if s in q or s in topic)
        if q_semantic > q_graph:
            return "semantic"
        return "graph"

    def _fill_from_context(self, routing: dict, state: ConversationState) -> dict:
        """If router left company/years blank, use active context."""
        if not routing.get("company") and state.active_company_name:
            routing["company"] = state.active_company_name
        if not routing.get("cik") and state.active_company_cik:
            routing["cik"] = state.active_company_cik
        if not routing.get("years"):
            if state.active_year_from:
                routing["years"] = [
                    state.active_year_from,
                    state.active_year_to or state.active_year_from,
                ]
        if not routing.get("topic") and state.active_topic:
            routing["topic"] = state.active_topic
        return routing
