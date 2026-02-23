# SEC Knowledge Graph — Project Reference

> This document is a reference guide for building the Ghostlink app on top of the SEC Knowledge Graph pipeline.
> **Do not edit files outside of `app/ghostlink/`.** This doc is read-only reference material.

---

## 1. What This Project Is

A pipeline that ingests SEC 10-K filings from EDGAR for ~7,880 publicly traded US companies and builds a **structured knowledge graph** in Neo4j. Data spans 1993–2024, with 2015–2024 actively collected.

Three filing sections are extracted per company per year:
- **Item 1** — Business Description
- **Item 1A** — Risk Factors
- **Item 7** — MD&A (Management Discussion & Analysis)

The pipeline has two layers:
1. **R layer** — downloads raw filings from EDGAR, extracts the three sections into `.txt` files
2. **Python layer** — preprocesses those `.txt` files into JSON, builds a domain glossary, and populates a Neo4j knowledge graph

---

## 2. Repository Layout

```
SEC/
├── CLAUDE.md                          # Master developer guide
├── PROJECT_STATUS.md                  # 8-session progress log
├── IDEAS.md                           # 11 business use cases
├── REINSTALL.md                       # From-scratch setup guide
│
├── python/                            # NLP + KG pipeline
│   ├── config.py                      # Central config — all paths and env vars
│   ├── requirements.txt               # pip dependencies
│   ├── models/
│   │   ├── schemas.py                 # Pydantic data models
│   │   └── llm_client.py              # Unified LLM wrapper
│   ├── preprocessing/
│   │   ├── cleaner.py                 # HTML stripping, whitespace
│   │   ├── segmenter.py               # Sentence segmentation (spaCy)
│   │   ├── tagger.py                  # Forward-looking + coreference detection
│   │   └── pipeline.py                # R .txt → SectionDocument JSON
│   ├── glossary/
│   │   ├── extractor.py               # Rule-based + LLM term extraction
│   │   └── vector_store.py            # ChromaDB integration
│   ├── ontology/
│   │   ├── nodes.py                   # 18 typed node classes
│   │   ├── relations.py               # 25 relation types + Edge model
│   │   └── neo4j_schema.py            # Constraints, indexes, upsert writer
│   ├── kg_population/
│   │   ├── extractor.py               # LLM-based entity extraction
│   │   ├── ner_extractor.py           # spaCy NER fallback (--fast mode)
│   │   ├── normaliser.py              # Raw dicts → typed nodes + dedup
│   │   ├── pipeline.py                # Orchestrator + checkpoint system
│   │   └── writer.py                  # Neo4j upsert operations
│   ├── run_preprocessing.py
│   ├── run_glossary.py
│   └── run_kg_population.py
│
├── R scripts                          # Data collection layer
│   ├── get_all_companies.R
│   ├── get_daily_master.R
│   ├── helper_functions.R
│   └── ticker_to_cik.csv              # CIK ↔ ticker lookup
│
├── Shell orchestrators
│   ├── run_parallel_collection.sh
│   ├── run_all_years.sh
│   └── run_daily_update.sh
│
├── edgar_RiskFactors/<year>/          # Extracted Item 1A .txt files
├── edgar_BusinDescr/<year>/           # Extracted Item 1 .txt files
├── edgar_MgmtDisc/<year>/             # Extracted Item 7 .txt files
├── edgar_MasterIndex/                 # Quarterly .Rda index files
│
├── python/data/
│   ├── preprocessed/                  # Stage 1 output: SectionDocument JSON
│   │   ├── risk_factors/
│   │   ├── business/
│   │   └── mda/
│   ├── glossary/                      # Stage 2 output: GlossaryStore JSON
│   ├── kg_export/.checkpoint.json     # KG population resume checkpoint
│   └── chroma/                        # ChromaDB vector store
│
└── app/
    ├── 10k-monitor/                   # Risk factor delta MVP (Next.js + FastAPI)
    └── ghostlink/                     # This app — under development
```

---

## 3. Data Sizes & Current State (as of 2026-02-21)

| Data | Size | Count |
|------|------|-------|
| edgar_BusinDescr/ | 703 MB | ~6,463 .txt files |
| edgar_MgmtDisc/ | 475 MB | ~6,209 .txt files |
| edgar_RiskFactors/ | 441 MB | ~6,074 .txt files |
| edgar_MasterIndex/ | 594 MB | 1993–2024 quarterly |
| Preprocessed JSON | — | ~18,746 documents |
| KG nodes (so far) | — | ~4,526 |
| KG edges (so far) | — | ~6,291 |

**Collection progress by year:**

| Year | Risk Factors | Business | MD&A |
|------|-------------|----------|------|
| 2015 | 1,555 | 1,675 | 1,643 |
| 2016 | 1,131 | 1,194 | 1,174 |
| 2017 | 561 | 600 | 597 |
| 2018 | 365 | 410 | 410 |
| 2019 | 952 | 1,030 | 1,035 |
| 2020 | 489 | 522 | 521 |
| 2021 | 154 | 162 | 169 |
| 2022 | 250 | 254 | 262 |
| 2023 | 190 | 193 | 211 |
| 2024 | 427 | 431 | 444 |

---

## 4. Raw File Format (R Output)

Each `.txt` file written by R has this header format, followed by the section text:

```
CIK: 0000320193
Company Name: Apple Inc.
Form Type: 10-K
Filing Date: 2024-11-01
Accession Number: 0000320193-24-000123

<section text begins here...>
```

**Filename pattern:** `{cik}_{accession_short}.txt`

**Fiscal year derivation:** If filing month ≤ 3 (Q1), fiscal year = filing year − 1. Otherwise fiscal year = filing year.

---

## 5. Preprocessed JSON Schema

After Stage 1 preprocessing, each filing section becomes a `SectionDocument` JSON file at:
`python/data/preprocessed/{section_type}/{cik}_{accession}.json`

### FilingMetadata
```json
{
  "cik": "0000320193",
  "ticker": "AAPL",
  "company_name": "Apple Inc.",
  "form_type": "10-K",
  "filing_date": "2024-11-01",
  "accession_number": "0000320193-24-000123",
  "fiscal_year": 2024,
  "section_type": "risk_factors"
}
```

### TaggedSentence
```json
{
  "sentence_id": "0000320193_rf_0042",
  "text": "We expect demand for our products to increase.",
  "word_count": 9,
  "has_company_coref": true,
  "forward_looking_indicators": ["expect"],
  "metadata": { "paragraph_index": 3, "sentence_index": 2 }
}
```

### SectionDocument
```json
{
  "metadata": { ...FilingMetadata },
  "sentences": [ ...TaggedSentence ],
  "word_count": 12847,
  "sentence_count": 342
}
```

---

## 6. Neo4j Graph Schema

### Node Types (18 total)

**Shared across all sections:**
| Node | ID Scheme | Key Properties |
|------|-----------|----------------|
| `FiscalYear` | `fy_{year}` | year |
| `Company` | `comp_{cik}` | cik, ticker, name |
| `Filing` | `filing_{accession}` | accession_number, filing_date, fiscal_year |
| `Section` | `{accession}_{section_type}` | section_type, word_count |

**Business Description (Item 1):**
| Node | ID Scheme |
|------|-----------|
| `BusinessSegment` | `{cik}_{year}_seg_{slug}` |
| `Product` | `{cik}_{year}_prod_{slug}` |
| `GeographicMarket` | `geo_{iso_code}` (e.g. `geo_US`, `geo_CN`) |
| `CustomerSegment` | `cs_{slug}` (Enterprise, Government, SMB, Consumer) |
| `Competitor` | `comp_{cik}` or `comp_{slug}` |
| `Regulation` | `reg_{slug}` (GDPR, SOX, HIPAA, etc.) |

**Risk Factors (Item 1A):**
| Node | ID Scheme |
|------|-----------|
| `RiskFactor` | `{cik}_{accession}_risk_{seq:04d}` |
| `RiskDriver` | `rd_{slug}` (supply chain, interest rate, etc.) |
| `RiskConsequence` | `rc_{slug}` (loss, bankruptcy, etc.) |
| `Mitigation` | `mit_{cik}_{accession}_{seq:04d}` |

**MD&A (Item 7):**
| Node | ID Scheme |
|------|-----------|
| `FinancialMetric` | `{cik}_{accession}_metric_{slug}` |
| `FinancialPeriod` | `fp_{cik}_{year}` |
| `Driver` | `drv_{slug}` (revenue/cost driver) |
| `MacroFactor` | `macro_{slug}` |
| `ManagementOutlook` | `{cik}_{accession}_outlook_{seq:04d}` |

### Relation Types (25 total)

**Temporal scaffold:**
```
(FiscalYear:fy_2022)-[:PRECEDES]->(FiscalYear:fy_2023)-[:PRECEDES]->(FiscalYear:fy_2024)
                                                                            |
                                                                 [:FILED_IN]
                                                                      |
                                                                  (Filing)
                                                                      |
                                                                [:FILED_BY]
                                                                      |
                                                                  (Company)
```

**Full relation list:**
| Type | From → To |
|------|-----------|
| `FILED_BY` | Filing → Company |
| `HAS_SECTION` | Filing → Section |
| `FILED_IN` | Filing → FiscalYear |
| `PRECEDES` | FiscalYear → FiscalYear |
| `HAS_SEGMENT` | Company → BusinessSegment |
| `OFFERS` | Company → Product |
| `OPERATES_IN` | Company → GeographicMarket |
| `TARGETS` | Company → CustomerSegment |
| `COMPETES_WITH` | Company ↔ Competitor |
| `SUBJECT_TO` | Company → Regulation |
| `HAS_RISK` | Company → RiskFactor |
| `CAUSED_BY` | RiskFactor → RiskDriver |
| `MAY_RESULT_IN` | RiskFactor → RiskConsequence |
| `MITIGATED_BY` | RiskFactor → Mitigation |
| `RELATED_TO` | RiskFactor ↔ RiskFactor |
| `SUPERSEDES` | RiskFactor → RiskFactor (cross-year) |
| `REPORTS` | Company → FinancialMetric |
| `ATTRIBUTED_TO` | FinancialMetric → Driver |
| `DRIVEN_BY` | FinancialMetric → MacroFactor |
| `IMPACTED_BY` | Company → MacroFactor |
| `HAS_OUTLOOK` | Company → ManagementOutlook |
| `REFERENCES` | ManagementOutlook → FinancialMetric |

**Reserved (not yet implemented):**
`AFFECTS`, `MATERIALISED_AS`, `CITED_IN`, `REPORTED_IN`, `PERSISTED_TO`, `EMERGED_IN`, `RESOLVED_IN`

### Uniqueness Constraints & Indexes
- 18 uniqueness constraints on `node_id` (one per node type)
- Indexes on: `FiscalYear.year`, `Company.cik`, `Company.ticker`, `Filing.accession_number`, `RiskFactor.cik`, `FinancialMetric.cik`

---

## 7. Infrastructure

### Neo4j
- Running in Docker container: `neo4j-sec`
- HTTP: `http://localhost:7474`
- Bolt: `bolt://localhost:7687`
- Credentials: `neo4j` / `secpassword` (from `.env`)
- Edition: Community (single database only — hence FiscalYear anchor design)

### ChromaDB
- Persistent vector store at `python/data/chroma/`
- Stores sentence-level embeddings for semantic search
- Populated during Stage 2 glossary extraction (`--index-chroma` flag)

### LLM Providers (configured via `.env`)
| Variable | Values |
|----------|--------|
| `LLM_PROVIDER` | `ollama` (default), `anthropic`, `openai` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` |
| `OLLAMA_MODEL` | `gpt-oss:latest` |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` |
| `OPENAI_MODEL` | `gpt-4o` |

---

## 8. Python Config (`python/config.py`)

All paths and settings flow from this single file. Key values:

```python
# Paths
EDGAR_RISK_FACTORS_DIR     # edgar_RiskFactors/
EDGAR_BUSINESS_DIR         # edgar_BusinDescr/
EDGAR_MDA_DIR              # edgar_MgmtDisc/
PREPROCESSED_DIR           # python/data/preprocessed/
GLOSSARY_DIR               # python/data/glossary/
KG_EXPORT_DIR              # python/data/kg_export/
CHROMA_PERSIST_DIR         # python/data/chroma/
TICKER_TO_CIK_PATH         # ticker_to_cik.csv

# NLP
FORWARD_LOOKING_PATTERNS   # 26 regex patterns
COMPANY_COREF_PATTERNS     # 4 patterns (we, our, the company, etc.)

# Neo4j
NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, NEO4J_DATABASE
```

---

## 9. Key Cypher Query Patterns

These queries demonstrate what the graph can answer:

```cypher
-- Companies with most risk factors in a given year
MATCH (c:Company)-[:FILED_BY]-(:Filing)-[:FILED_IN]-(:FiscalYear {year: 2023})
      -[:HAS_SECTION]-(:Section)-[:HAS_RISK]->(r:RiskFactor)
RETURN c.name, count(r) as risk_count
ORDER BY risk_count DESC LIMIT 20

-- Top risk drivers across semiconductor sector
MATCH (c:Company {sector: 'semiconductors'})-[:HAS_RISK]->(r:RiskFactor)-[:CAUSED_BY]->(d:RiskDriver)
WHERE r.as_of_year = 2022
RETURN d.label, count(r) as frequency
ORDER BY frequency DESC

-- Competitor network for a company
MATCH (c:Company {ticker: 'NVDA'})-[:COMPETES_WITH]-(competitor:Competitor)
RETURN c.name, competitor.name

-- Risk factors that materialised year-over-year (reserved — not yet implemented)
MATCH (r1:RiskFactor)-[:SUPERSEDES]->(r2:RiskFactor)
WHERE r1.as_of_year = 2023 AND r2.as_of_year = 2022
RETURN r1, r2
```

---

## 10. Existing App: 10k-monitor (Reference)

A working MVP at `app/10k-monitor/` with this architecture:

**Backend:** FastAPI + SQLite
- Reads preprocessed JSON directly from `../../python/data/preprocessed/risk_factors/`
- No Neo4j dependency (works off flat files)
- Computes diffs with `difflib.SequenceMatcher`
- Caches results in SQLite at `backend/data/monitor.db`

**Frontend:** Next.js 14 + TypeScript + Tailwind CSS
- Company search grid
- Filing timeline
- Side-by-side sentence-level risk factor comparison
- Severity scoring: HIGH/MED/LOW

**Endpoints:**
```
GET  /api/health                    — index stats
GET  /api/companies?q=AMD           — search companies
GET  /api/companies/{cik}           — detail + filing list
GET  /api/delta/{acc_A}/{acc_B}     — risk factor diff
POST /api/reindex                   — force re-index
```

This app demonstrates: reading preprocessed JSON, indexing by CIK, and building a diff interface without requiring Neo4j to be running.

---

## 11. LLM Client API

Located at `python/models/llm_client.py`. All providers share a single interface:

```python
from python.models.llm_client import LLMClient

client = LLMClient()  # uses LLM_PROVIDER env var

response = client.complete(
    prompt="Extract risk factors from this text...",
    system="You are a financial analyst...",
    max_tokens=1000,
    temperature=0.0
)
# returns: str
```

Provider-specific notes:
- **Ollama:** retries with exponential backoff (5→10→20→40→80s) on VRAM eviction; `keep_alive=-1`
- **Anthropic / OpenAI:** standard API calls, no retry logic

---

## 12. What Is Not Yet Built (Opportunities for Ghostlink)

These are explicitly deferred or never implemented in the pipeline:

| Missing Feature | Notes |
|----------------|-------|
| Cross-year semantic linking | `PERSISTED_TO`, `EMERGED_IN`, `RESOLVED_IN` edges not created |
| LLM-mode KG population at scale | All KG data is from spaCy NER (noisy but fast) |
| Natural language query interface | No RAG or Cypher generator over the graph |
| Risk evolution timeline UI | Temporal layer is in place but no UI exists |
| Sector risk dashboard | Graph analytics not yet aggregated |
| Peer comparison reports | No report generation |
| Alert / watch service | No delta alerting |
| Semantic search UI | ChromaDB populated but no user-facing query |
| Cross-section entity linking | Entities in Business, Risk, MDA sections not connected to each other |
| Historical data 1993–2014 | Master indexes ready; collection not started |
| Graph quality audit | NER noise (false positive ORG, GPE) not cleaned |

---

## 13. Business Use Cases (from IDEAS.md)

Priority applications for the graph data:

1. **Risk Signal Generation** — new, escalating, de-escalating risk factors across portfolio
2. **Portfolio Risk Mapping** — concentration of shared risk drivers across holdings
3. **Competitive Intelligence** — `COMPETES_WITH` graph, sector landscape
4. **Credit Due Diligence** — automated risk narrative from graph + source sentences
5. **M&A Due Diligence** — idiosyncratic vs sector risk breakdown
6. **Disclosure Benchmarking** — how does company X's risk disclosure compare to peers?
7. **Emerging Risk Detection** — first appearances of new `RiskDriver` nodes across sector
8. **Risk Evolution Timeline** — track how a risk factor changes wording year over year
9. **Natural Language Query** — "What are the top 5 risks for chip companies in 2023?"
10. **Sector Pulse Reports** — automated quarterly PDF/web report per sector
11. **RiskRadar Alerts** — watch a company or sector; notify on material changes

---

## 14. Technical Notes for App Development

### Accessing Preprocessed Data (no Neo4j required)

Each preprocessed file is self-contained JSON at:
```
python/data/preprocessed/{section_type}/{cik}_{accession}.json
```

To list all companies with risk factor data:
```python
from pathlib import Path
import json

for f in Path("../../python/data/preprocessed/risk_factors").glob("*.json"):
    with open(f) as fh:
        doc = json.load(fh)
    cik = doc["metadata"]["cik"]
    ticker = doc["metadata"]["ticker"]
    year = doc["metadata"]["fiscal_year"]
```

### Accessing Neo4j

```python
from neo4j import GraphDatabase

driver = GraphDatabase.driver(
    "bolt://localhost:7687",
    auth=("neo4j", "secpassword")
)

with driver.session() as session:
    result = session.run("MATCH (c:Company) RETURN c LIMIT 10")
    for record in result:
        print(record["c"])
```

### ChromaDB Semantic Search

```python
import chromadb

client = chromadb.PersistentClient(path="../../python/data/chroma")
collection = client.get_collection("sec_sentences")

results = collection.query(
    query_texts=["supply chain disruption risk"],
    n_results=10
)
```

### Environment Setup for App

Copy the parent `.env` or create your own at `app/ghostlink/.env`:
```
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=secpassword
ANTHROPIC_API_KEY=...
```

---

## 15. Data Quality Notes

- **spaCy NER false positives:** The current graph was populated with `--fast` mode (spaCy NER). This means some `Competitor` nodes may be financial phrases (e.g., "Cash and Equivalents" misclassified as ORG). Treat graph data as approximate.
- **Fiscal year approximation:** Q1 filings assumed to be prior year — valid for most 10-Ks (which report the prior fiscal year), but not all companies.
- **CIK stability:** CIK is the stable identifier for a company across all years. Tickers can change; CIK does not.
- **Accession number uniqueness:** Each filing has a unique accession number. Format: `{cik}-{yy}-{seq}` (e.g., `0000320193-24-000123`).
- **Missing years/companies:** Collection is ongoing. Not all companies have all years 2015–2024. Gaps exist especially for 2017–2023.
- **Graph sparsity:** At ~4,526 nodes and ~6,291 edges from 18,746 preprocessed docs, the KG is still sparse. Only ~13% of documents have been written to Neo4j so far.
