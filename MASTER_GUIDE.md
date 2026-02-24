# SEC Knowledge Graph — Master Guide

> **Purpose:** If you lose your computer, lose the data, or come back after a long break — this document tells you exactly what was built, why, how to rebuild it, and what to do next.

---

## Table of Contents

1. [What This Project Is](#1-what-this-project-is)
2. [System Requirements](#2-system-requirements)
3. [Starting From Zero — Full Rebuild](#3-starting-from-zero--full-rebuild)
4. [R Layer — Data Collection](#4-r-layer--data-collection)
5. [Python Layer — Pipeline](#5-python-layer--pipeline)
6. [Neo4j — Graph Database](#6-neo4j--graph-database)
7. [App Layer](#7-app-layer)
8. [Architecture Deep Dive](#8-architecture-deep-dive)
9. [Current Status (as of 2026-02-23)](#9-current-status-as-of-2026-02-23)
10. [What To Do Next](#10-what-to-do-next)
11. [Command Quick Reference](#11-command-quick-reference)
12. [Key Design Decisions (and Why)](#12-key-design-decisions-and-why)
13. [Troubleshooting](#13-troubleshooting)

---

## 1. What This Project Is

A pipeline that turns raw SEC 10-K filings into a **knowledge graph** stored in Neo4j. The goal is to make 30 years of financial risk disclosures queryable, comparable, and searchable at scale.

### What it does, end-to-end:

```
SEC EDGAR (public) → R scripts download raw filings
                   → Extract 3 sections per filing:
                       - Item 1  (Business Description)
                       - Item 1A (Risk Factors)
                       - Item 7  (MD&A — Management Discussion)
                   → Python cleans + segments text into sentences
                   → Tags forward-looking language & company coreferences
                   → Extracts domain glossary terms
                   → Populates Neo4j with typed entities & relationships
                   → ChromaDB stores sentence embeddings for semantic search
                   → App layer serves risk delta views and graph analytics
```

### Scale:
- **~7,880** US public companies (with 10-K filings on EDGAR)
- **30+ years** of data (1993–2024); actively collected 2015–2024
- **~50,000** extracted `.txt` section files
- **~49,000** preprocessed JSON documents
- **18 node types**, **25 relation types** in the ontology

### GitHub Repository:
```
https://github.com/msmith01/SEC_KG  (private)
Remote: git@github.com:msmith01/SEC_KG.git
```

---

## 2. System Requirements

### Hardware
- **RAM:** 16 GB minimum, 32 GB recommended (spaCy + Neo4j together)
- **Disk:** 50+ GB free (raw filings deleted after extraction, but outputs grow)
- **GPU:** Optional (RTX series for local LLM via Ollama). If using RTX 5090: see [GPU fix below](#rtx-5090-gsp-firmware-crash)
- **CPU:** Any modern multicore (R parallel workers use forking)

### Software
| Tool | Version | Purpose |
|------|---------|---------|
| R | ≥ 4.3 | Data collection from EDGAR |
| Python | ≥ 3.11 | Pipeline, preprocessing, KG population |
| Docker | Latest | Runs Neo4j |
| Ollama | Latest | Local LLM inference (optional) |
| Node.js | ≥ 18 | Frontend (10k-monitor app) |
| Git | Any | Version control |

### R Packages (auto-installed by scripts)
```r
install.packages(c("edgar", "dplyr", "tidyr", "stringr", "lubridate", "jsonlite"))
```

---

## 3. Starting From Zero — Full Rebuild

Follow these steps **in order** if rebuilding from scratch.

### Step 1 — Clone the repository

```bash
git clone git@github.com:msmith01/SEC_KG.git
cd SEC_KG
```

### Step 2 — Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in:
```
LLM_PROVIDER=ollama          # or: anthropic, openai
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=gpt-oss:20b     # or whatever model you have pulled
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password
CHROMA_PERSIST_DIR=python/data/chroma
```

### Step 3 — Start Neo4j (Docker)

```bash
docker run -d \
  --name neo4j-sec \
  -p 7474:7474 -p 7687:7687 \
  -v $(pwd)/neo4j_data:/data \
  -v $(pwd)/neo4j_logs:/logs \
  -e NEO4J_AUTH=neo4j/password \
  -e NEO4J_dbms_memory_pagecache_size=2G \
  -e NEO4J_dbms_memory_heap_max__size=4G \
  neo4j:5
```

Wait ~30 seconds, then check: http://localhost:7474 (login: neo4j / password)

To restart Neo4j later: `docker start neo4j-sec`

### Step 4 — Set up Python

```bash
# Install deps (system Python or venv)
pip install -r python/requirements.txt

# Download spaCy model (large is best; small works if disk is tight)
python -m spacy download en_core_web_lg
# fallback: python -m spacy download en_core_web_sm

# Apply Neo4j schema (run once before any KG population)
python python/run_kg_population.py --apply-schema
```

> **Note on venv:** The `.venv/` directory exists but is partially broken (deps landed in user Python `~/.local/lib/python3.13/`). Just use `python` or `python3` directly — it works. If you want a clean venv:
> ```bash
> python3 -m venv .venv
> source .venv/bin/activate
> pip install -r python/requirements.txt
> python -m spacy download en_core_web_lg
> ```

### Step 5 — Set up R

```bash
# Install edgar + dependencies (run once in R console)
Rscript -e 'install.packages(c("edgar","dplyr","tidyr","stringr","lubridate","jsonlite"), repos="https://cran.r-project.org")'
```

### Step 6 — Collect data (R layer)

Start with a recent year to verify everything works:

```bash
# Test: collect 2024 data, 4 parallel workers
bash run_parallel_collection.sh 2024 4

# Then collect all years 2015–2024 (this takes ~13 hours total)
bash run_all_years.sh 2015 2024 4

# Historical (1993–2014) — run when ready
bash run_smart_collection.sh 1993 2014 4 6
```

Watch logs in `logs/collection_<year>_worker_N.log`.

### Step 7 — Run preprocessing (Python)

```bash
# Process all sections (reads R output, writes JSON to python/data/preprocessed/)
python python/run_preprocessing.py

# Or one section at a time:
python python/run_preprocessing.py --section risk_factors
python python/run_preprocessing.py --section business
python python/run_preprocessing.py --section mda
```

### Step 8 — Build glossary (optional but useful)

```bash
# Fast mode (no LLM needed)
python python/run_glossary.py --rules-only

# Full mode (uses LLM — requires Ollama or API key)
python python/run_glossary.py

# Also push to ChromaDB vector store
python python/run_glossary.py --index-chroma
```

### Step 9 — Populate the graph

```bash
# Dry run first (no Neo4j writes, just verify extraction works)
python python/run_kg_population.py --dry-run --section risk_factors --limit 1

# Fast mode (spaCy NER — no GPU needed, processes everything)
python python/run_kg_population.py --fast --section risk_factors
python python/run_kg_population.py --fast --section business
python python/run_kg_population.py --fast

# LLM mode (higher quality extraction — requires working GPU or API key)
python python/run_kg_population.py --section risk_factors
```

The checkpoint at `python/data/kg_export/.checkpoint.json` makes this resumable — if interrupted, just re-run the same command.

### Step 10 — Verify the graph

Open Neo4j browser: http://localhost:7474

```cypher
// Count everything
MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count ORDER BY count DESC;

// Sample a company
MATCH (c:Company)-[:FILED_BY]-(f:Filing)-[:HAS_SECTION]-(s:Section)
RETURN c, f, s LIMIT 25;

// Risk factors for a company
MATCH (c:Company {name: "APPLE INC"})-[:FILED_BY]-(f:Filing)-[:HAS_SECTION]-(s:Section)-[:HAS_RISK]-(r:RiskFactor)
RETURN r.text LIMIT 20;
```

---

## 4. R Layer — Data Collection

### Key Files

| File | Purpose |
|------|---------|
| `ticker_to_cik.csv` | Maps ~5,128 company tickers to EDGAR CIK numbers — **essential, don't lose this** |
| `helper_functions.R` | Core extraction logic: `getRiskFactors()`, `fetch10KData()` |
| `get_all_companies.R` | Bulk collection script (parameterized) |
| `get_daily_master.R` | Download daily EDGAR index, fetch recent 10 companies |
| `get_daily_master_index.R` | Download/maintain quarterly EDGAR master indexes |
| `run_parallel_collection.sh` | Run `get_all_companies.R` in N parallel workers per year |
| `run_smart_collection.sh` | Run multiple years concurrently (4 years × N workers) |
| `run_all_years.sh` | Loop through all years sequentially |
| `run_daily_update.sh` | Cron job for daily EDGAR updates |

### What gets downloaded

EDGAR hosts all SEC filings publicly. For each company × year, we download its 10-K and extract three sections:

| Section | EDGAR Name | Directory |
|---------|-----------|-----------|
| Item 1 | Business Description | `edgar_BusinDescr/<year>/` |
| Item 1A | Risk Factors | `edgar_RiskFactors/<year>/` |
| Item 7 | MD&A | `edgar_MgmtDisc/<year>/` |

Raw filing HTML is deleted after extraction to save disk (saves ~4 TB at full scale).

### Output file format

Each `.txt` file in the output directories has a header block followed by raw section text:

```
CIK: 320193
Company Name: APPLE INC
Form Type: 10-K
Filing Date: 2023-11-03
Accession Number: 0000320193-23-000106

<section text starts here...>
```

### Resumability

`get_all_companies.R` skips companies that already have output files in all three section directories (`{cik}_*.txt` exists in RF, BD, and MD&A for the target year). Safe to re-run after interruption.

### Parallelization

```bash
# One year, N workers
bash run_parallel_collection.sh 2024 4        # default: 4 workers
bash run_parallel_collection.sh 2020 8        # 8 workers for speed
bash run_parallel_collection.sh 2020 4 1000   # only first 1000 companies

# Multiple years concurrently
bash run_smart_collection.sh 1993 2014 4 6    # 4 years at a time, 6 workers/year

# All years sequentially
bash run_all_years.sh 2015 2024 4             # 2015→2024, 4 workers/year
```

---

## 5. Python Layer — Pipeline

### Overview

Three stages, each a standalone runnable script:

```
Stage 1: Preprocessing  →  python/run_preprocessing.py
Stage 2: Glossary       →  python/run_glossary.py
Stage 3: KG Population  →  python/run_kg_population.py
```

### Central Config: `python/config.py`

All paths and environment variables are read **once** here. Nothing downstream hardcodes any paths. If you move directories or rename things, only `config.py` needs to change.

### Data Models: `python/models/schemas.py`

| Model | Purpose |
|-------|---------|
| `FilingMetadata` | Provenance per filing: CIK, ticker, company name, accession number, filing date, fiscal year |
| `TaggedSentence` | One sentence + boolean flags: `is_forward_looking`, `has_company_ref` |
| `SectionDocument` | One section from one filing = list of `TaggedSentence` + `FilingMetadata` |
| `GlossaryTerm` | Domain term + aliases, definition, frequency, domain tags, section scope |
| `GlossaryStore` | Dict of `GlossaryTerm` with dedup/merge logic |

### LLM Abstraction: `python/models/llm_client.py`

Single `LLMClient` class wraps Ollama, Anthropic, and OpenAI. Set `LLM_PROVIDER` env var to switch:

```python
client = LLMClient()
response = client.complete("Extract risk factors from this text...", system="You are...")
```

Ollama has exponential backoff retry (5s → 10s → 20s → 40s → 80s) to handle VRAM eviction after GPU crashes.

---

### Stage 1: Preprocessing

**Script:** `python/run_preprocessing.py`

**What it does:**
1. Walks `edgar_RiskFactors/`, `edgar_BusinDescr/`, `edgar_MgmtDisc/` directories
2. Parses the header block (CIK, company name, filing date, etc.)
3. Strips HTML/XBRL tags (`cleaner.py`)
4. Segments text into sentences using spaCy (`segmenter.py`)
5. Tags each sentence for forward-looking language and company coreferences (`tagger.py`)
6. Saves as `SectionDocument` JSON

**Output:** `python/data/preprocessed/{risk_factors,business,mda}/`

```bash
# All sections
python python/run_preprocessing.py

# One section
python python/run_preprocessing.py --section risk_factors

# Re-process already-done files
python python/run_preprocessing.py --overwrite
```

**spaCy model note:** Large model (`en_core_web_lg`) gives better sentence boundaries. The `max_length` limit was raised to 3,000,000 chars to handle very long filings (fixed in Session 8).

**Fiscal year derivation:**
- Filing in Jan/Feb/Mar of year Y → fiscal year = Y-1
- Filing in Apr–Dec of year Y → fiscal year = Y

---

### Stage 2: Glossary Extraction

**Script:** `python/run_glossary.py`

**What it does:**
- Reads preprocessed JSON files
- Extracts domain-specific terminology (financial, operational, regulatory, risk language)
- Optionally uses LLM for definition generation
- Outputs a merged `glossary.json`
- Optionally pushes terms to ChromaDB for semantic search

**Output:** `python/data/glossary/glossary.json`

```bash
python python/run_glossary.py --rules-only    # fast, no LLM
python python/run_glossary.py                 # full LLM extraction
python python/run_glossary.py --index-chroma  # also populate ChromaDB
```

---

### Stage 3: KG Population

**Script:** `python/run_kg_population.py`

**What it does:**
1. Reads preprocessed `SectionDocument` JSON files
2. Extracts entities and relationships (spaCy NER or LLM)
3. Normalizes entity names (deduplication)
4. Writes typed nodes and edges to Neo4j

**Two modes:**
- `--fast` — spaCy NER. No GPU needed. Processes the full corpus quickly. Some noise in entity recognition.
- Default — LLM extraction. Higher quality but requires working GPU (Ollama) or API key. Currently blocked on GPU stability.

**Checkpointing:** `python/data/kg_export/.checkpoint.json`
- Tracks which documents have been processed per section
- Re-running the same command safely skips already-done documents
- Delete this file to force a complete re-run

```bash
# Setup (once only)
python python/run_kg_population.py --apply-schema

# Test (no writes)
python python/run_kg_population.py --dry-run --section risk_factors --limit 1

# Fast mode — recommended for full corpus
python python/run_kg_population.py --fast --section risk_factors
python python/run_kg_population.py --fast

# LLM mode (requires GPU/API)
python python/run_kg_population.py --section risk_factors
```

---

### Module Map

```
python/
├── config.py                    ← ALL paths and env vars (start here)
├── models/
│   ├── schemas.py               ← Pydantic data models
│   └── llm_client.py            ← LLM abstraction (Ollama / Anthropic / OpenAI)
├── preprocessing/
│   ├── cleaner.py               ← Strip HTML/XBRL, normalize whitespace
│   ├── segmenter.py             ← spaCy sentence segmentation
│   ├── tagger.py                ← Forward-looking + coreference flags
│   └── pipeline.py              ← Orchestration: R .txt → SectionDocument JSON
├── glossary/
│   ├── extractor.py             ← LLM + rule-based term extraction
│   └── vector_store.py          ← ChromaDB integration
├── kg_population/
│   ├── extractor.py             ← LLM entity/relation extraction with section-tailored prompts
│   ├── ner_extractor.py         ← spaCy fast-mode extraction
│   ├── normaliser.py            ← Entity deduplication and normalization
│   ├── writer.py                ← Neo4j write operations
│   └── pipeline.py              ← Checkpoint-aware orchestration
└── ontology/
    ├── nodes.py                 ← 18 typed node classes
    ├── relations.py             ← 25 relation types
    └── neo4j_schema.py          ← Constraints, indexes, graph write operations
```

---

## 6. Neo4j — Graph Database

### Ontology: Node Types (18 total)

| Category | Node Type | Description |
|----------|-----------|-------------|
| Core | `Company` | A public company with a CIK |
| Core | `Filing` | One 10-K filing (identified by accession number) |
| Core | `Section` | One section within a filing (Item 1, 1A, or 7) |
| Core | `FiscalYear` | Year anchor node (e.g. `fy_2023`) |
| Business | `BusinessSegment` | Business unit or division |
| Business | `Product` | Product or service offering |
| Business | `GeographicMarket` | Country/region of operation |
| Business | `CustomerSegment` | Target customer category |
| Business | `Competitor` | Named competitor company |
| Business | `Regulation` | Named law or regulatory body |
| Risk | `RiskFactor` | Named risk from Item 1A |
| Risk | `RiskDriver` | Cause or source of a risk |
| Risk | `RiskConsequence` | Potential outcome of a risk |
| Risk | `Mitigation` | Action taken to reduce a risk |
| Financial | `FinancialMetric` | Revenue, EBITDA, etc. |
| Financial | `FinancialPeriod` | Quarter/year reference |
| Financial | `ManagementOutlook` | Forward-looking management statement |
| Financial | `MacroFactor` | Macro-economic condition (inflation, rates, etc.) |

### Ontology: Relation Types (25 total)

```
Structural:   FILED_BY, HAS_SECTION, FILED_IN, PRECEDES
Business:     HAS_SEGMENT, OFFERS, OPERATES_IN, TARGETS, COMPETES_WITH, SUBJECT_TO, INCLUDES
Risk:         HAS_RISK, CAUSED_BY, MAY_RESULT_IN, MITIGATED_BY, RELATED_TO, SUPERSEDES
MD&A:         REPORTS, ATTRIBUTED_TO, DRIVEN_BY, IMPACTED_BY, HAS_OUTLOOK, REFERENCES
Cross-sec:    AFFECTS, MATERIALISED_AS, CITED_IN, REPORTED_IN  (reserved, not yet built)
```

### FiscalYear Design

This is the key design innovation. Instead of embedding the year in every node, we use anchor `FiscalYear` nodes chained with `PRECEDES`:

```
(fy_2022)-[:PRECEDES]->(fy_2023)-[:PRECEDES]->(fy_2024)
                                                    |
                                              [:FILED_IN]
                                                    |
                                               (Filing)
                                                    |
                                             [:FILED_BY]
                                                    |
                                               (Company)
```

This enables temporal queries across all filings without Neo4j Enterprise multi-database.

### Node ID Conventions (deterministic, idempotent)

| Node | ID Format |
|------|----------|
| Company | `{cik}` |
| Filing | `{accession_number}` |
| FiscalYear | `fy_{year}` |
| RiskFactor | `{cik}_{accession}_risk_{seq:04d}` |
| RiskDriver | `rd_{slug}` |
| Section | `{accession_number}_{section_type}` |

IDs are deterministic so repeated runs safely upsert (MERGE) rather than duplicate.

### Useful Cypher Queries

```cypher
-- Count all nodes by type
MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count ORDER BY count DESC;

-- Company with filings
MATCH (c:Company)-[:FILED_BY]-(f:Filing) RETURN c.name, count(f) AS filings ORDER BY filings DESC LIMIT 20;

-- Risk drivers across all companies
MATCH (r:RiskFactor)-[:CAUSED_BY]->(d:RiskDriver) RETURN d.name, count(r) AS mentions ORDER BY mentions DESC LIMIT 20;

-- Competitor network
MATCH (c1:Company)-[:COMPETES_WITH]->(c2:Company) RETURN c1.name, c2.name LIMIT 50;

-- All risks for Apple over time
MATCH (c:Company {name:"APPLE INC"})-[:FILED_BY]-(f:Filing)-[:FILED_IN]-(fy:FiscalYear)
      (f)-[:HAS_SECTION]-(s:Section)-[:HAS_RISK]-(r:RiskFactor)
RETURN fy.year, r.text ORDER BY fy.year;
```

---

## 7. App Layer

### 10k-monitor (`app/10k-monitor/`)

A web app for viewing and comparing Risk Factor changes between consecutive 10-K filings.

**Stack:** Next.js 14 (frontend) + FastAPI (backend) + SQLite (cache)

**What it does:**
- Search companies by name or ticker
- View filing timeline for any company
- Side-by-side sentence diff of Risk Factors between two filings
- Severity scoring: HIGH / MED / LOW changes

**Backend endpoints:**
```
GET  /api/health                          → Index stats
GET  /api/companies?q=AMD                 → Search companies
GET  /api/companies/{cik}                 → Company detail + filing list
GET  /api/delta/{acc_latest}/{acc_prev}   → Compute risk factor diff
POST /api/reindex                         → Force re-index from preprocessed JSON
```

**Run it:**
```bash
# Backend
cd app/10k-monitor/backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Frontend (separate terminal)
cd app/10k-monitor/frontend
npm install
npm run dev
# → http://localhost:3000
```

---

### ghostlink (`app/ghostlink/`)

Multi-feature analytics platform — **architecture planned, implementation pending**.

**Planned features (priority order):**
- **P0:** Risk timeline, delta view, forward-looking sentence filter
- **P1:** Competitor graph explorer, semantic search (ChromaDB), Cypher query builder
- **P2:** Financial metrics dashboard, macro exposure mapping, watchlist + alerts
- **P3:** PDF export, sector reports, RAG natural-language interface

**Architecture decision:** Initially reads preprocessed JSON directly (faster to build, avoids Neo4j dependency while graph is sparse). Will migrate to Neo4j queries for multi-hop graph features (competitor networks, cross-company risk links).

---

## 8. Architecture Deep Dive

### Full Data Flow

```
SEC EDGAR
    │
    ▼ (R: edgar package)
edgar_RiskFactors/<year>/<cik>_*.txt
edgar_BusinDescr/<year>/<cik>_*.txt
edgar_MgmtDisc/<year>/<cik>_*.txt
    │
    ▼ (Python: preprocessing/)
python/data/preprocessed/risk_factors/<cik>_<accession>.json
python/data/preprocessed/business/<cik>_<accession>.json
python/data/preprocessed/mda/<cik>_<accession>.json
    │
    ├──▶ (Python: glossary/) ──▶ python/data/glossary/glossary.json
    │                        ──▶ python/data/chroma/  (ChromaDB)
    │
    ▼ (Python: kg_population/)
Neo4j ─ nodes: Company, Filing, Section, RiskFactor, RiskDriver, ...
       ─ edges: FILED_BY, HAS_SECTION, HAS_RISK, CAUSED_BY, ...
    │
    ▼ (App layer)
app/10k-monitor  ─ risk delta web UI
app/ghostlink     ─ full analytics platform (planned)
```

### File Naming Conventions

R output files: `{cik}_{accession_number}.txt`
- Example: `320193_0000320193-23-000106.txt`

Preprocessed JSON: `{cik}_{accession_number}.json`
- Mirrors R output naming exactly

### How the R header is parsed

`preprocessing/pipeline.py` reads each `.txt` file and splits on the first blank line:

```python
# Lines before blank line = header
# Lines after blank line = section text
header = {
    "CIK": "320193",
    "Company Name": "APPLE INC",
    "Form Type": "10-K",
    "Filing Date": "2023-11-03",
    "Accession Number": "0000320193-23-000106"
}
```

### Automation (Cron)

```bash
# Add these to crontab with: crontab -e

# Daily at 6 AM: download new filings from EDGAR
0 6 * * * cd /path/to/SEC_KG && bash run_daily_update.sh >> logs/daily_update.log 2>&1

# Hourly: preprocess any new .txt files
0 * * * * cd /path/to/SEC_KG && python3 python/run_preprocessing.py >> logs/preprocessing.log 2>&1
```

---

## 9. Current Status (as of 2026-02-24 22:50)

### Data Collection

| Year | Risk Factors | Business | MD&A | Status |
|------|-------------|----------|------|--------|
| 2024 | 2,677 | 2,702 | 2,848 | In progress — needs restart |
| 2023 | 2,087 | 2,098 | 2,221 | In progress — needs restart |
| 2022 | 773 | 809 | 824 | Done |
| 2021 | 632 | 677 | 682 | Done |
| 2020 | 489 | 522 | 521 | Done |
| 2019 | 952 | 1,030 | 1,035 | Done |
| 2018 | 365 | 410 | 410 | Done |
| 2017 | 561 | 600 | 597 | Done |
| 2016 | 1,131 | 1,194 | 1,174 | Done |
| 2015 | 1,555 | 1,675 | 1,643 | Done |
| 1993–2014 | 0 | 0 | 0 | Queued |

**Total (2015–2024):** ~32,920 extracted `.txt` files

### Preprocessing

- **~55,600 documents preprocessed** (~17,858 RF / 18,745 business / 18,997 MDA as of 2026-02-24)
- Hourly cron job keeps pace with ongoing collection

### Knowledge Graph

- **Graph wiped and restarted clean on 2026-02-24** after discovering multigraph edge buildup (old schema used `filing_ref` in MERGE key, creating up to 12 parallel edges per node pair — made writes progressively slower)
- **OOM crash fixed (2026-02-24):** Old loader read all 55,600 docs into RAM at startup (~40 GB → killed after ~4h). Now lazy-loads one doc at a time. Committed `7ff22f5`.
- **Throttle flag added:** `--delay N` sleeps N seconds between docs to avoid CPU overload
- **Running overnight:** `nohup python3 python/run_kg_population.py --fast --delay 2 > logs/kg_population_throttled.log 2>&1 &` (PID 8839)
- **~3,961 / 55,600 docs done** (checkpoint as of 22:50 on 2026-02-24); ~8–23s/doc with delay
- Monitor: `tail -f logs/kg_population_throttled.log`
- Check progress: `python3 -c "import json; d=json.load(open('python/data/kg_export/.checkpoint.json')); print(len(d), '/ ~55600')"`
- Checkpoint at `python/data/kg_export/.checkpoint.json`
- **Neo4j runs in Docker:** `docker start neo4j-sec` if not running

### Pipeline Performance (after 2026-02-24 optimisation)

The KG population pipeline was profiled and optimised (commit `2906cb5`):

| Fix | Before | After |
|-----|--------|-------|
| spaCy: `nlp.pipe(batch_size=64)` vs per-sentence calls | — | ~5x NER speedup |
| Neo4j: single `write_document()` session per doc | ~8 round-trips/doc | 1 session/doc |
| Edge MERGE: `(a)-[r:TYPE]->(b)` without `filing_ref` key | multigraph, growing O(n) | one edge per pair |
| Checkpoint: every 50 docs instead of every doc | — | minor I/O reduction |
| **Total** | **3–4s/doc** | **~1s/doc** |

### Glossary

- **65 KB** glossary from ~3,748 docs (rules-only, stale)
- Full corpus rebuild queued: `python3 python/run_glossary.py --rules-only --index-chroma`

### App Layer

- **10k-monitor:** Built and functional (Next.js + FastAPI + SQLite)
- **ghostlink:** Architecture planned, implementation not started

### Log Locations

| Log | Command to view |
|-----|----------------|
| KG population (current) | `tail -f logs/kg_population_throttled.log` |
| R collection per year | `tail -f logs/collection_<year>_worker_N.log` |
| Preprocessing cron | `tail -f logs/preprocessing.log` |
| Daily EDGAR update | `tail -f logs/daily_update.log` |

### Known Issues

1. **Python venv broken** — deps are in user Python (`~/.local/lib/python3.13/`) not `.venv/`. Everything still works; just use `python3` directly.
2. **RTX 5090 GPU instability** — GSP firmware crash on CUDA ops. Fix applied (`NVreg_EnableGpuFirmware=0`). LLM extraction (`kg_population` non-fast mode) blocked until stable.
3. **spaCy NER noise** — `--fast` mode produces false-positive Competitor nodes (e.g. "Board of Directors", "LLP", "Internal Audit" tagged as ORG). Addressed in E-4 (graph quality audit).

---

## 10. What To Do Next

### Running overnight (no action needed)

```bash
# KG population — check progress:
tail -f logs/kg_population_throttled.log
python3 -c "import json; d=json.load(open('python/data/kg_export/.checkpoint.json')); print(len(d), '/ ~55600 docs')"
```

### Tomorrow — first three things

```bash
# 1. Restart R collection (2023 + 2024 workers stopped)
nohup bash run_parallel_collection.sh 2023 4 > logs/collection_2023_restart.log 2>&1 &
nohup bash run_parallel_collection.sh 2024 4 > logs/collection_2024_restart.log 2>&1 &

# 2. Start glossary rebuild (failed last session — log was 0 bytes, needs diagnosis)
nohup python3 python/run_glossary.py --rules-only --index-chroma > logs/glossary_rebuild.log 2>&1 &

# 3. Check KG checkpoint and adjust --delay if CPU still high
python3 -c "import json; d=json.load(open('python/data/kg_export/.checkpoint.json')); print(len(d), '/ ~55600 docs')"
```

### While KG population runs — glossary rebuild (safe to run in parallel)

```bash
# Fast, CPU-only, ~30 min on full corpus
python3 python/run_glossary.py --rules-only --index-chroma
```

### After 2023/2024 collection completes

```bash
# Collect historical years (1993–2014)
bash run_smart_collection.sh 1993 2014 4 6
```

### After KG population completes (~15h from 2026-02-24)

```bash
# 1. Graph quality audit — remove NER false positives (E-4)
#    Run Cypher in Neo4j browser to flag/delete junk Competitor nodes

# 2. Cross-year semantic linking (E-1) — biggest value-add
#    PERSISTED_TO / EMERGED_IN / RESOLVED_IN edges between RiskFactor nodes

# 3. Re-run with LLM once GPU is stable (higher quality extraction)
rm python/data/kg_export/.checkpoint.json
python3 python/run_kg_population.py --section risk_factors
```

### Graph enrichment (biggest value-add)

Once the graph is fully populated, add cross-year temporal links:

```cypher
-- Concept: link risk factors that persist across years for the same company
-- "This risk factor existed in 2022, 2023, and 2024"
-- Edge type: PERSISTED_TO (not yet built)
```

This requires the `PERSISTED_TO` and `EMERGED_IN` cross-year semantic linking work (deferred, design in TRACKER.md).

### Product features

- Build out `ghostlink` multi-feature analytics platform
- Add RAG natural-language query interface (ChromaDB + LLM)
- Analyst dashboard with risk timelines, competitor maps, sector reports

---

## 11. Command Quick Reference

### R Data Collection

```bash
# Single year, parallel workers
bash run_parallel_collection.sh 2024           # 4 workers (default)
bash run_parallel_collection.sh 2024 8         # 8 workers
bash run_parallel_collection.sh 2024 4 1000    # first 1000 companies only

# Multiple years concurrently
bash run_smart_collection.sh 1993 2014 4 6     # 4 years × 6 workers

# All years loop
bash run_all_years.sh                          # 1993→now
bash run_all_years.sh 2015 2024 4              # 2015–2024

# Direct R (single year, one process)
Rscript get_all_companies.R --year 2024
Rscript get_all_companies.R --year 2024 --offset 500 --limit 100
```

### Python Pipeline

```bash
# Preprocessing
python python/run_preprocessing.py
python python/run_preprocessing.py --section risk_factors
python python/run_preprocessing.py --overwrite

# Glossary
python python/run_glossary.py --rules-only
python python/run_glossary.py
python python/run_glossary.py --index-chroma

# KG Population
python python/run_kg_population.py --apply-schema   # setup (once)
python python/run_kg_population.py --dry-run --limit 1
python python/run_kg_population.py --fast
python python/run_kg_population.py --fast --section risk_factors
python python/run_kg_population.py                  # LLM mode
```

### Neo4j

```bash
docker start neo4j-sec        # start
docker stop neo4j-sec         # stop
docker logs neo4j-sec         # view logs
# Browser: http://localhost:7474
```

### App layer

```bash
# 10k-monitor backend
cd app/10k-monitor/backend && uvicorn main:app --reload --port 8000

# 10k-monitor frontend
cd app/10k-monitor/frontend && npm run dev    # http://localhost:3000
```

### Git

```bash
git add -p           # review and stage changes
git commit -m "..."
git push
```

---

## 12. Key Design Decisions (and Why)

### Why R for collection?

The `edgar` CRAN package handles EDGAR authentication, rate limiting, and section extraction out of the box. Rewriting this in Python would have taken weeks. R does this part well; Python does everything else.

### Why extract 3 sections (not the whole filing)?

Item 1 (Business), Item 1A (Risk Factors), and Item 7 (MD&A) together give you ~80% of the structured information in a 10-K. The full document includes financial tables, exhibits, and boilerplate that are harder to parse and less useful for NLP.

### Why Neo4j?

Graph databases handle the natural structure of the data: companies link to filings link to risk factors link to drivers. Temporal queries ("show me how this risk evolved across years") and multi-hop queries ("find competitors who share this risk driver") are Cypher queries rather than complex SQL joins.

### Why FiscalYear anchor nodes?

Neo4j Community Edition (free) only supports one database. Instead of fighting that constraint, FiscalYear nodes act as a temporal anchor. Any year-level query starts from `MATCH (fy:FiscalYear {year: 2023})`. The `PRECEDES` chains enable temporal traversals.

### Why preprocessed JSON as an intermediate format?

The R output is raw text. Preprocessing (cleaning, segmenting, tagging) is expensive but idempotent. Storing the output as JSON means the app layer can read structured data without running spaCy every time. It also decouples the collection layer from the analysis layer.

### Why spaCy NER for fast KG population?

LLM extraction is much higher quality but requires a GPU and is slow. spaCy NER processes the full corpus in hours on CPU. The plan is: populate the graph with spaCy first (good enough for most queries), then selectively enrich high-value sections with LLM extraction when the GPU is stable.

### Why ChromaDB?

Sentence-level semantic search is not what Neo4j does well. ChromaDB stores vector embeddings of every sentence and supports cosine similarity search. The two databases complement each other: Neo4j for structural/relational queries, ChromaDB for semantic/similarity queries.

---

## 13. Troubleshooting

### RTX 5090 GSP firmware crash

Symptom: CUDA operations crash with GSP firmware error.

Fix:
```bash
echo 'options nvidia NVreg_EnableGpuFirmware=0' | sudo tee /etc/modprobe.d/nvidia-gsp.conf
sudo update-initramfs -u
# Reboot
```

### spaCy crashes on large filings

Symptom: `ValueError: max_length exceeded` on very long filings.

Fix (already applied in `segmenter.py`):
```python
nlp.max_length = 3_000_000  # raise from default 1M
```

If you see this again, check `python/preprocessing/segmenter.py` line that sets `max_length`.

### Neo4j connection refused

1. Check Docker is running: `docker ps`
2. Start container: `docker start neo4j-sec`
3. Wait 30 seconds before retrying
4. Check logs: `docker logs neo4j-sec`

### Ollama VRAM eviction / timeout

Symptom: LLM calls fail intermittently, especially after GPU crashes.

The `LLMClient` in `python/models/llm_client.py` retries with exponential backoff (up to 5 attempts). If it still fails, restart Ollama:

```bash
systemctl restart ollama
# or
pkill ollama && ollama serve &
```

### Python deps not found

If `import` fails despite having installed requirements:

```bash
# Check which python you're using
which python3
python3 -c "import sys; print(sys.path)"

# Install to the same Python
python3 -m pip install -r python/requirements.txt
```

### KG population running slowly

The pipeline was profiled on 2026-02-24. Bottlenecks found and fixed (commit `2906cb5`):

1. **spaCy per-sentence calls** — fixed by `nlp.pipe(batch_size=64)` in `ner_extractor.py`
2. **Neo4j session per write** — fixed by `write_document()` single-session method in `neo4j_schema.py`
3. **Edge MERGE with `filing_ref` in key** — created multigraph; fixed by removing from MERGE pattern

If still slow, profile with:
```bash
python3 -c "
import time, sys
sys.path.insert(0, 'python')
from models.schemas import SectionDocument
from kg_population.ner_extractor import NERExtractor
import config
files = sorted((config.PREPROCESSED_DIR / 'risk_factors').glob('*.json'))[:5]
docs = [SectionDocument.model_validate_json(f.read_text()) for f in files]
ext = NERExtractor()
t = time.time()
for d in docs: ext.extract(d)
print(f'NER only: {(time.time()-t)/5:.2f}s/doc')
"
```

Expected: ~0.5-1s/doc NER, ~0.1-0.3s/doc Neo4j write on a clean graph.

If the graph has grown large and MERGE is slowing down again, check for edge count per node:
```cypher
MATCH (c:Company)-[r:COMPETES_WITH]->(comp)
WITH c, comp, count(r) AS cnt WHERE cnt > 1
RETURN count(*) AS problem_pairs
```
If `problem_pairs > 0`, the graph has accumulated parallel edges. Wipe and restart:
```bash
python3 -c "
import sys; sys.path.insert(0,'python')
from ontology.neo4j_schema import Neo4jGraph
g = Neo4jGraph()
while True:
    r = g.query('MATCH (n) WITH n LIMIT 10000 DETACH DELETE n RETURN count(n) AS d')
    if r[0]['d'] == 0: break
    print('deleted', r[0]['d'])
g.close()
"
python3 python/run_kg_population.py --apply-schema
echo '[]' > python/data/kg_export/.checkpoint.json
nohup python3 -u python/run_kg_population.py --fast > logs/kg_population_fast.log 2>&1 &
```

### R collection stalling

Check log files in `logs/collection_<year>_worker_N.log`. Common causes:
- EDGAR rate limiting (the `edgar` package handles backoff, but can stall on network issues)
- R memory pressure (reduce `--batch-size` or number of workers)
- CIK not found in EDGAR (safe to ignore, logged as warning)

### Graph looks empty after population

Check the checkpoint file:
```bash
cat python/data/kg_export/.checkpoint.json | python3 -m json.tool | head -20
```

If everything is checkpointed as done but the graph is empty, the writer may have been in dry-run mode. Check your command used `--fast` and not `--dry-run`. Delete the checkpoint and re-run:
```bash
rm python/data/kg_export/.checkpoint.json
python python/run_kg_population.py --fast --section risk_factors
```

---

*Last updated: 2026-02-24. Update this file whenever the project structure, commands, or status materially change. Push to GitHub after every session.*
