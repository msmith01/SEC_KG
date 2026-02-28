# SEC Knowledge Graph — Project History

A full account of every phase of the project, the decisions made, the problems hit, and how they were solved.

---

## The Goal

Build a system that turns 30+ years of SEC 10-K filings into a structured, queryable knowledge graph in Neo4j — so financial analysts can ask questions like "how has Apple's supply chain risk changed over time?" or "which companies share the same macro risk drivers?" without reading thousands of documents manually.

---

## Phase 1 — Infrastructure Setup

The first thing we built was the environment.

- Neo4j was deployed as a Docker container (`neo4j-sec`), exposing ports 7474 (browser) and 7687 (bolt) on `0.0.0.0` so it could be accessed from a Windows machine on the LAN at `http://192.168.1.39:7474`
- Python dependencies were installed to the user's Python (`~/.local/lib/python3.13/`) because the virtualenv (`.venv/`) ended up broken — we noted this and moved on; `python3` directly still works fine
- `.env` config was created from `.env.example` with Neo4j credentials and the LLM provider setting (`LLM_PROVIDER=ollama`)
- **RTX 5090 GPU crash fix:** The GPU was crashing on any CUDA workload due to a GSP firmware bug. Fixed by writing `options nvidia NVreg_EnableGpuFirmware=0` to `/etc/modprobe.d/nvidia-gsp.conf` and rebuilding the initramfs
- `CLAUDE.md` was written to document the entire project structure, commands, and decisions for AI assistance across sessions

---

## Phase 2 — R Data Collection Layer

We decided to use R (not Python) for downloading EDGAR filings because the `edgar` CRAN package handles EDGAR's rate limits, authentication quirks, and section extraction out of the box. Reproducing this in Python would have taken much longer.

**What we built:**

- `helper_functions.R` — wraps the edgar package's `getFilings()`, `getRiskFactors()`, `getBusinDescr()`, `getMgmtDisc()` functions. Each 10-K has three sections extracted and saved as `.txt` files: Item 1 (Business Description), Item 1A (Risk Factors), Item 7 (MD&A / Management Discussion)
- `get_daily_master.R` — downloads the daily EDGAR index and fetches filings for the first 10 tickers as a quick test
- `get_all_companies.R` — bulk collector with `--year`, `--offset`, `--limit` args; resumable — skips any company where output files already exist in all three section directories
- `get_historical_master.R` — downloads all quarterly EDGAR master index `.Rda` files from 1993 to the present (32 years)
- `run_parallel_collection.sh` — splits ~10,021 companies across N parallel R workers for a given year
- `run_smart_collection.sh` — runs 4 years concurrently, each with N workers (24 R processes at once)
- `run_all_years.sh` — loops through all years sequentially, calling the parallel runner per year
- `run_daily_update.sh` + `get_daily_master_index.R` — daily cron automation to pick up new filings from EDGAR

**Output format:** Each `.txt` file has a structured header block followed by the raw section text:

```
CIK: 320193
Company Name: APPLE INC
Form Type: 10-K
Filing Date: 2023-11-03
Accession Number: 0000320193-23-000106

<section text starts here>
```

**Scale reached:**

| Year      | Status                                                     |
|-----------|------------------------------------------------------------|
| 2015–2022 | Complete                                                   |
| 2023–2024 | In progress (currently resuming)                           |
| 1993–2014 | Queued (master indexes downloaded, collection not started) |

Total: ~32,920 extracted `.txt` section files across 2015–2024.

---

## Phase 3 — Python Preprocessing Pipeline

With raw text files coming out of R, we built the Python preprocessing stage.

**Architecture decision:** Store an intermediate JSON format (`SectionDocument`) rather than going straight from raw text to Neo4j. This means cleaning and segmenting text is done once and cheaply re-used by every downstream stage (glossary, KG population, app layer).

**Modules built:**

- `python/config.py` — central config: all paths and env var reads. Nothing else hardcodes paths
- `python/models/schemas.py` — Pydantic data models:
  - `FilingMetadata` — provenance per filing (CIK, ticker, accession, date, fiscal year)
  - `TaggedSentence` — one sentence with `is_forward_looking` and `has_company_ref` flags
  - `SectionDocument` — one section from one filing = list of `TaggedSentence` + `FilingMetadata`
  - `GlossaryTerm` / `GlossaryStore` — domain glossary with merge/dedup logic
- `python/models/llm_client.py` — single `LLMClient` class wrapping Ollama, Anthropic, and OpenAI behind a unified `client.complete(prompt, system=...)` interface. Ollama has exponential backoff retry (5s → 10s → 20s → 40s → 80s) to handle VRAM eviction
- `python/preprocessing/cleaner.py` — strips HTML tags, XBRL markup, normalises whitespace
- `python/preprocessing/segmenter.py` — spaCy sentence segmentation with `max_length=3_000_000` (needed to handle very large 10-K filings; the default 1M limit was causing crashes)
- `python/preprocessing/tagger.py` — flags forward-looking sentences ("we expect", "may result in", "anticipate") and company coreferences
- `python/preprocessing/pipeline.py` — orchestrates: walks R output directories, parses header blocks, calls cleaner → segmenter → tagger, writes `SectionDocument` JSON

**Fiscal year derivation logic:** Filings from Jan/Feb/Mar of year Y are assigned to fiscal year Y-1 (companies report their prior-year results in Q1).

**Scale:** ~56,076 documents preprocessed (17,858 risk factors / 18,745 business descriptions / 18,997 MD&A). A cron job runs hourly to preprocess any new files as R collection adds them.

---

## Phase 4 — Ontology Design & Neo4j Schema

We designed the knowledge graph schema before writing any population code.

**Key design decision:** FiscalYear anchor nodes chained with `PRECEDES` edges. Instead of embedding the year in every node, each filing links to a `FiscalYear` node. This gives a temporal layer to the graph without requiring Neo4j Enterprise (which costs money). Temporal traversal queries work with the chain:

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

**18 node types across four categories:**
- Core: `Company`, `Filing`, `Section`, `FiscalYear`
- Business: `BusinessSegment`, `Product`, `GeographicMarket`, `CustomerSegment`, `Competitor`, `Regulation`
- Risk: `RiskFactor`, `RiskDriver`, `RiskConsequence`, `Mitigation`
- Financial: `FinancialMetric`, `FinancialPeriod`, `ManagementOutlook`, `MacroFactor`

**25 relation types** including `FILED_BY`, `HAS_SECTION`, `FILED_IN`, `PRECEDES`, `HAS_RISK`, `CAUSED_BY`, `MAY_RESULT_IN`, `MITIGATED_BY`, `COMPETES_WITH`, `OPERATES_IN`, and more.

Node IDs are deterministic (e.g. `{cik}` for Company, `{accession_number}` for Filing, `fy_{year}` for FiscalYear) so every write uses `MERGE` (upsert) rather than creating duplicates.

19 uniqueness constraints and 8 indexes applied to Neo4j via `python/ontology/neo4j_schema.py`.

---

## Phase 5 — Glossary Extraction

Built `python/glossary/extractor.py` (rule-based + LLM term extraction) and `python/glossary/vector_store.py` (ChromaDB integration). Produced an initial 65 KB glossary from ~3,748 docs using rules-only mode. A full corpus rebuild is currently running in the background.

---

## Phase 6 — KG Population (Two Modes)

This is the most complex part of the system. We built two extraction modes that coexist in the same graph:

### Fast mode (`--fast`, spaCy NER)

- Uses spaCy's `en_core_web_lg` model to extract named entities
- No GPU required; processes the full corpus in hours
- Extracts: `Company`, `Filing`, `FiscalYear`, `Section`, `Competitor`, `GeographicMarket`, `Product`
- Noisy — NER over-fires on non-geographic text (e.g. "Board of Directors" tagged as a Competitor)
- Checkpoint: `.checkpoint_fast.json`

### LLM mode (default)

- Uses a local Ollama model or Anthropic/OpenAI API
- Slower (~0.1 doc/sec vs ~1 doc/sec for spaCy) but much higher quality
- Extracts everything fast mode does, plus `RiskFactor`, `RiskDriver`, `RiskConsequence`, `Mitigation`, `BusinessSegment`, `MacroFactor`, `ManagementOutlook` nodes
- Currently blocked until GPU is stable (RTX 5090 issue)
- Checkpoint: `.checkpoint_llm.json`

Both modes use `MERGE` (upsert) — neither mode ever deletes the other's data.

---

## Phase 7 — Performance Crises and Fixes

The KG population pipeline hit three serious problems. All were diagnosed and fixed.

### Problem 1: Multigraph edge buildup

The original `MERGE` pattern for edges included `filing_ref` in the key, meaning each new run of a document created a new parallel edge between the same node pair. After thousands of documents, some node pairs had 12+ parallel edges. Each Neo4j write had to scan an ever-growing set of edges, making the pipeline progressively slower.

**Fix:** Removed `filing_ref` from the MERGE key so each node pair has at most one edge per relationship type. Wiped the graph and started clean. Committed `2906cb5`.

### Problem 2: OOM crash after ~4 hours

The old loader read all ~55,600 JSON documents into RAM at startup — approximately 40 GB. The system's OOM killer terminated the process after ~4 hours of runtime.

**Fix:** Changed to lazy loading — one document is loaded per iteration and garbage collected before the next. Added a fast section-ID scan that reads only the first 100 bytes of each file (8x faster than loading the full document to check if it's already checkpointed). Committed `7ff22f5`.

### Problem 3: Single-threaded CPU bottleneck

The original `run_kg_population.py` was single-threaded. With 56,076 documents at ~1 doc/sec, it would take 15+ hours and was susceptible to being interrupted.

**Fix:** Built `python/run_kg_parallel.py` — a multiprocess architecture with N extractor worker processes (spaCy NER, CPU-bound) feeding a single writer process (Neo4j). Why a single writer? Concurrent `MERGE` on shared nodes (`Company`, `Competitor`) causes Neo4j deadlocks. The single writer serializes all writes safely.

**Critical performance fix within the parallel runner:** The edge `MATCH` patterns were written without node labels, causing Neo4j to do full node scans to find both ends of each edge.
- Without labels: ~26 seconds per write (full scan)
- With labels (e.g. `MATCH (a:Company)-[r:COMPETES_WITH]->(b:Competitor)`): ~0.06 seconds per write

**Overall result:** ~55x speedup — from 0.18 docs/sec (single-threaded throttled) to ~10 docs/sec (parallel, 12 workers). The full 56,076 document corpus was completed in ~90 minutes.

Also added `FiscalYear` pre-creation (`setup_fiscal_years()`) before workers start, eliminating a second class of deadlocks on the `PRECEDES` chain.

---

## Phase 8 — 10k-Monitor App

Built `app/10k-monitor/` — a web app for viewing Risk Factor changes between consecutive 10-K filings:
- Backend: FastAPI + SQLite
- Frontend: Next.js 14
- Features: company search, filing timeline, side-by-side sentence diff with HIGH/MED/LOW severity scoring

---

## Phase 9 — 8-K Data Collection

While the 10-K pipeline ran, we added a parallel collection pipeline for 8-K filings (material event disclosures — CEO changes, acquisitions, earnings guidance cuts, etc.):

- `get_8k_documents.R` — downloads raw 8-K text to `edgar_8K/<year>/`; resumable with `--year`/`--offset`/`--limit` args
- `get_8k_items.R` — uses `get8KItems()` to extract structured event items (item codes like 1.01 Material Agreement, 5.02 Executive Change); outputs `edgar_8K_items/<year>/events_<year>.csv`; batched 50 CIKs per call
- `run_parallel_8k.sh` — two-pass parallel runner (Pass 1: raw download; Pass 2: structured events, gated on Pass 1 success)
- `run_all_years_8k.sh` — runs 2014–2024 in batches of 3 concurrent years × 4 workers

8-K KG integration (preprocessing, ontology, timeline queries) is planned but not yet built.

---

## Phase 10 — NER Competitor Noise Cleanup

After examining the graph, we found the spaCy fast-mode was producing large numbers of false-positive `Competitor` nodes — things like "Board of Directors", "Internal Audit Committee", "LLP", "Inc." were being tagged as competitor ORG entities.

Built a cleanup script that:
1. Queries all `Competitor` nodes
2. Runs them through a blocklist + heuristic filters (too short, contains "LLP"/"Inc" suffix only, looks like a department name, etc.)
3. Deletes the false positives and their relationships from Neo4j

---

## Phase 11 — Chatbot (Phase 1)

Built a complete chatbot at `python/chatbot/` running as a Streamlit app at `http://192.168.1.39:8501`.

**Architecture:**
```
Question → Router (LLM extracts intent + company + years)
         → Graph QA (Text-to-Cypher → Neo4j)
         + Semantic QA (ChromaDB similarity search)
         → Synthesiser (LLM merges both sources)
         → Answer with citations
```

**Files:**
- `app.py` — Streamlit UI, session management
- `router.py` — LLM-based intent classification and entity extraction
- `graph_qa.py` — Text-to-Cypher generation and Neo4j execution
- `semantic_qa.py` — ChromaDB semantic search
- `synthesiser.py` — LLM answer synthesis from both sources
- `memory.py` — conversation history
- `prompts.py` — all LLM prompt templates

**Known Phase 2 issues queued:**
1. Company name resolution — graph stores names in UPPER CASE; fuzzy matching needed in `router.py`
2. Cypher error recovery — retry with LLM fix on syntax errors in `graph_qa.py`
3. Session persistence — save/load conversation JSON in `memory.py`
4. "No results" fallback messaging

---

## Where Things Stand

### Completed

- Full R collection pipeline (2015–2022 done; 2023/2024 resuming)
- Full preprocessing pipeline (~56k documents)
- Neo4j ontology (18 node types, 25 relations, constraints + indexes)
- KG population — fast/spaCy mode: 100% complete (56,076/56,076 docs)
- 8-K collection pipeline (running 2014–2024)
- 10k-monitor web app
- Chatbot Phase 1

### Running right now

| Process              | Status              |
|----------------------|---------------------|
| Neo4j                | Up                  |
| Chatbot (port 8501)  | Up, PID 6558        |
| R collection 2023    | Running (4 workers) |
| R collection 2024    | Running (4 workers) |
| 8-K collection 2014–2024 | Running        |
| Glossary rebuild     | Running             |

### Next dev work

- Chatbot Phase 2 (company name resolution, Cypher error recovery, session persistence)
- LLM-mode KG population (adds RiskFactor/RiskDriver/etc. nodes — unlocks the highest-value queries)
- Historical R collection 1993–2014
- Cross-year semantic linking (`PERSISTED_TO` / `EMERGED_IN` edges between risk factors across years)

---

## Architecture Critique (from external review)

Three gaps identified that will likely matter at scale:

**1. Entity Resolution gap**
spaCy NER creates `Competitor` nodes like "Amazon.com Inc" and "Amazon" as separate nodes. Without canonicalization to a CIK or canonical entity ID, cross-year competitive landscape traversal breaks. Fix: a canonicalization layer that fuzzy-matches extracted ORGs to CIKs before writing to Neo4j.

**2. Loss of provenance on edges**
Removing `filing_ref` from edge keys (Phase 7 fix) solved the multigraph problem but removed the link from an edge back to the specific sentence that justified it. Fix: store `filing_ids` as an array property on the edge, or use an intermediate `Claim` node: `(Company)-[:MADE]->(Claim)-[:MENTIONS]->(RiskFactor)` with the `TaggedSentence` ID stored on the Claim.

**3. No LLM extraction validation loop**
LLM-mode extraction with a local model can silently under-extract (VRAM eviction, context limits) with no measurable signal. Fix: run a "gold standard" extraction with a heavier model (Claude Sonnet, GPT-4o) on a 1% random sample, then compute precision/recall against that baseline to know actual extraction quality.
