# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## GitHub Workflow — IMPORTANT

The repo is at **https://github.com/msmith01/SEC_KG** (private). Remote is `git@github.com:msmith01/SEC_KG.git`.

**After any session that changes pipeline code, scripts, or config:**
1. Update `REINSTALL.md` if the change affects how someone would rebuild from scratch (new deps, new scripts, new steps, changed commands, etc.)
2. Commit all changed files with a clear message
3. Push to GitHub

```bash
git add -p          # review and stage changes
git commit -m "..."
git push
```

Push frequently — at minimum once per session, ideally after each meaningful change.

## What This Project Is

A pipeline that builds a **knowledge graph of SEC 10-K filings** stored in Neo4j. It has two layers:

1. **R layer** — downloads raw filings from EDGAR and extracts three sections per filing: Business Description (Item 1), Risk Factors (Item 1A), and MD&A (Item 7).
2. **Python layer** — preprocesses those extracted `.txt` files into structured JSON, builds a domain glossary, and populates a Neo4j graph with typed ontology nodes and edges.

ChromaDB provides a companion vector store for sentence-level semantic search.

## Environment

Copy `.env.example` to `.env` and fill in values. Key settings:

- `LLM_PROVIDER` — `ollama` (default, local), `anthropic`, or `openai`
- Neo4j runs in Docker (`neo4j-sec`); start it before running the Python pipeline: `docker start neo4j-sec`
- Python virtualenv is at `.venv/` — activate with `source .venv/bin/activate` (but the bin only has `python`/`python3`, so use `.venv/bin/python` directly or install properly)

## Accessing Neo4j Browser from Windows

The Ubuntu machine runs Neo4j in Docker, bound on `0.0.0.0:7474` (browser) and `0.0.0.0:7687` (bolt). It is accessible from any machine on the LAN.

**Ubuntu machine IP:** `192.168.1.39`

Steps:
1. Start Neo4j on Ubuntu (if not already running): `docker start neo4j-sec`
2. On Windows, open a browser and go to: `http://192.168.1.39:7474`
3. In the connection dialog use:
   - **Connect URL:** `bolt://192.168.1.39:7687`
   - **Username:** `neo4j`
   - **Password:** `password`

> Note: the bolt URL in the browser dialog must use the Ubuntu LAN IP, not `localhost`.

**Useful starter queries:**
```cypher
// FiscalYear chain
MATCH p=(fy:FiscalYear)-[:PRECEDES*]->(fy2:FiscalYear) RETURN p LIMIT 20

// Company → filings → fiscal year
MATCH p=(c:Company)<-[:FILED_BY]-(f:Filing)-[:FILED_IN]->(fy:FiscalYear)
RETURN p LIMIT 50

// Risk factors with drivers
MATCH p=(rf:RiskFactor)-[:DRIVEN_BY]->(rd:RiskDriver)
RETURN p LIMIT 100
```

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

## System Health — GPU, Load, and Ollama

### GPU Crash Pattern

The RTX 5090 GPU crashes periodically. When it does, Ollama automatically falls back to running the LLM on CPU. A 20.9B model on CPU consumes **2000%+ CPU** (most of the 24 cores), which overloads the machine and can trigger a cascade:

```
GPU driver crash → Ollama falls back to CPU → 20+ cores saturated
→ system overheats/OOMs → GPU crashes again on next boot
```

**Check GPU status before starting any LLM work:**
```bash
nvidia-smi
# If you see "Unknown Error" or "No devices found" — GPU is crashed, do NOT start Ollama workloads
```

**Check `size_vram` via Ollama API:**
```bash
curl -s http://localhost:11434/api/ps | python3 -m json.tool
# size_vram: 0 means model is running on CPU — dangerous, will overload machine
```

### Safe Startup Order (after reboot)

Always follow this order to avoid overloading the machine:

1. **Reboot** — clears GPU driver crash state
2. **Verify GPU**: `nvidia-smi` — must show the RTX 5090 cleanly before continuing
3. **Start Neo4j**: `docker start neo4j-sec` — low footprint, safe any time
4. **Start R collection** — network I/O bound, low CPU per worker; use ≤4 workers per year
5. **Start chatbot** — only after GPU is verified; chatbot defaults to `ollama` provider
6. **Start LLM workloads** — only when home to monitor GPU temps and fan speed

### Next Session TODO (when home)

```bash
# 1. Check load
uptime

# 2. Reboot to clear GPU crash state
sudo reboot

# 3. After reboot — verify GPU
nvidia-smi

# 4. Start Neo4j
docker start neo4j-sec

# 5. Restart R collection (stops on reboot) — 8 workers total
nohup bash run_parallel_collection.sh 2023 2 > logs/collection_2023_resume3.log 2>&1 &
nohup bash run_parallel_collection.sh 2024 2 > logs/collection_2024_resume3.log 2>&1 &
nohup bash run_all_years.sh 1993 2014 4 > logs/historical_collection3.log 2>&1 &

# 6. Run 8K preprocessing on collected raw files
python3 python/run_preprocessing_8k.py --year 2014 2015 2016

# 7. If GPU healthy — start LLM-mode KG population (monitor fans)
nohup python3 python/run_kg_population.py --section risk_factors > logs/kg_llm_risk_factors.log 2>&1 &
watch -n 5 nvidia-smi
```

### Cooling Down an Overloaded Machine

If load average is high (check with `uptime`; target < number of cores):

```bash
# Check what's eating CPU
ps aux --sort=-%cpu | head -20

# Stop all R collection workers and orchestrators
kill $(ps aux | grep -E "(run_parallel_collection|get_all_companies|run_all_years|get_8k)" | grep -v grep | awk '{print $2}')

# Stop the chatbot
kill $(ps aux | grep "streamlit run" | grep -v grep | awk '{print $2}')

# Check if Ollama is running on CPU (size_vram: 0 is bad)
curl -s http://localhost:11434/api/ps | python3 -m json.tool

# Ollama will unload the model automatically after expires_at passes
# Once unloaded, load drops immediately
```

### Chatbot LLM Provider Warning

The chatbot sidebar defaults to `ollama`. Any question asked while Ollama is on CPU will trigger a slow CPU inference and spike load. If the GPU is not healthy, either:
- Switch the provider dropdown to `anthropic` before asking anything
- Or don't start the chatbot until GPU is verified

---

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
