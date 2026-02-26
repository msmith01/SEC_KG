"""
All prompt templates for the chatbot pipeline.
"""

# ── Graph schema fed to the Cypher-generation LLM ────────────────────────────

GRAPH_SCHEMA = """
Node labels and their key properties:
  Company          : name (string), cik (string), ticker (string), sic_code (string)
  Filing           : accession_number (string), filing_date (string), fiscal_year (int), form_type (string)
  Section          : section_type (string: "risk_factors"|"business"|"mda"), accession_number (string)
  FiscalYear       : year (int)
  RiskFactor       : summary (string), category (string), severity (string), accession_number (string)
  RiskDriver       : name (string), driver_type (string)
  RiskConsequence  : description (string)
  Mitigation       : description (string), mitigation_type (string)
  GeographicMarket : name (string), iso_code (string)
  Competitor       : name (string)
  Product          : name (string)
  BusinessSegment  : name (string), revenue_pct (float)
  FinancialMetric  : name (string), value (float), unit (string), fiscal_year (int)
  MacroFactor      : name (string), direction (string)
  ManagementOutlook: summary (string), sentiment (string), horizon (string)

Relationships (direction matters):
  (Filing)-[:FILED_BY]->(Company)
  (Filing)-[:HAS_SECTION]->(Section)
  (Filing)-[:FILED_IN]->(FiscalYear)
  (FiscalYear)-[:PRECEDES]->(FiscalYear)
  (Company)-[:HAS_RISK]->(RiskFactor)
  (RiskFactor)-[:CAUSED_BY]->(RiskDriver)
  (RiskFactor)-[:MAY_RESULT_IN]->(RiskConsequence)
  (RiskFactor)-[:MITIGATED_BY]->(Mitigation)
  (RiskFactor)-[:SUPERSEDES]->(RiskFactor)
  (RiskFactor)-[:RELATED_TO]->(RiskFactor)
  (Company)-[:OPERATES_IN]->(GeographicMarket)
  (Company)-[:COMPETES_WITH]->(Competitor)
  (Company)-[:HAS_SEGMENT]->(BusinessSegment)
  (Company)-[:OFFERS]->(Product)
  (Company)-[:HAS_OUTLOOK]->(ManagementOutlook)
  (FinancialMetric)-[:IMPACTED_BY]->(MacroFactor)

IMPORTANT NOTES:
- RiskFactor, RiskDriver, etc. only exist if LLM-mode KG population was run.
  In fast-mode (spaCy), only Company/Filing/Section/FiscalYear/Competitor/GeographicMarket/Product exist.
- Always use OPTIONAL MATCH for nodes that may not exist (RiskFactor etc.)
- Company names are UPPER CASE in the graph (e.g. "TYSON FOODS INC", "COCA COLA CO")
- Use toLower() + CONTAINS for fuzzy company name matching
"""

# ── Cypher examples fed to the generation LLM ────────────────────────────────

CYPHER_EXAMPLES = """
EXAMPLE 1 — Company's geographic market footprint:
MATCH (c:Company)-[:OPERATES_IN]->(g:GeographicMarket)
WHERE toLower(c.name) CONTAINS "henry schein"
RETURN c.name AS company, collect(DISTINCT g.name) AS markets

EXAMPLE 2 — Companies with exposure to a specific country:
MATCH (c:Company)-[:OPERATES_IN]->(g:GeographicMarket)
WHERE toLower(g.name) CONTAINS "china"
RETURN c.name AS company, c.ticker AS ticker, collect(DISTINCT g.name) AS china_markets
ORDER BY company LIMIT 50

EXAMPLE 3 — Risk factors for a company (requires LLM-mode graph):
MATCH (c:Company)-[:HAS_RISK]->(rf:RiskFactor)
WHERE toLower(c.name) CONTAINS toLower($company)
OPTIONAL MATCH (rf)-[:CAUSED_BY]->(rd:RiskDriver)
RETURN rf.summary, rf.category, rf.severity, collect(rd.name) AS drivers
ORDER BY rf.severity DESC LIMIT 20

EXAMPLE 4 — How a company's risk disclosures changed over time:
MATCH (c:Company)<-[:FILED_BY]-(f:Filing)
WHERE toLower(c.name) CONTAINS toLower($company)
MATCH (c)-[:HAS_RISK]->(rf:RiskFactor)
WHERE rf.accession_number = f.accession_number
RETURN f.fiscal_year, rf.category, count(rf) AS count
ORDER BY f.fiscal_year, rf.category

EXAMPLE 5 — Cross-company: which companies share a risk driver:
MATCH (rd:RiskDriver)<-[:CAUSED_BY]-(rf:RiskFactor)<-[:HAS_RISK]-(c:Company)
WHERE toLower(rd.name) CONTAINS toLower($topic)
RETURN c.name, count(rf) AS exposure
ORDER BY exposure DESC LIMIT 20

EXAMPLE 6 — What competitors a company mentions:
MATCH (c:Company)-[:COMPETES_WITH]->(comp:Competitor)
WHERE toLower(c.name) CONTAINS "amazon"
RETURN comp.name, count(*) AS mentions
ORDER BY mentions DESC LIMIT 20

EXAMPLE 7 — Node count overview (useful to check what's in graph):
MATCH (n) RETURN labels(n)[0] AS type, count(n) AS count ORDER BY count DESC

EXAMPLE 8 — Companies in the graph with filings:
MATCH (c:Company)<-[:FILED_BY]-(f:Filing)
RETURN c.name, c.ticker, count(f) AS filing_count
ORDER BY filing_count DESC LIMIT 30
"""

# ── Router prompt ─────────────────────────────────────────────────────────────

ROUTER_SYSTEM = """You are a query analysis assistant for a financial knowledge graph built from SEC 10-K filings.
Analyse the user's question and output ONLY a JSON object — no explanation, no markdown fences."""

ROUTER_TEMPLATE = """Conversation context so far:
{context_summary}

Recent history:
{history}

New question: {question}

Output a JSON object with these fields:
{{
  "intent": one of "company" | "temporal" | "cross_company" | "trend" | "overview" | "clarify",
  "company": company name as it would appear in SEC filings (UPPER CASE), or null,
  "cik": CIK string if known, or null,
  "years": [from_year, to_year] as integers, or null,
  "topic": short topic keyword (e.g. "supply_chain", "tariff", "cybersecurity", "revenue"), or null,
  "cypher_hint": one sentence describing what graph traversal would answer this question
}}

Rules:
- If the question says "the company" or "them" or "that", resolve it to the active company in context.
- If no year is specified, use null (the Cypher will handle it).
- For "how has X changed", use intent "temporal".
- For "which companies", use intent "cross_company".
- For "what is in the graph" or general capability questions, use intent "overview".
"""

# ── Cypher generation prompt ──────────────────────────────────────────────────

CYPHER_SYSTEM = """You are an expert Neo4j Cypher query writer for a knowledge graph of SEC 10-K filings.
Output ONLY a valid Cypher query — no explanation, no markdown fences, no comments."""

CYPHER_TEMPLATE = """Graph schema:
{schema}

Example queries:
{examples}

Task: Write a Cypher query to answer this question.
Intent: {intent}
Company: {company}
Years: {years}
Topic: {topic}
Hint: {cypher_hint}
Question: {question}

Rules:
- Use toLower() + CONTAINS for company/market name matching (names are upper case in graph)
- Use OPTIONAL MATCH for nodes that may not exist (RiskFactor, RiskDriver etc.)
- ALWAYS include c.name AS company in RETURN so results can be attributed to a company
- Use collect(DISTINCT ...) to group related values onto one row per company
- Return at most 50 rows (use LIMIT 50)
- If years are given, filter: WHERE f.fiscal_year >= {year_from} AND f.fiscal_year <= {year_to}
- Output ONLY the Cypher query, nothing else
"""

# ── Answer synthesis prompt ───────────────────────────────────────────────────

SYNTHESISER_SYSTEM = """You are a financial analyst assistant specialising in SEC 10-K filings.
Answer questions based ONLY on the provided context — graph facts and filing excerpts.
Cite sources as [Company, FY20XX] after claims. Be concise and direct.
If the data is limited or the graph doesn't have enough nodes yet, say so clearly."""

SYNTHESISER_TEMPLATE = """Question: {question}

Active context: {context_summary}

--- GRAPH FACTS ---
{graph_facts}

--- FILING EXCERPTS (semantic search) ---
{semantic_hits}

--- CONVERSATION HISTORY ---
{history}

Answer the question using the facts above. Be specific — name companies, years, figures.
If no relevant data was found in the graph, say so and describe what the graph does contain
(use the overview facts if provided). Keep the answer under 300 words unless more detail is needed.
"""
