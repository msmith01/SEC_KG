# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

A pipeline that builds a **knowledge graph of SEC 10-K filings** stored in Neo4j. It has two layers:

1. **R layer** — downloads raw filings from EDGAR and extracts three sections per filing: Business Description (Item 1), Risk Factors (Item 1A), and MD&A (Item 7).
2. **Python layer** — preprocesses those extracted `.txt` files into structured JSON, builds a domain glossary, and populates a Neo4j graph with typed ontology nodes and edges.

ChromaDB provides a companion vector store for sentence-level semantic search.

## Environment

Copy `.env.example` to `.env` and fill in values. Key settings:

- `LLM_PROVIDER` — `ollama` (default, local), `anthropic`, or `openai`
- Neo4j runs locally; start it before running the Python pipeline
- Python virtualenv is at `.venv/` — activate with `source .venv/bin/activate` (but the bin only has `python`/`python3`, so use `.venv/bin/python` directly or install properly)

Install Python deps:
```bash
pip install -r python/requirements.txt
python -m spacy download en_core_web_lg   # or en_core_web_sm as fallback
```

## Graph Design: FiscalYear Anchor Nodes

Each filing is linked to a `FiscalYear` node (`fy_{year}`). FiscalYear nodes are chained with `PRECEDES` edges. This gives a temporal layer to the graph without needing multiple databases (Neo4j Community only supports one database).

```
(FiscalYear:fy_2022)-[:PRECEDES]->(FiscalYear:fy_2023)-[:PRECEDES]->(FiscalYear:fy_2024)
                                                                            |
                                                                      (Filing)-[:FILED_BY]->(Company)
```

Cross-year linking (e.g. `PERSISTED_TO` between RiskFactor nodes) is deferred — the FiscalYear scaffold is in place for when that work begins.

## R: Data Collection

The R scripts use the `edgar` CRAN package. `ticker_to_cik.csv` maps tickers to EDGAR CIK numbers.

```bash
# Download daily master index CSVs and fetch 10-K data for first 10 tickers
Rscript get_daily_master.R

# Scale to all companies (resumable — skips already-collected CIKs)
Rscript get_all_companies.R
Rscript get_all_companies.R --year 2020 --batch-size 100
Rscript get_all_companies.R --year 2020 --offset 500 --limit 100

# Parallel collection for a single year (logs to logs/collection_<year>_worker_N.log)
bash run_parallel_collection.sh 2024           # 4 workers, all ~5128 companies
bash run_parallel_collection.sh 2020 8         # 8 workers
bash run_parallel_collection.sh 2020 4 1000    # 4 workers, first 1000 companies

# All years 1993–present (years run sequentially, companies in parallel per year)
bash run_all_years.sh                          # 1993 → now, 4 workers/year
bash run_all_years.sh 2010                     # 2010 → now
bash run_all_years.sh 2010 2020 8              # 2010–2020, 8 workers/year
```

Output directories written by R (year-organised):
- `edgar_DailyMasterCSVs/` — daily index CSVs (current year top-ups)
- `edgar_MasterIndex/` — quarterly master index `.Rda` files (1993+, from `getMasterIndex()`)
- `edgar_Filings/` — raw downloaded filing text files
- `edgar_RiskFactors/<year>/` — extracted Item 1A sections
- `edgar_BusinDescr/<year>/` — extracted Item 1 sections
- `edgar_MgmtDisc/<year>/` — extracted Item 7 sections

`helper_functions.R` provides `getRiskFactors()`, `fetch10KData()`, and related wrappers around the `edgar` package's `getFilings`, `getMgmtDisc`, `getBusinDescr` functions.

## Python: Pipeline Stages

All Python scripts are run from the repo root. The venv python is `.venv/bin/python`.

### Stage 1 — Preprocessing

Reads R `.txt` files, cleans text, segments into sentences, tags forward-looking language and company coreferences. Outputs `SectionDocument` JSON to `python/data/preprocessed/{section_type}/`.

```bash
python python/run_preprocessing.py                        # all three sections
python python/run_preprocessing.py --section risk_factors # one section
python python/run_preprocessing.py --overwrite            # re-process existing
```

### Stage 2 — Glossary Extraction

Builds a cross-company domain glossary from preprocessed documents using LLM + rule-based extraction. Optionally indexes into ChromaDB.

```bash
python python/run_glossary.py                   # LLM + rules
python python/run_glossary.py --rules-only      # fast, no LLM
python python/run_glossary.py --index-chroma    # also push to ChromaDB
```

### Stage 3 — KG Population

Extracts entities/relations from preprocessed documents and writes them into Neo4j. Checkpointed — re-runs skip already-processed documents.

```bash
# Always apply schema once before first real run
python python/run_kg_population.py --apply-schema

# Dry run (no Neo4j writes) — good for testing
python python/run_kg_population.py --dry-run --section risk_factors --limit 1

# Fast mode using spaCy NER instead of LLM
python python/run_kg_population.py --fast --section risk_factors

# Full run
python python/run_kg_population.py --section risk_factors
python python/run_kg_population.py   # all sections
```

KG population checkpoint: `python/data/kg_export/.checkpoint.json`

## Architecture

```
R extraction (edgar_*/ dirs)
        ↓
python/preprocessing/   — cleaner.py, segmenter.py, tagger.py, pipeline.py
        ↓ SectionDocument JSON (python/data/preprocessed/)
python/glossary/        — extractor.py, vector_store.py (ChromaDB)
python/kg_population/   — extractor.py (LLM) / ner_extractor.py (spaCy)
                          normaliser.py → writer.py → Neo4j
```

**Central config**: `python/config.py` — all paths and env var reads. Nothing downstream hardcodes paths.

**Data models** (`python/models/schemas.py`):
- `FilingMetadata` — provenance (CIK, ticker, accession number, filing date, fiscal year)
- `TaggedSentence` — one sentence with forward-looking and coreference tags
- `SectionDocument` — one section per filing (list of `TaggedSentence`)
- `GlossaryTerm` / `GlossaryStore` — cross-company glossary with merge logic

**LLM abstraction** (`python/models/llm_client.py`): `LLMClient` wraps Ollama, Anthropic, and OpenAI behind a single `client.complete(prompt, system=...)` call. Switch provider via `LLM_PROVIDER` env var. Ollama retries with exponential backoff on VRAM eviction.

**Neo4j ontology** (`python/ontology/`): `nodes.py` defines typed node classes (Company, Filing, Section, RiskFactor, RiskDriver, RiskConsequence, Mitigation, Product, Competitor, etc.); `relations.py` defines typed edges; `neo4j_schema.py` manages uniqueness constraints and graph write operations.

## Key Data Flow Detail

The R file header format (parsed by `preprocessing/pipeline.py`):
```
CIK: <value>
Company Name: <value>
Form Type: <value>
Filing Date: YYYY-MM-DD
Accession Number: <value>

<section text>
```

A company is considered "already collected" (skipped by `get_all_companies.R`) if output files matching `{cik}_*.txt` exist in all three of `edgar_RiskFactors/`, `edgar_BusinDescr/`, and `edgar_MgmtDisc/`.

Fiscal year is derived from filing date: filings in Q1 (month ≤ 3) are assumed to report on the prior calendar year.
