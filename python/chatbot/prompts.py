"""
All prompt templates for the chatbot pipeline.
"""

# ── Graph schema fed to the Cypher-generation LLM ────────────────────────────

GRAPH_SCHEMA = """
Node labels and key properties (* = actually populated in current graph):
  Company*          : name (string, UPPER CASE), cik (string), ticker (string)
  Filing*           : accession_number (string), cik (string), filing_date (string), form_type (string)
                      NOTE: Filing has NO fiscal_year property — get year via FILED_IN → FiscalYear
  Section*          : section_type (string: "risk_factors"|"business"|"mda"),
                      accession (string, links to Filing.accession_number), word_count (int)
  FiscalYear*       : year (int)
  GeographicMarket* : name (string), iso_code (string), level (string)
  Competitor*       : name (string)
  ManagementOutlook*: text (string), sentiment (string: "positive"|"negative"|"neutral"),
                      horizon (string), accession (string, links to Filing.accession_number), cik (string)
  FinancialMetric*  : name (string), as_of_year (int), direction (string),
                      accession (string, links to Filing.accession_number), cik (string)
  RiskFactor        : [LLM mode only — no nodes yet] summary, category, severity, accession_number
  RiskDriver        : [LLM mode only — no nodes yet] name, driver_type
  RiskConsequence   : [LLM mode only — no nodes yet] description
  Mitigation        : [LLM mode only — no nodes yet] description, mitigation_type
  Product           : [LLM mode only — no nodes yet] name
  BusinessSegment   : [LLM mode only — no nodes yet] name, revenue_pct
  MacroFactor       : [LLM mode only — no nodes yet] name, direction

Relationships (direction matters):
  (Filing)-[:FILED_BY]->(Company)
  (Filing)-[:HAS_SECTION]->(Section)
  (Filing)-[:FILED_IN]->(FiscalYear)
  (FiscalYear)-[:PRECEDES]->(FiscalYear)
  (Company)-[:OPERATES_IN]->(GeographicMarket)
  (Company)-[:COMPETES_WITH]->(Competitor)
  (Company)-[:HAS_OUTLOOK]->(ManagementOutlook)
  (Company)-[:HAS_RISK]->(RiskFactor)         [LLM mode only]
  (RiskFactor)-[:CAUSED_BY]->(RiskDriver)     [LLM mode only]
  (RiskFactor)-[:MAY_RESULT_IN]->(RiskConsequence) [LLM mode only]
  (RiskFactor)-[:MITIGATED_BY]->(Mitigation)  [LLM mode only]
  (Company)-[:HAS_SEGMENT]->(BusinessSegment) [LLM mode only]
  (Company)-[:OFFERS]->(Product)              [LLM mode only]

YEAR FILTERING — Filing has no fiscal_year property. Always filter year via FiscalYear node:
  MATCH (f:Filing)-[:FILED_IN]->(fy:FiscalYear) WHERE fy.year = 2022
  For ManagementOutlook/FinancialMetric/Section, join via accession:
  MATCH (f:Filing) WHERE f.accession_number = mo.accession
  MATCH (f)-[:FILED_IN]->(fy:FiscalYear) WHERE fy.year = 2022

COMPANY MATCHING:
  If cik is provided: use exact match WHERE c.cik = "<cik>"  (preferred — no fuzzy needed)
  If only name available: WHERE toLower(c.name) CONTAINS toLower("<name>")
  If only ticker available: WHERE toLower(c.ticker) = toLower("<ticker>")
"""

# ── Cypher examples fed to the generation LLM ────────────────────────────────

CYPHER_EXAMPLES = """
EXAMPLE 1 — Company's geographic market footprint (by CIK — preferred):
MATCH (c:Company)-[:OPERATES_IN]->(g:GeographicMarket)
WHERE c.cik = "1096752"
RETURN c.name AS company, collect(DISTINCT g.name) AS markets

EXAMPLE 2 — Companies with exposure to a specific country:
MATCH (c:Company)-[:OPERATES_IN]->(g:GeographicMarket)
WHERE toLower(g.name) CONTAINS "china"
RETURN c.name AS company, c.ticker AS ticker, collect(DISTINCT g.name) AS china_markets
ORDER BY company LIMIT 50

EXAMPLE 3 — MD&A outlook text for a company in a specific year:
MATCH (c:Company)-[:HAS_OUTLOOK]->(mo:ManagementOutlook)
WHERE c.cik = "1318605"
MATCH (f:Filing)-[:FILED_IN]->(fy:FiscalYear)
WHERE f.accession_number = mo.accession AND fy.year = 2022
RETURN mo.text AS outlook, mo.sentiment, mo.horizon, fy.year AS year
ORDER BY mo.sentiment LIMIT 30

EXAMPLE 4 — MD&A outlook across all years for a company (temporal):
MATCH (c:Company)-[:HAS_OUTLOOK]->(mo:ManagementOutlook)
WHERE c.cik = "1318605"
MATCH (f:Filing)-[:FILED_IN]->(fy:FiscalYear)
WHERE f.accession_number = mo.accession
RETURN fy.year AS year, mo.sentiment, mo.text AS outlook
ORDER BY fy.year DESC LIMIT 50

EXAMPLE 5 — What years a company has filings for (always run this when year query returns empty):
MATCH (c:Company)<-[:FILED_BY]-(f:Filing)-[:FILED_IN]->(fy:FiscalYear)
WHERE c.cik = "1318605"
RETURN c.name AS company, collect(DISTINCT fy.year) AS available_years

EXAMPLE 6 — Companies in the graph with filing counts:
MATCH (c:Company)<-[:FILED_BY]-(f:Filing)
RETURN c.name AS company, c.ticker AS ticker, count(f) AS filing_count
ORDER BY filing_count DESC LIMIT 30

EXAMPLE 7 — What competitors a company mentions:
MATCH (c:Company)-[:COMPETES_WITH]->(comp:Competitor)
WHERE c.cik = "1018724"
RETURN comp.name AS competitor, count(*) AS mentions
ORDER BY mentions DESC LIMIT 20

EXAMPLE 8 — Companies with China/tariff exposure (cross-company):
MATCH (c:Company)-[:OPERATES_IN]->(g:GeographicMarket)
WHERE toLower(g.name) CONTAINS "china"
RETURN c.name AS company, c.ticker AS ticker, collect(DISTINCT g.name) AS markets
ORDER BY company LIMIT 50

EXAMPLE 9 — Node count overview:
MATCH (n) RETURN labels(n)[0] AS type, count(n) AS count ORDER BY count DESC

EXAMPLE 10 — Business description section text retrieval (for narrative questions):
MATCH (c:Company)<-[:FILED_BY]-(f:Filing)-[:FILED_IN]->(fy:FiscalYear)
WHERE c.cik = "1318605" AND fy.year = 2022
MATCH (f)-[:HAS_SECTION]->(sec:Section)
WHERE sec.section_type = "business"
RETURN c.name AS company, fy.year AS year, sec.accession AS accession, sec.word_count AS words

EXAMPLE 11 — Risk factor section retrieval (LLM nodes absent — use Section lookup):
MATCH (c:Company)<-[:FILED_BY]-(f:Filing)-[:FILED_IN]->(fy:FiscalYear)
WHERE c.cik = "1318605" AND fy.year = 2022
MATCH (f)-[:HAS_SECTION]->(sec:Section)
WHERE sec.section_type = "risk_factors"
RETURN c.name AS company, fy.year AS year, sec.accession AS accession, sec.word_count AS words

EXAMPLE 12 — FinancialMetric for a company in a year:
MATCH (fm:FinancialMetric)
WHERE fm.cik = "1318605" AND fm.as_of_year = 2022
RETURN fm.name AS metric, fm.direction, fm.as_of_year AS year
LIMIT 30
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
CIK: {cik}
Years: {years}
Topic: {topic}
Hint: {cypher_hint}
Question: {question}

Rules:
- COMPANY MATCHING: if cik is not "any", use WHERE c.cik = "{cik}" — exact, no fuzzy needed.
  Only use toLower(c.name) CONTAINS when cik is "any" and name is provided.
- YEAR FILTERING: Filing has NO fiscal_year property. Always join:
  MATCH (f:Filing)-[:FILED_IN]->(fy:FiscalYear) WHERE fy.year >= {year_from} AND fy.year <= {year_to}
  For ManagementOutlook/FinancialMetric/Section year filtering, join via accession:
  MATCH (f:Filing) WHERE f.accession_number = mo.accession
  MATCH (f)-[:FILED_IN]->(fy:FiscalYear) WHERE fy.year = {year_from}
- ManagementOutlook text is in mo.text (NOT mo.summary — that property does not exist)
- FinancialMetric year is in fm.as_of_year (NOT fm.fiscal_year)
- Section accession is sec.accession (links to Filing.accession_number)
- Use OPTIONAL MATCH for LLM-only nodes (RiskFactor, RiskDriver, Product, BusinessSegment)
- ALWAYS include c.name AS company in RETURN so results can be attributed to a company
- Use collect(DISTINCT ...) to group related values onto one row per company
- Return at most 50 rows (use LIMIT 50)
- Output ONLY the Cypher query, nothing else
"""

# ── Answer synthesis prompt ───────────────────────────────────────────────────

SYNTHESISER_SYSTEM = """You are a financial analyst assistant specialising in SEC 10-K filings.
Answer questions based ONLY on the provided context — graph facts and filing excerpts.
Cite sources as [Company, FY20XX] after claims. Be concise and direct.
If the data is limited or the graph doesn't have enough nodes yet, say so clearly."""

SYNTHESISER_TEMPLATE = """Question: {question}

Active context: {context_summary}

Note: {source_note}

{primary_block}

{secondary_block}

--- CONVERSATION HISTORY ---
{history}

Answer the question using the facts above. Be specific — name companies, years, figures.
If no relevant data was found, say so and describe what IS available (years, companies in graph).
Keep the answer under 300 words unless more detail is needed.
"""
