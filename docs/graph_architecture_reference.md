# SEC Knowledge Graph — Architecture Reference

> This document captures the graph design conversation and serves as a reference
> for querying the Neo4j database. Neo4j is at `bolt://localhost:7687` (local)
> or `bolt://192.168.1.39:7687` (LAN). User: `neo4j` / Password: `password`.

---

## Next Steps Roadmap
_Last updated: 2026-02-26_

### Immediate — Service Recovery (run first each session)

```bash
# 1. Start Neo4j (check first — may already be running)
docker ps
docker start neo4j-sec

# 2. KG population (fast/spaCy mode — checkpoint resumes automatically)
nohup python3 python/run_kg_population.py --fast > logs/kg_population_throttled.log 2>&1 &

# 3. Chatbot
nohup streamlit run python/chatbot/app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true > logs/chatbot.log 2>&1 &

# 4. R collection for incomplete years
bash run_parallel_collection.sh 2023 4 > logs/collection_2023.log 2>&1 &
bash run_parallel_collection.sh 2024 4 > logs/collection_2024.log 2>&1 &

# 5. Glossary rebuild from full corpus
python3 python/run_glossary.py --rules-only --index-chroma > logs/glossary_rebuild.log 2>&1 &

# Check everything is alive:
ps aux | grep -E "kg_population|streamlit|run_parallel|run_glossary" | grep -v grep
tail -3 logs/kg_population_throttled.log
tail -5 logs/chatbot.log
```

---

### Chatbot — Phase 2 Quality Fixes (main dev work, do while KG runs)

The chatbot skeleton works but has known quality issues. Fix in this order:

**a. Company name resolution** (`python/chatbot/router.py`)
The graph stores company names in UPPER CASE (e.g. `APPLE INC`). Users type natural case.
After LLM routing extracts a company name, do a fuzzy Neo4j lookup before querying:
```cypher
MATCH (c:Company)
WHERE toLower(c.name) CONTAINS toLower($user_input)
   OR c.ticker = toUpper($user_input)
RETURN c.name, c.cik LIMIT 5
```

**b. Cypher error recovery** (`python/chatbot/graph_qa.py`)
If Neo4j rejects the generated Cypher, pass the error message back to the LLM and ask it
to fix the query once before returning empty results.

**c. "No results" messaging** (`python/chatbot/graph_qa.py`)
The graph is ~13% populated (fast-mode only). When a query returns nothing, the synthesiser
should explain what IS in the graph (structural nodes, no semantic entities yet) rather than
just "no data found". The `_overview` fallback in `graph_qa.py` partially handles this —
verify it actually surfaces.

**d. Session persistence** (`python/chatbot/memory.py`)
Save conversation history to a JSON file on disk so it survives chatbot restarts.
Add `save_to_file()` and `load_from_file()` to the memory module.

---

### After KG Fast-Mode Completes (~55,600 docs, est. 15-20h from 2026-02-26)

**LLM-mode KG population** — the single biggest quality unlock.
Run on a focused subset first (risk factors only, 2020-2024) to get the semantic nodes
into the graph: `RiskFactor`, `RiskDriver`, `RiskConsequence`, `Mitigation`.

```bash
# Schema must already be applied (it is)
python3 python/run_kg_population.py --section risk_factors
```

This unlocks chatbot query types like:
- "What supply chain risks did Apple disclose in 2023?"
- "Which companies share geopolitical risk drivers?"
- "How have Tesla's risk factors changed since 2021?"

**Graph quality audit** (before LLM run)
spaCy NER produces false-positive `Competitor` nodes. Run a Cypher cleanup first:
```cypher
// Find suspiciously generic competitor names to review
MATCH (comp:Competitor)
WHERE size(comp.name) < 4
   OR comp.name IN ["the Company", "Management", "Inc", "Corp"]
RETURN comp.name, comp.node_id LIMIT 50
```

---

### Medium Term — Graph Enrichment

| Task | What it enables | Depends on |
|------|----------------|------------|
| Cross-year linking (`SUPERSEDES` edges) | "Did this risk persist or evolve year-over-year?" | LLM-mode done |
| Cross-section edges (`AFFECTS`, `MATERIALISED_AS`, `CITED_IN`) | "Did the stated risk show up in the financials?" | LLM-mode done |
| Historical collection 1993-2014 | Full 30-year dataset | RAM free |
| Risk co-occurrence network | Cluster companies by shared risk profile | LLM-mode done |
| Temporal trend analysis | "When did AI risk start appearing in 10-Ks?" | LLM-mode done |

```bash
# Historical collection (when RAM is free):
bash run_smart_collection.sh 1993 2014 4 6
```

---

### Longer Term — Chatbot Phase 3 & 4

**Phase 3 — UI + graph visualisation**
Add a `pyvis` subgraph panel to the Streamlit app. After each answer, extract node IDs
from the graph query results and render an interactive HTML subgraph showing the entities
referenced. See `CHATBOT_DESIGN.md` Phase 3 section for design details.

**Phase 4 — Cross-company and trend queries**
Requires LLM-mode nodes. Enables sector comparison, tariff/supply chain screening across
all ~10,000 companies, and year-over-year risk trend charts.

---

### Process / Log Reference

| Process | Start command | Log file | PID check |
|---------|--------------|----------|-----------|
| Neo4j | `docker start neo4j-sec` | `docker logs neo4j-sec` | `docker ps` |
| KG population | `nohup python3 python/run_kg_population.py --fast > logs/kg_population_throttled.log 2>&1 &` | `logs/kg_population_throttled.log` | `ps aux \| grep kg_population` |
| Chatbot | `nohup streamlit run python/chatbot/app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true > logs/chatbot.log 2>&1 &` | `logs/chatbot.log` | `ps aux \| grep streamlit` |
| R collection | `bash run_parallel_collection.sh <year> 4 > logs/collection_<year>.log 2>&1 &` | `logs/collection_<year>_worker_N.log` | `ps aux \| grep Rscript` |
| Glossary rebuild | `python3 python/run_glossary.py --rules-only --index-chroma > logs/glossary_rebuild.log 2>&1 &` | `logs/glossary_rebuild.log` | `ps aux \| grep run_glossary` |

---

---

## One Graph, Not Three Separate Ones

It is one unified Neo4j graph. Everything — all companies, all years, all three
sections — lives in the same database. The graph is structured so you can query
across any of those dimensions freely.

---

## The Three-Level Hierarchy

```
FiscalYear (fy_2022) ──PRECEDES──► FiscalYear (fy_2023) ──PRECEDES──► FiscalYear (fy_2024)
                                          │
                                     FILED_IN
                                          ▼
Company ◄──FILED_BY── Filing ──HAS_SECTION──► Section (risk_factors)
                                         └──HAS_SECTION──► Section (business)
                                         └──HAS_SECTION──► Section (mda)
```

**Level 1 — Temporal layer:** FiscalYear nodes (one per calendar year, shared
across all companies) chained with `PRECEDES` edges. This is how you query
"what changed year over year."

**Level 2 — Filing layer:** Each Filing links to one Company, one FiscalYear,
and three Section nodes (one per 10-K section).

**Level 3 — Extracted entity layer:** The sections are the source of all the
interesting nodes:

| Source section                | Extracted nodes                                                              |
|-------------------------------|------------------------------------------------------------------------------|
| Business Description (Item 1) | Product, BusinessSegment, GeographicMarket, Competitor, CustomerSegment, Regulation |
| Risk Factors (Item 1A)        | RiskFactor, RiskDriver, RiskConsequence, Mitigation                         |
| MD&A (Item 7)                 | FinancialMetric, FinancialPeriod, MacroFactor, ManagementOutlook            |

---

## Why Not Split Into Three Separate Graphs?

The whole point of a unified graph is cross-section queries. The reserved (not
yet built) cross-section edges illustrate this:

- `RiskFactor → AFFECTS → BusinessSegment` — risk factors threatening specific business units
- `RiskFactor → MATERIALISED_AS → FinancialMetric` — did a stated risk actually show up in the numbers?
- `MacroFactor → CITED_IN → RiskFactor` — same macro concern cited in risk factors across many companies

Those queries are only possible because it is one graph.

---

## Shared vs. Filing-Specific Nodes

Some nodes are **deduplicated across the whole graph**:

- `GeographicMarket` — `geo_us` is one node; all companies that operate in the US point to it
- `RiskDriver` — `rd_supply_chain_disruption` is one node; every company with a supply chain risk points to it
- `Competitor` — `comp_apple_inc` is shared across any company that names Apple as a competitor
- `CustomerSegment` — `cs_enterprise` is shared
- `Regulation` — `reg_gdpr` is shared
- `MacroFactor` — `macro_interest_rates` is shared

Other nodes are **filing-specific** (one per filing/company/year):

- `RiskFactor`, `Mitigation`, `FinancialMetric`, `ManagementOutlook`, `FinancialPeriod`
- `BusinessSegment`, `Product` (scoped to company + year — the same product name at different companies is separate)

---

## Current Pipeline State

The pipeline is currently running in **fast mode** (`--fast`, spaCy NER). This
populates the structural skeleton: `Company`, `Filing`, `FiscalYear`, `Section`,
`Competitor`, `GeographicMarket`, `Product`.

The richer semantic nodes (`RiskFactor`, `RiskDriver`, `RiskConsequence`,
`Mitigation`, `FinancialMetric`, `ManagementOutlook`, `MacroFactor`) require the
**LLM extraction pass**, which has not run yet.

---

## Node ID Conventions

| Node            | ID pattern                                     | Example                              |
|-----------------|------------------------------------------------|--------------------------------------|
| FiscalYear      | `fy_{year}`                                    | `fy_2023`                            |
| Company         | `{cik}`                                        | `0000320193`                         |
| Filing          | `{accession_number}`                           | `0000320193-23-000106`               |
| Section         | `{cik}_{accession}_{section_type}`             | `0000320193_0000320193-23-000106_mda` |
| BusinessSegment | `{cik}_{year}_seg_{slug}`                      | `0000320193_2023_seg_services`       |
| Product         | `{cik}_{year}_prod_{slug}`                     | `0000320193_2023_prod_iphone`        |
| GeographicMarket| `geo_{iso_code}`                               | `geo_us`, `geo_cn`                   |
| CustomerSegment | `cs_{slug}`                                    | `cs_enterprise`                      |
| Competitor      | `comp_{cik}` or `comp_{slug}`                  | `comp_samsung_electronics`           |
| Regulation      | `reg_{slug}`                                   | `reg_gdpr`                           |
| RiskFactor      | `{cik}_{accession}_risk_{seq:04d}`             | `0000320193_..._risk_0001`           |
| RiskDriver      | `rd_{slug}`                                    | `rd_supply_chain_disruption`         |
| RiskConsequence | `rc_{slug}`                                    | `rc_revenue_decline`                 |
| Mitigation      | `mit_{cik}_{accession}_{seq:04d}`              | `mit_0000320193_..._0001`            |
| FinancialMetric | `{cik}_{accession}_metric_{slug}`              | `0000320193_..._metric_revenue`      |
| FinancialPeriod | `fp_{cik}_{year}_{quarter?}`                   | `fp_0000320193_2023_q4`              |
| MacroFactor     | `macro_{slug}`                                 | `macro_interest_rates`               |
| ManagementOutlook| `{cik}_{accession}_outlook_{seq:04d}`         | `0000320193_..._outlook_0001`        |

---

## Cypher Query Reference

### Structural / Navigation

```cypher
-- FiscalYear chain
MATCH p=(fy:FiscalYear)-[:PRECEDES*]->(fy2:FiscalYear)
RETURN p LIMIT 20

-- All companies with their filing counts
MATCH (c:Company)<-[:FILED_BY]-(f:Filing)
RETURN c.name, c.ticker, count(f) AS filings
ORDER BY filings DESC

-- One company's full filing history (all years)
MATCH (c:Company {ticker: "AAPL"})<-[:FILED_BY]-(f:Filing)-[:FILED_IN]->(fy:FiscalYear)
RETURN c.name, fy.year, f.filing_date
ORDER BY fy.year

-- Sections available for a given company + year
MATCH (c:Company {ticker: "MSFT"})<-[:FILED_BY]-(f:Filing)-[:FILED_IN]->(:FiscalYear {year: 2023}),
      (f)-[:HAS_SECTION]->(s:Section)
RETURN s.section_type, s.word_count
```

---

### Risk Factors (Item 1A)

```cypher
-- All risk factors for a company in a given year
MATCH (c:Company {ticker: "AAPL"})-[:HAS_RISK]->(rf:RiskFactor {as_of_year: 2023})
RETURN rf.title, rf.category, rf.word_count
ORDER BY rf.word_count DESC

-- Risk factors with their drivers
MATCH (c:Company)-[:HAS_RISK]->(rf:RiskFactor)-[:CAUSED_BY]->(rd:RiskDriver)
RETURN c.ticker, rf.title, rd.label
LIMIT 50

-- Risk factors with full chain: driver → risk → consequence → mitigation
MATCH (c:Company {ticker: "TSLA"})-[:HAS_RISK]->(rf:RiskFactor)
OPTIONAL MATCH (rf)-[:CAUSED_BY]->(rd:RiskDriver)
OPTIONAL MATCH (rf)-[:MAY_RESULT_IN]->(rc:RiskConsequence)
OPTIONAL MATCH (rf)-[:MITIGATED_BY]->(m:Mitigation)
RETURN rf.title, collect(distinct rd.label) AS drivers,
       collect(distinct rc.label) AS consequences,
       collect(distinct m.description) AS mitigations

-- Most common risk drivers across ALL companies (cross-company pattern)
MATCH (:RiskFactor)-[:CAUSED_BY]->(rd:RiskDriver)
RETURN rd.label, count(*) AS mention_count
ORDER BY mention_count DESC LIMIT 20

-- Companies sharing the same risk driver (supply chain cluster)
MATCH (c:Company)-[:HAS_RISK]->(rf:RiskFactor)-[:CAUSED_BY]->(rd:RiskDriver)
WHERE rd.node_id = "rd_supply_chain_disruption"
RETURN DISTINCT c.name, c.ticker, rf.as_of_year
ORDER BY c.ticker, rf.as_of_year

-- Risk factors that lead to revenue decline
MATCH (rf:RiskFactor)-[:MAY_RESULT_IN]->(rc:RiskConsequence)
WHERE rc.node_id = "rc_revenue_decline"
MATCH (c:Company)-[:HAS_RISK]->(rf)
RETURN c.ticker, rf.title, rf.as_of_year
ORDER BY rf.as_of_year

-- New risk factors introduced in 2024 (is_new flag from LLM extraction)
MATCH (c:Company)-[:HAS_RISK]->(rf:RiskFactor {as_of_year: 2024, is_new: true})
RETURN c.ticker, rf.title, rf.category
ORDER BY c.ticker

-- Risk factor evolution: same company, two consecutive years
MATCH (c:Company {ticker: "AAPL"})-[:HAS_RISK]->(rf1:RiskFactor {as_of_year: 2022}),
      (c)-[:HAS_RISK]->(rf2:RiskFactor {as_of_year: 2023})
WHERE rf1.category = rf2.category
RETURN rf1.title AS risk_2022, rf2.title AS risk_2023, rf1.category
```

---

### Business Description (Item 1)

```cypher
-- All products offered by a company in a given year
MATCH (c:Company {ticker: "AAPL"})-[:OFFERS]->(p:Product {as_of_year: 2023})
RETURN p.name, p.category
ORDER BY p.name

-- All business segments with revenue percentages (when populated by LLM)
MATCH (c:Company {ticker: "MSFT"})-[:HAS_SEGMENT]->(bs:BusinessSegment)
RETURN bs.name, bs.revenue_pct, bs.as_of_year
ORDER BY bs.as_of_year, bs.revenue_pct DESC

-- Products that belong to a specific segment
MATCH (c:Company {ticker: "AAPL"})-[:HAS_SEGMENT]->(bs:BusinessSegment)-[:INCLUDES]->(p:Product)
RETURN bs.name AS segment, collect(p.name) AS products

-- Which markets does a company operate in?
MATCH (c:Company {ticker: "TSLA"})-[:OPERATES_IN]->(geo:GeographicMarket)
RETURN geo.name, geo.iso_code, geo.level
ORDER BY geo.name

-- Cross-company: which companies operate in China?
MATCH (c:Company)-[:OPERATES_IN]->(geo:GeographicMarket {iso_code: "CN"})
RETURN c.name, c.ticker
ORDER BY c.ticker

-- Competitor overlap: companies that share a common competitor
MATCH (c1:Company)-[:COMPETES_WITH]->(comp:Competitor)<-[:COMPETES_WITH]-(c2:Company)
WHERE c1.ticker < c2.ticker
RETURN c1.ticker, c2.ticker, comp.name AS shared_competitor
ORDER BY c1.ticker, c2.ticker

-- All competitors named for a given company across all years
MATCH (c:Company {ticker: "MSFT"})-[:COMPETES_WITH]->(comp:Competitor)
RETURN comp.name, comp.cik
ORDER BY comp.name

-- Regulatory exposure: companies subject to GDPR
MATCH (c:Company)-[:SUBJECT_TO]->(reg:Regulation)
WHERE reg.node_id = "reg_gdpr"
RETURN c.name, c.ticker
ORDER BY c.ticker

-- Full regulatory footprint of a company
MATCH (c:Company {ticker: "AAPL"})-[:SUBJECT_TO]->(reg:Regulation)
RETURN reg.name, reg.body, reg.jurisdiction
ORDER BY reg.body

-- Customer segments targeted — cross-company view
MATCH (c:Company)-[:TARGETS]->(cs:CustomerSegment)
RETURN cs.label, collect(c.ticker) AS companies, count(c) AS company_count
ORDER BY company_count DESC

-- Business segment revenue concentration for a company
MATCH (c:Company {ticker: "AAPL"})-[:HAS_SEGMENT]->(bs:BusinessSegment {as_of_year: 2023})
WHERE bs.revenue_pct IS NOT NULL
RETURN bs.name, bs.revenue_pct
ORDER BY bs.revenue_pct DESC
```

---

### MD&A (Item 7)

```cypher
-- All financial metrics reported by a company for a year
MATCH (c:Company {ticker: "AAPL"})-[:REPORTS]->(fm:FinancialMetric {as_of_year: 2023})
RETURN fm.name, fm.value, fm.unit, fm.direction, fm.yoy_change, fm.basis
ORDER BY fm.name

-- Metrics by direction (which companies reported revenue declines in 2023?)
MATCH (c:Company)-[:REPORTS]->(fm:FinancialMetric {as_of_year: 2023})
WHERE fm.name CONTAINS "Revenue" AND fm.direction = "decrease"
RETURN c.ticker, fm.name, fm.value, fm.yoy_change
ORDER BY fm.yoy_change

-- Metrics attributed to a specific business segment
MATCH (c:Company {ticker: "MSFT"})-[:REPORTS]->(fm:FinancialMetric)-[:ATTRIBUTED_TO]->(bs:BusinessSegment)
RETURN fm.name, fm.value, fm.direction, bs.name AS segment
ORDER BY bs.name

-- Macro factors driving financial performance — cross-company
MATCH (fm:FinancialMetric)-[:IMPACTED_BY]->(macro:MacroFactor)
MATCH (c:Company)-[:REPORTS]->(fm)
RETURN macro.label, collect(DISTINCT c.ticker) AS affected_companies,
       count(fm) AS metric_count
ORDER BY metric_count DESC

-- Which macro factor affects the most companies?
MATCH (c:Company)-[:REPORTS]->(fm:FinancialMetric)-[:IMPACTED_BY]->(macro:MacroFactor)
RETURN macro.label, count(DISTINCT c) AS company_count
ORDER BY company_count DESC LIMIT 10

-- Management outlook sentiment breakdown for a year
MATCH (c:Company)-[:HAS_OUTLOOK]->(mo:ManagementOutlook)
WHERE mo.accession CONTAINS "2023"
RETURN mo.sentiment, count(*) AS count
ORDER BY count DESC

-- Cautious outlooks with the metrics they reference
MATCH (c:Company)-[:HAS_OUTLOOK]->(mo:ManagementOutlook {sentiment: "cautious"})-[:REFERENCES]->(fm:FinancialMetric)
RETURN c.ticker, mo.text, fm.name, fm.direction
ORDER BY c.ticker

-- Metrics that declined YoY (sorted by worst performance)
MATCH (c:Company)-[:REPORTS]->(fm:FinancialMetric {direction: "decrease"})
WHERE fm.yoy_change IS NOT NULL
RETURN c.ticker, fm.name, fm.yoy_change AS pct_change
ORDER BY fm.yoy_change ASC LIMIT 20

-- Revenue driver decomposition for a company
MATCH (c:Company {ticker: "TSLA"})-[:REPORTS]->(fm:FinancialMetric)-[:DRIVEN_BY]->(drv)
RETURN fm.name, collect(drv.label) AS drivers
ORDER BY fm.name
```

---

### Cross-Section Queries (Reserved — requires LLM pass + cross-section edges)

These queries require the `AFFECTS`, `MATERIALISED_AS`, `CITED_IN`, and
`REPORTED_IN` edges, which are planned but not yet built:

```cypher
-- Which business segments are most threatened by risk factors?
MATCH (rf:RiskFactor)-[:AFFECTS]->(bs:BusinessSegment)
MATCH (c:Company)-[:HAS_SEGMENT]->(bs)
RETURN bs.name, count(rf) AS risk_count, collect(DISTINCT rf.title) AS risks
ORDER BY risk_count DESC

-- Did a stated risk materialise in the financials?
MATCH (c:Company {ticker: "AAPL"})-[:HAS_RISK]->(rf:RiskFactor)-[:MATERIALISED_AS]->(fm:FinancialMetric)
RETURN rf.title, fm.name, fm.direction, fm.yoy_change

-- Which macro factors are cited in risk factors across many companies?
MATCH (macro:MacroFactor)-[:CITED_IN]->(rf:RiskFactor)
MATCH (c:Company)-[:HAS_RISK]->(rf)
RETURN macro.label, count(DISTINCT c) AS company_count, count(rf) AS risk_count
ORDER BY company_count DESC

-- Full causal chain: macro → risk → financial impact
MATCH (macro:MacroFactor)-[:CITED_IN]->(rf:RiskFactor)-[:MATERIALISED_AS]->(fm:FinancialMetric)
MATCH (c:Company)-[:HAS_RISK]->(rf), (c)-[:REPORTS]->(fm)
RETURN c.ticker, macro.label, rf.title, fm.name, fm.direction
ORDER BY c.ticker
```

---

## Extensibility — Can More Nodes Be Added?

Yes — the architecture is intentionally extensible. The pipeline is structured
so adding a new node type requires:

1. A new class in `python/ontology/nodes.py`
2. A new relation type in `python/ontology/relations.py`
3. A new extraction rule or LLM prompt update in `python/kg_population/`
4. A new uniqueness constraint in `python/ontology/neo4j_schema.py`

### Potential additions to Business Description (Item 1)

| Proposed node       | Rationale                                                        | Scope     |
|---------------------|------------------------------------------------------------------|-----------|
| `KeySupplier`       | Named critical suppliers — maps supply chain dependencies        | shared    |
| `IntellectualProperty` | Patent/trademark references — important for tech/pharma       | filing    |
| `Subsidiary`        | Named subsidiaries / affiliates                                  | filing    |
| `DistributionChannel` | Direct, retail, wholesale, digital — how products reach customers | shared |
| `Partnership`       | Named joint ventures and alliances                               | filing    |
| `Certification`     | ISO, SOC 2, FDA approvals etc.                                   | shared    |
| `Employee` (aggregate) | Headcount disclosures by segment or geography                 | filing    |

### Potential additions to MD&A (Item 7)

| Proposed node       | Rationale                                                        | Scope     |
|---------------------|------------------------------------------------------------------|-----------|
| `CapitalAllocation` | Buybacks, dividends, capex guidance — capital return signals     | filing    |
| `GuidanceStatement` | Forward-looking specific numeric guidance vs ManagementOutlook  | filing    |

### Potential additions to Risk Factors (Item 1A)

| Proposed node       | Rationale                                                        | Scope     |
|---------------------|------------------------------------------------------------------|-----------|
| `RegulatoryRisk`    | Specific regulatory proceedings / enforcement actions            | filing    |
| `LitigationRisk`    | Named lawsuits or regulatory investigations                      | filing    |
