# SEC Knowledge Graph Project — Session History & Status

*Generated: 2026-02-21. Covers all 8 Claude Code conversation sessions.*

---

## 1. Chronological Summary of Sessions

### Session 1 — 2026-02-18 (5dc9b9c0)
**Topic: Understanding the existing R scripts and initial design**

The project began with an existing set of R scripts in the repo:
- `get_daily_master.R` — downloads daily EDGAR index CSVs and processes 10-K filings
- `helper_functions.R` — extracts Item 1, Item 1A, and Item 7 text from raw filings
- `ticker_to_cik.csv` — ticker-to-CIK mapping table

The user wanted to understand what Items 7A (Quantitative Market Risk) and Item 8 (Financial Statements) contained. The decision was made to skip those for now and focus on Items 1, 1A, and 7.

**Key actions:**
- Identified Windows paths hardcoded in the R scripts and updated them for the Linux environment
- Adapted `get_daily_master.R` to run on the first 10 tickers from `ticker_to_cik.csv` (AIR, ABT, WDDD, ACU, BKTI, ADX, AMD, AEM, APD, CECO)

**Design document produced:** A full conceptual pipeline was designed covering the four sequential transformation stages:

```
Raw Filing Text
      → [Preprocessing] (clean, segment, tag, metadata)
      → [Glossary] (domain terms + definitions)
      → [Taxonomy] (hierarchical concept organisation)
      → [Ontology] (entity types, relation types, constraints, IDs)
      → [Knowledge Graph] (populated instances from text)
```

Each company was to produce three section-level KGs per filing year (Business Description, Risk Factors, MD&A), with cross-section linking deferred until schemas stabilised.

---

### Session 2 — 2026-02-19 Morning (cf3da10f) — The Main Build Session
**Topic: Building all four pipeline milestones from scratch**

This was the longest session (5.7 MB, ~8 hours of work). The user confirmed the architectural decisions: R for data collection, Python for NLP/KG, Neo4j as the graph database, ChromaDB as the vector store, and a local Ollama model (`gpt-oss:latest`) as the LLM with flexibility to switch to Claude/OpenAI APIs.

**Milestone 1 — Preprocessing layer (completed)**

Created the full Python package structure:

```
python/
├── config.py                    # Central config, all paths and env vars
├── .env.example
├── models/
│   ├── llm_client.py            # Unified LLM client (Ollama/Anthropic/OpenAI)
│   └── schemas.py               # Pydantic models (FilingMetadata, TaggedSentence,
│                                #   SectionDocument, GlossaryTerm, GlossaryStore)
├── preprocessing/
│   ├── cleaner.py               # HTML/XBRL stripping, whitespace normalisation
│   ├── segmenter.py             # spaCy sentence segmentation with regex fallback
│   ├── tagger.py                # Coreference + forward-looking sentence tags
│   └── pipeline.py              # Reads R .txt files → SectionDocument JSON
├── glossary/
│   ├── extractor.py             # Rule-based + LLM term extraction
│   └── vector_store.py          # ChromaDB sentence search + glossary lookup
├── ontology/
│   ├── nodes.py                 # 18 typed node classes with ID schemes
│   ├── relations.py             # 25 relation types + Edge model
│   └── neo4j_schema.py          # Constraints, indexes, upsert writer
├── kg_population/
│   ├── extractor.py             # Section-tailored LLM prompts → raw dicts
│   ├── normaliser.py            # Raw dicts → typed nodes/edges + dedup
│   └── pipeline.py              # End-to-end orchestrator
├── run_preprocessing.py
├── run_glossary.py
└── run_kg_population.py
```

**Milestone 2 — Glossary extraction (completed)**

Rule-based + LLM extraction of domain terms. ChromaDB integration for semantic sentence search. Verified working with 58 terms extracted from the 8 initial companies.

**Milestone 3 — Ontology as code + Neo4j schema (completed)**

18 node types and 25 relation types defined. Neo4j Docker container (`neo4j-sec`) started. Schema applied: 18 constraints + 7 indexes. Community Edition limitation noted: one database only, so multi-year data goes into a single database with `FiscalYear` anchor nodes.

**Milestone 4 — KG population pipeline (completed)**

LLM-based entity/relation extractor with dry-run mode. Also built a `--fast` mode using spaCy NER (no GPU required) for faster iteration. The initial demo on 8 companies in `--fast` mode completed in 39 seconds producing:
- 2,487 nodes
- 2,682 edges

NER noise noted: spaCy occasionally classifies financial phrases as ORG entities (e.g., "Website Access" as a competitor). LLM mode eliminates this.

**R pipeline scaling built:**
- `get_all_companies.R` — parameterised for year and offset, reads master index Rda files
- `run_parallel_collection.sh` — splits the ~7,880 unique CIKs across N workers
- Benchmarked at 36 seconds per company (download + extract 3 sections)
- Estimates: 4 workers → ~13 hrs, 8 workers → ~6.5 hrs for full corpus

**GPU issues began:** The RTX 5090 (Blackwell) started crashing with CUDA `unspecified launch failure` errors due to a GSP firmware bug. LLM mode via Ollama became unreliable. The `--fast` spaCy mode was used as a workaround.

**Neo4j browser access:** Resolved — exposed on `0.0.0.0:7474` via Docker, accessible from Windows at `http://192.168.1.38:7474` using `neo4j://192.168.1.38:7687`.

---

### Session 3 — 2026-02-19 Afternoon (210348f9)
**Topic: Post-reboot recovery, GPU stability, and resuming processing**

After a reboot to fix the GPU driver state, the user returned with the RTX 5090 showing idle. The session focused on getting everything running again.

**Actions:**
- Neo4j (`neo4j-sec` Docker container) restarted
- `.env` file created with correct Neo4j connection string
- Preprocessing re-run — all 29 documents confirmed preprocessed
- Schema re-applied to the clean Neo4j database
- Ollama restarted after post-reboot CUDA initialisation error

**GPU crashed again** during LLM KG population — CUDA kernel failure, GPU fell off PCIe bus. Root cause: RTX 5090 GSP firmware crash (`NV_ERR_GPU_IN_FULLCHIP_RESET`). Known driver/firmware bug with Blackwell GPUs.

**Fix applied:** Disabled GSP firmware mode:
```bash
echo 'options nvidia NVreg_EnableGpuFirmware=0' | sudo tee /etc/modprobe.d/nvidia-gsp.conf
sudo update-initramfs -u
```

**Fast mode KG population completed** while waiting for GPU fix:
- 30 documents processed
- 4,526 nodes written
- 6,291 edges written

**Three robustness fixes implemented:**
1. `keep_alive=-1` in Ollama calls — prevents model eviction from VRAM after 5 min idle
2. Exponential backoff retry logic (5 attempts: 5→10→20→40→80s waits)
3. Checkpoint system in `kg_population/pipeline.py` — writes completed `section_id` to `.checkpoint.json` after each document; restarts skip already-done docs

---

### Session 4 — 2026-02-19 Evening Part 1 (e42d17d2)
**Topic: GPU re-stabilised, design decision on multi-year graph structure**

GPU confirmed back after GSP fix. User connected to Neo4j browser. Graph with ~4,526 nodes visible.

**Key architectural decision — multi-year graph structure:**

| Option | Description | Decision |
|--------|-------------|----------|
| A | One database, `FiscalYear` anchor nodes | **Adopted** |
| B | Separate Docker containers per year | Rejected — cross-year queries impossible |
| C | Enterprise Edition upgrade | Rejected — cost |

User requested historical data going back to 1993 and emphasis on the FiscalYear scaffold for eventual cross-year linking.

---

### Session 5 — 2026-02-19 Evening Part 2 (c651b039)
**Topic: CLAUDE.md creation and major architecture refactor for multi-year support**

`/init` command run — `CLAUDE.md` generated to document the full project.

**Major multi-year refactor implemented:**

*New R files:*
- `get_historical_master.R` — downloads quarterly EDGAR master indexes for 1993–present via `getMasterIndex()`
- `run_all_years.sh` — outer loop running `run_parallel_collection.sh` year by year

*Modified R files:*
- `get_all_companies.R` — now takes `--year YYYY`; reads year-specific Rda master index files; outputs to `edgar_RiskFactors/<year>/` etc.
- `run_parallel_collection.sh` — now takes year as first argument
- `helper_functions.R` — `getRiskFactors()` writes to year subdir; cleans up raw filings after extraction

*Modified Python files:*
- `ontology/nodes.py` — added `FiscalYear` node (`fy_{year}`)
- `ontology/relations.py` — added `FILED_IN` and `PRECEDES` relation types
- `ontology/neo4j_schema.py` — added `FiscalYear` uniqueness constraint and `year` index
- `kg_population/writer.py` — added `ensure_fiscal_year_chain()` and `link_filing_to_fiscal_year()`
- `kg_population/pipeline.py` — auto-creates FiscalYear node and FILED_IN edge per document
- `preprocessing/pipeline.py` — walks year subdirectories when globbing `.txt` files
- `config.py` — added `EDGAR_MASTER_INDEX_DIR`

**Disk space crisis discovered:** `edgar_Filings/` was 5.8 GB for just 235 companies. Extrapolated to full corpus = ~4 TB. Fix: delete raw filing files immediately after section extraction. `helper_functions.R` updated accordingly.

**`run_smart_collection.sh` created:** 4 years in parallel × 6 workers each = 24 cores. Runs newest years first (2024→1993).

Historical master indexes downloaded: all 32 years (1993–2024), 235 companies already collected for 2024.

All overnight jobs launched:
- R collection 1993–2024 on 24 cores
- Preprocessing loop (every 10 min)
- KG population loop (every 15 min)
- `monitor_graph.sh` — logs milestone alerts at 1K, 5K, 10K… nodes

---

### Session 6 — 2026-02-20 Morning (ba997b42)
**Topic: Scaling collection to all tickers and automating the daily pipeline**

Summary at session start:
- ~3,167 `.txt` files collected (2019–2024, partial)
- ~516 preprocessed JSON files
- 65KB glossary built
- 134 documents checkpointed in KG (mostly dry-run)

**Key decision:** Include all ~7,880 unique CIKs in `ticker_to_cik.csv`, not just the default ~5,128.

**Actions taken:**
- Fixed `run_parallel_collection.sh` hardcoded `TOTAL=5128` → `7880`
- Started `run_all_years.sh 2015 2024 4` in background
- Started preprocessing on already-collected files
- Discovered `.venv/` was broken — all packages are in user Python at `~/.local/lib/python3.13/`; use `python3` directly

**Daily automation set up:**
- `get_daily_master_index.R` — downloads only daily CSV index (last 90 days, resumable)
- `run_daily_update.sh` — full daily pipeline: new EDGAR index → collect new 10-K filings → preprocess new files
- **Cron jobs installed:**
  - `0 6 * * *` — `run_daily_update.sh` (keeps filings current daily at 6am)
  - `0 * * * *` — `run_preprocessing.py` (processes new downloads every hour)

Neo4j restarted, glossary rebuilt from 3,748 preprocessed docs. KG population started in `--fast` spaCy mode (~6 hr estimate for 3,616 documents).

**Target file count:** ~39,077 total 10-K filings across 2015–2024 → ~117,000 `.txt` section files.

---

### Session 7 — 2026-02-20 Afternoon (7bb0fb3a)
**Topic: Status check and summary document created**

| Year | Risk Factors | Business | MD&A | Notes |
|------|-------------|----------|------|-------|
| 2015 | 1,555 | 1,675 | 1,643 | Complete |
| 2016 | 1,131 | 1,194 | 1,174 | Complete |
| 2017 | 496 | 533 | 529 | In progress (~295/1325) |
| 2018 | — | — | — | **Missing — investigate** |
| 2019 | 0 | 0 | 0 | Not started |
| 2020 | 0 | 0 | 0 | Not started |
| 2021 | 154 | 162 | 169 | Partial |
| 2022 | 250 | 254 | 262 | Partial |
| 2023 | 190 | 193 | 211 | Partial |
| 2024 | 427 | 431 | 444 | Partial |

Preprocessing: 4,024 risk_factors / 1,644 business / 1,514 MDA preprocessed.
Glossary: running (`--rules-only --index-chroma`, 2h+ elapsed).
KG population: 769/3,616 (21%) on business section; transient Neo4j timeout at doc 718, recovered.

Overnight between Sessions 7 and 8, background jobs continued running unattended.

---

### Session 8 — 2026-02-21 (current)
**Topic: Resume preprocessing + KG population; bugfixes; status review**

**State at session start (overnight progress):**

| Year | Risk Factors | Business | MD&A | Notes |
|------|-------------|----------|------|-------|
| 2015 | 1,555 | 1,675 | 1,643 | Complete |
| 2016 | 1,131 | 1,194 | 1,174 | Complete |
| 2017 | 561 | 600 | 597 | More collected |
| 2018 | **365** | **410** | **410** | **Fixed — was missing** |
| 2019 | **952** | **1,030** | **1,035** | **Filled — was 0** |
| 2020 | 489 | 522 | 521 | Partially filled (was 0) |
| 2021 | 154 | 162 | 169 | Partial (unchanged) |
| 2022 | 250 | 254 | 262 | Partial (unchanged) |
| 2023 | 190 | 193 | 211 | Partial (unchanged) |
| 2024 | 427 | 431 | 444 | Partial (unchanged) |

Preprocessing at session start: 6,074 risk_factors / 6,463 business / 6,209 MDA.
KG checkpoint at session start: 2,463 docs.
Disk: 34% used, 1.2 TB free.

**Bug fixed: spaCy `max_length` error in `preprocessing/segmenter.py`**

Some large 10-K sections have very long paragraphs (1.37M+ characters) that exceeded spaCy's default 1M-character limit. Fixed by setting `nlp.max_length = 3_000_000` after model load. Safe for sentence segmentation — the limit is a parser/NER memory guard, not needed for sentencizer output.

**Jobs started this session:**
- Neo4j (`neo4j-sec`) restarted
- `python3 python/run_preprocessing.py` — running, catching up on new MDA + risk_factors files
- `python3 python/run_kg_population.py --fast` — resumed from 2,463 docs; **16,530 total** documents in queue

---

## 2. Ideas and Features Discussed But NOT Yet Implemented

### Cross-Year Semantic Linking
The scaffold is in place (FiscalYear nodes + PRECEDES edges) but deferred:
- `PERSISTED_TO` edges between RiskFactor nodes across years (e.g., supply chain risk in 2021 and 2022)
- `EMERGED_IN` — risk first appearing in a given year
- `RESOLVED_IN` — risk disappearing from subsequent filings
- Example query: *"show how Apple's supply chain risk evolved 2020→2024"*

### LLM-Mode KG Population at Scale
The LLM extractor has never successfully completed a full production run due to GPU instability. All current graph data is from spaCy NER `--fast` mode. A re-run with the LLM is needed to get high-quality nodes without NER false positives.

### Cross-Section Graph Linking
No edges exist connecting entities across sections within the same filing (e.g., a risk factor in Item 1A referenced in a mitigation in Item 7). This cross-section layer was designed but not implemented.

### Taxonomy Layer
The original design called for a hierarchical taxonomy between Glossary and Ontology — organising concepts into parent-child trees (e.g., "Market Risk" → "Interest Rate Risk" → "Fixed Rate Exposure"). Designed conceptually, never coded.

### Item 7A and Item 8 Extraction
- **Item 7A** — Quantitative/Qualitative Disclosures About Market Risk (sensitivity tables, interest rate/FX/commodity exposure)
- **Item 8** — Full audited financial statements (income statement, balance sheet, cash flow)

Explicitly skipped in Session 1. Would require additional R extractors and more complex table parsing.

### LLM-Assisted Glossary Building
The glossary currently runs `--rules-only`. The LLM-based path exists in `glossary/extractor.py` but has not been run at scale due to GPU instability.

### Graph Quality Audit / NER Noise Cleanup
spaCy `--fast` mode produces noise in Competitor and other ORG-type nodes. No automated deduplication or quality-review pass has been done. Plan was to re-run with LLM extractor to replace these.

### Semantic Search Interface
ChromaDB is populated with sentence-level vectors but no user-facing query interface (web UI, API endpoint, or CLI) has been built.

### Historical Data 1993–2014
Master indexes for all years 1993–2024 are downloaded. Active collection has only targeted 2015–2024. The 1993–2014 years represent ~20 additional years of filings (~60K+ additional section files).

### Automated Graph Monitoring / Alerting
`monitor_graph.sh` was created and logs milestones, but no alerting (email, notification, dashboard) was built. The monitor just writes to `logs/graph_monitor.log`.

### Graph Analytics Layer
No analytics have been run on the completed graph. Ideas discussed:
- **Sector-level risk aggregation** — cluster risk factors by company sector (SIC code) to find which risks are sector-wide vs company-specific
- **Risk co-occurrence network** — edges between RiskDriver nodes that frequently appear together across filings
- **Temporal trend analysis** — track rising/falling frequency of specific risk types year-over-year (e.g., "AI risk" emerging post-2022)
- **Competitor network** — derive a market competition graph from Competitor nodes extracted across all filings

### Query / RAG Layer
The graph and ChromaDB vectors are built but there is no natural language interface over them. Ideas:
- **Cypher query generator** — take a natural language question, generate a Cypher query, run it, summarise the result (RAG-over-graph)
- **Hybrid retrieval** — combine ChromaDB vector search (for relevant sentences) with graph traversal (for structured relationships) to answer questions like *"What risks did semiconductor companies mention most in 2022?"*
- **Analyst dashboard** — simple web UI (FastAPI + Jinja2 or Streamlit) that exposes search + graph queries without needing to write Cypher

### `app/` Directory — In Progress
A separate application layer is in development (not yet committed). Will be documented once complete.

---

## 3. Pipeline Tasks Outstanding

### Actively Running (as of 2026-02-21)

| Task | Status | Log |
|------|--------|-----|
| Preprocessing | Running — catching up on 2018/2019/2020 new files | `logs/preprocessing_20260221.log` |
| KG population (`--fast`) | Running — 2,463/16,530 resumed | `logs/kg_population_20260221.log` |

### Immediate Tasks

- [ ] **Monitor preprocessing completion** — should finish all three sections; check for further spaCy errors on unusually large files
- [ ] **Monitor KG population** — 16,530 docs at ~2–3 docs/sec = ~2 hrs; watch for Neo4j timeout at scale
- [ ] **Investigate 2020–2024 gaps** — 2021–2024 still partial (154–489 RF files vs ~1000+ expected); determine if collection finished or stalled
- [ ] **Run glossary rebuild** — current glossary is stale (built from ~3,748 docs); rebuild after preprocessing completes: `python3 python/run_glossary.py --rules-only --index-chroma`
- [ ] **Verify cron jobs are firing** — check `logs/cron_daily.log` and `logs/cron_preprocessing.log` to confirm 6am daily and hourly crons ran

### Medium-Term Tasks

- [ ] **LLM-mode KG re-population** — once GPU is stable, re-run without `--fast` to replace spaCy NER nodes with higher-quality LLM-extracted entities
- [ ] **Extend collection to 1993–2014** — master indexes are ready; run `bash run_all_years.sh 1993 2014 4`
- [ ] **Implement cross-year semantic linking** — add `PERSISTED_TO`, `EMERGED_IN`, `RESOLVED_IN` edges after multi-year graph is populated
- [ ] **Cross-section linking** — connect entities that appear in multiple sections of the same filing
- [ ] **Implement taxonomy layer** — build hierarchical concept tree between Glossary and Ontology
- [ ] **Item 7A / Item 8 extraction** — add R extractors for market risk tables and financial statements when ready
- [ ] **LLM glossary extraction at scale** — run `python3 python/run_glossary.py --index-chroma` (without `--rules-only`) once GPU is stable

### Infrastructure / Quality Tasks

- [ ] **Graph quality audit** — write Cypher queries to identify and flag NER noise (false-positive Competitor/ORG nodes)
- [ ] **Build semantic search / query interface** — ChromaDB is populated but has no user-facing query UI or API; consider FastAPI endpoint or Streamlit dashboard
- [ ] **Fix `.venv/` Python environment** — venv has no packages; either fix it or remove it; update `CLAUDE.md` to document `python3` as the correct binary
- [ ] **Disk space monitoring** — disk at 34% (1.2 TB free) as of 2026-02-21; needs ongoing monitoring as 1993–2014 collection begins
- [ ] **Neo4j stability under extended load** — timeout occurred at doc 718 in Session 7; consider increasing Neo4j heap/page-cache memory if it recurs at scale
- [ ] **`app/` development** — complete and commit the in-progress application layer

---

## Appendix: Key Technical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Data collection language | R (edgar package) | Best-in-class EDGAR access; handles HTML/XBRL parsing internally |
| NLP/KG language | Python | Natural fit for spaCy, neo4j-python, chromadb, pydantic |
| Graph database | Neo4j Community Edition (Docker) | Full graph query capability; single-database limitation worked around with FiscalYear nodes |
| Vector store | ChromaDB | Local, no API cost, integrates with sentence-level preprocessing output |
| LLM | Ollama (`gpt-oss:latest`) local, switchable to Anthropic/OpenAI | Local-first for cost/privacy; unified `LLMClient` abstraction allows API switch via env var |
| Multi-year graph | Single Neo4j DB with `FiscalYear` anchor nodes + `PRECEDES` chains | Community Edition limitation; scaffold enables temporal queries |
| Filing cleanup | Delete raw `edgar_Filings/` after section extraction | 5.8 GB for 235 companies → ~4 TB projected for full corpus |
| Parallelism | 4–6 workers per year | EDGAR rate limit ~10 req/sec; beyond 8 workers risks throttling |
| spaCy max_length | Set to 3,000,000 after model load | Some 10-K sections have paragraphs >1M chars; safe for sentencizer |
