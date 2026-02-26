# SEC Knowledge Graph — Task Tracker

Last updated: **2026-02-25 22:30** (end of session)

### Status key
| Symbol | Meaning |
|--------|---------|
| ✅ | Complete |
| 🔄 | In Progress |
| ⏸ | Paused |
| 📋 | Open (not started) |
| ⚠️ | Blocked |

---

## Infrastructure & Environment

| # | Task | Status | Started | Completed | Notes |
|---|------|--------|---------|-----------|-------|
| I-1 | Neo4j Docker container (`neo4j-sec`) | ✅ | 2026-02-19 | 2026-02-19 | Exposed on `0.0.0.0:7474/7687`; accessible from Windows browser at `http://192.168.1.39:7474` (bolt: `bolt://192.168.1.39:7687`, user: neo4j, pass: password) |
| I-2 | ChromaDB local vector store | ✅ | 2026-02-19 | 2026-02-19 | Sentence-level embeddings; populated alongside preprocessing |
| I-3 | Python package structure (`python/`) | ✅ | 2026-02-19 | 2026-02-19 | `config.py`, `models/`, `preprocessing/`, `glossary/`, `ontology/`, `kg_population/` |
| I-4 | `.env` config file | ✅ | 2026-02-19 | 2026-02-19 | `LLM_PROVIDER`, Neo4j creds, paths — copy from `.env.example` |
| I-5 | RTX 5090 GSP firmware crash fix | ✅ | 2026-02-19 | 2026-02-19 | `NVreg_EnableGpuFirmware=0` in `/etc/modprobe.d/nvidia-gsp.conf` |
| I-6 | Cron jobs (daily collect + hourly preprocess) | ✅ | 2026-02-20 | 2026-02-20 | `0 6 * * *` → `run_daily_update.sh`; `0 * * * *` → `run_preprocessing.py` |
| I-7 | Python venv broken — all deps in user Python | ⚠️ | 2026-02-20 | — | `.venv/` exists but empty; use `python3` directly (`~/.local/lib/python3.13/`) |
| I-8 | CLAUDE.md project instructions | ✅ | 2026-02-20 | 2026-02-20 | Documents all commands, architecture, data flow |
| I-9 | Fix company count in collection scripts (5128 → 10021) | ✅ | 2026-02-21 | 2026-02-21 | Fixed in `run_smart_collection.sh` and `run_parallel_collection.sh` |
| I-10 | Graph visualisation (networkx/matplotlib) | ✅ | 2026-02-24 | 2026-02-24 | Sample subgraph render: FiscalYear chain, filings, companies, competitors, geo markets. Generated ad-hoc via Python; saved to `/tmp/sec_kg_viz.png` |

---

## R Data Collection

| # | Task | Status | Started | Completed | Notes |
|---|------|--------|---------|-----------|-------|
| R-1 | `get_daily_master.R` — daily EDGAR index download | ✅ | 2026-02-18 | 2026-02-18 | First 10 tickers; Linux path fixes applied |
| R-2 | `helper_functions.R` — Item 1 / 1A / 7 extractors | ✅ | 2026-02-18 | 2026-02-18 | `getRiskFactors()`, `getBusinDescr()`, `getMgmtDisc()`; raw filings deleted after extraction |
| R-3 | `get_all_companies.R` — parameterised bulk collector | ✅ | 2026-02-19 | 2026-02-19 | `--year`, `--offset`, `--limit` flags; skips already-collected CIKs |
| R-4 | `run_parallel_collection.sh` — multi-worker year runner | ✅ | 2026-02-19 | 2026-02-19 | Splits ~10,021 companies across N workers per year |
| R-5 | `get_historical_master.R` — all quarterly indexes 1993–present | ✅ | 2026-02-20 | 2026-02-20 | 32 years of `.Rda` master index files downloaded |
| R-6 | `run_all_years.sh` — sequential year loop | ✅ | 2026-02-20 | 2026-02-20 | Calls `run_parallel_collection.sh` year by year |
| R-7 | `run_smart_collection.sh` — concurrent year batches | ✅ | 2026-02-20 | 2026-02-20 | 4 years in parallel × 6 workers = 24 R processes |
| R-8 | `get_daily_master_index.R` + `run_daily_update.sh` | ✅ | 2026-02-20 | 2026-02-20 | Daily automation for new filings |
| R-9 | Collection 2015–2024 (all ~10,021 companies) | 🔄 | 2026-02-20 | — | 2023 + 2024 still running; 2015–2022 appear complete |
| R-10 | Collection 1993–2014 (historical) | 📋 | — | — | Master indexes ready; run after RAM frees up: `bash run_smart_collection.sh 1993 2014 4 6` |

### Collection progress by year (as of 2026-02-24 ~22:45)

| Year | Risk Factors | Business | MD&A | Status |
|------|-------------|----------|------|--------|
| 2024 | 2,677 | 2,702 | 2,848 | 🔄 In progress — needs restart tomorrow |
| 2023 | 2,087 | 2,098 | 2,221 | 🔄 In progress — needs restart tomorrow |
| 2022 | 773 | 809 | 824 | ✅ Done |
| 2021 | 632 | 677 | 682 | ✅ Done |
| 2020 | 489 | 522 | 521 | ✅ Done |
| 2019 | 952 | 1,030 | 1,035 | ✅ Done |
| 2018 | 365 | 410 | 410 | ✅ Done |
| 2017 | 561 | 600 | 597 | ✅ Done |
| 2016 | 1,131 | 1,194 | 1,174 | ✅ Done |
| 2015 | 1,555 | 1,675 | 1,643 | ✅ Done |
| 1993–2014 | 0 | 0 | 0 | 📋 Not started |

---

## Python Pipeline

### Preprocessing

| # | Task | Status | Started | Completed | Notes |
|---|------|--------|---------|-----------|-------|
| P-1 | `preprocessing/cleaner.py` — HTML/XBRL strip, whitespace | ✅ | 2026-02-19 | 2026-02-19 | |
| P-2 | `preprocessing/segmenter.py` — spaCy sentence segmentation | ✅ | 2026-02-19 | 2026-02-19 | `max_length=3_000_000` set to handle large filings |
| P-3 | `preprocessing/tagger.py` — forward-looking + coreference tags | ✅ | 2026-02-19 | 2026-02-19 | |
| P-4 | `preprocessing/pipeline.py` — R `.txt` → `SectionDocument` JSON | ✅ | 2026-02-19 | 2026-02-19 | Walks year subdirs; parses CIK/ticker/date header |
| P-5 | Fix spaCy `max_length` crash on large filings | ✅ | 2026-02-21 | 2026-02-21 | Some paragraphs exceed 1M chars; raised limit to 3M |
| P-6 | Preprocess all currently collected files | 🔄 | 2026-02-20 | — | ~17,858 RF / 18,745 business / 18,997 MDA preprocessed (55,600 total as of 2026-02-24); cron keeping pace |
| P-7 | Continuous preprocessing of new files (cron) | 🔄 | 2026-02-20 | — | Hourly cron; runs automatically as collection adds files |

### Glossary

| # | Task | Status | Started | Completed | Notes |
|---|------|--------|---------|-----------|-------|
| G-1 | `glossary/extractor.py` — rule-based + LLM term extraction | ✅ | 2026-02-19 | 2026-02-19 | |
| G-2 | `glossary/vector_store.py` — ChromaDB integration | ✅ | 2026-02-19 | 2026-02-19 | |
| G-3 | Initial glossary build (58 terms, 8 companies) | ✅ | 2026-02-19 | 2026-02-19 | |
| G-4 | Glossary rebuild from ~3,748 docs (rules-only) | ✅ | 2026-02-20 | 2026-02-21 | 65 KB glossary; stale — full corpus rebuild needed |
| G-5 | **Glossary rebuild from full corpus** | 📋 | — | — | Run after collection + preprocessing settles: `python3 python/run_glossary.py --rules-only --index-chroma` |
| G-6 | LLM-mode glossary extraction at scale | ⚠️ | — | — | Blocked on GPU stability; code exists in `extractor.py` |

### Ontology & KG Population

| # | Task | Status | Started | Completed | Notes |
|---|------|--------|---------|-----------|-------|
| O-1 | `ontology/nodes.py` — 18 typed node classes | ✅ | 2026-02-19 | 2026-02-19 | Company, Filing, Section, RiskFactor, RiskDriver, Competitor, Product, etc. |
| O-2 | `ontology/relations.py` — 25 relation types | ✅ | 2026-02-19 | 2026-02-19 | |
| O-3 | `ontology/neo4j_schema.py` — constraints + indexes | ✅ | 2026-02-19 | 2026-02-19 | 19 uniqueness constraints + 8 indexes applied |
| O-4 | `FiscalYear` anchor nodes + `PRECEDES` chain | ✅ | 2026-02-20 | 2026-02-20 | Multi-year graph scaffold; `FILED_IN` edges per filing |
| O-5 | `kg_population/extractor.py` — LLM entity/relation extractor | ✅ | 2026-02-19 | 2026-02-19 | Section-tailored prompts; unreliable due to GPU crashes |
| O-6 | `kg_population/ner_extractor.py` — spaCy fast extractor | ✅ | 2026-02-19 | 2026-02-19 | No GPU needed; some NER noise (ORG false positives) |
| O-7 | Checkpoint system (`.checkpoint.json`) | ✅ | 2026-02-19 | 2026-02-19 | Per-document; restarts skip already-done sections |
| O-8 | Ollama retry / `keep_alive=-1` fix | ✅ | 2026-02-19 | 2026-02-19 | Exponential backoff; prevents VRAM eviction |
| O-9 | **KG population (fast/spaCy) — full corpus** | 🔄 | 2026-02-24 | — | Restarted unthrottled after Neo4j wipe + recovery (2026-02-25). PID 16538; log: `logs/kg_population_throttled.log`; ~862/55,600 as of 22:00; ~1–2s/doc; est. 15–20h |
| O-10 | **LLM-mode KG re-population** | ⚠️ | — | — | Blocked on GPU; will replace spaCy NER noise with higher-quality entities |
| O-11 | **KG pipeline performance optimisation** | ✅ | 2026-02-24 | 2026-02-24 | 3-4x speedup: (1) `nlp.pipe(batch_size=64)` instead of per-sentence calls; (2) `write_document()` — single Neo4j session per doc; (3) edge `MERGE (a)-[r:TYPE]->(b)` without `filing_ref` in key — eliminates multigraph buildup; (4) checkpoint every 50 docs. Committed `2906cb5`. Graph wiped + restarted clean. |
| O-12 | **KG OOM crash fix — lazy document loading** | ✅ | 2026-02-24 | 2026-02-24 | Old code loaded all 55,600 JSON docs into RAM at startup (~40 GB → OOM kill after ~4h). Fixed: one doc loaded per iteration, previous doc GC'd. Fast section_id scan reads only first 100 bytes per file (8x faster). Committed `7ff22f5`. |
| O-13 | **KG throttle flag (`--delay`)** | ✅ | 2026-02-24 | 2026-02-24 | Added `--delay N` arg to `run_kg_population.py` — sleeps N seconds between docs; passes through to `pipeline.run_all()`. Current run uses `--delay 2`. |

| C-1 | **Chatbot — Phase 1 (working skeleton)** | ✅ | 2026-02-25 | 2026-02-25 | Streamlit app at `http://192.168.1.39:8501`; files in `python/chatbot/`; router + graph QA (text-to-Cypher) + semantic QA (ChromaDB) + synthesiser + memory. PID 22221; log: `logs/chatbot.log` |
| C-2 | **Chatbot — Phase 2 (conversation quality)** | 📋 | — | — | Co-ref resolution, company alias matching, Cypher error recovery, session persistence |
| C-3 | **Chatbot — Phase 3 (UI + graph viz)** | 📋 | — | — | pyvis graph panel, context chips, export to markdown |
| C-4 | **Chatbot — Phase 4 (cross-company + trend)** | 📋 | — | — | Needs LLM-mode RiskFactor nodes; trend queries, sector comparison |

---

## Graph Enrichment (Planned)

| # | Task | Status | Started | Completed | Notes |
|---|------|--------|---------|-----------|-------|
| E-1 | **Cross-year semantic linking** | 📋 | — | — | `PERSISTED_TO`, `EMERGED_IN`, `RESOLVED_IN` edges between RiskFactor nodes across years; uses sentence embeddings to match |
| E-2 | **Cross-section linking** | 📋 | — | — | Link entities appearing in multiple sections of the same filing (Item 1 ↔ 1A ↔ 7) |
| E-3 | **Taxonomy layer** | 📋 | — | — | Hierarchical concept tree between Glossary and Ontology (e.g. Market Risk → Interest Rate Risk → Fixed Rate Exposure) |
| E-4 | **Graph quality audit / NER noise cleanup** | 📋 | — | — | Cypher queries to flag false-positive Competitor/ORG nodes from spaCy; dedup pass |

---

## Analytics (Planned)

| # | Task | Status | Started | Completed | Notes |
|---|------|--------|---------|-----------|-------|
| A-1 | **Risk co-occurrence network** | 📋 | — | — | Edges between RiskDriver nodes that frequently appear together across filings |
| A-2 | **Sector risk profiles** | 📋 | — | — | Cluster risk types by SIC code; find sector-wide vs company-specific risks |
| A-3 | **Temporal trend analysis** | 📋 | — | — | Track rising/falling frequency of risk types year-over-year (e.g. "AI risk" post-2022) |
| A-4 | **Competitor network** | 📋 | — | — | Derive a market competition graph from all Competitor nodes across filings |

---

## Product / Query Layer (Planned)

| # | Task | Status | Started | Completed | Notes |
|---|------|--------|---------|-----------|-------|
| Q-1 | **RAG query interface** | 📋 | — | — | Natural language → Cypher + ChromaDB hybrid retrieval; FastAPI or Streamlit |
| Q-2 | **Semantic search CLI/API** | 📋 | — | — | ChromaDB populated but no user-facing query layer |
| Q-3 | **Analyst dashboard** | 📋 | — | — | Simple web UI over search + graph queries without writing Cypher |

---

## Suggested Build Order

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
END OF SESSION: 2026-02-25 ~22:30
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

WHAT IS RUNNING OVERNIGHT (do not kill these):
  PID 16538 — KG population (--fast, unthrottled)
              951/55,600 checkpointed at session end
              log: logs/kg_population_throttled.log
  PID 22221 — Streamlit chatbot (port 8501)
              log: logs/chatbot.log
  Docker    — neo4j-sec (up, clean DB, wiped + rebuilt tonight)

WHAT IS NOT RUNNING (needs manual start tomorrow):
  1. R collection 2023: bash run_parallel_collection.sh 2023 4 > logs/collection_2023.log 2>&1 &
  2. R collection 2024: bash run_parallel_collection.sh 2024 4 > logs/collection_2024.log 2>&1 &
  3. Glossary rebuild:  python3 python/run_glossary.py --rules-only --index-chroma > logs/glossary_rebuild.log 2>&1 &

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TOMORROW — STEP BY STEP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

STEP 1 — Check overnight processes (5 min)
  # Is KG population still alive?
  ps aux | grep kg_population | grep -v grep
  tail -5 logs/kg_population_throttled.log
  python3 -c "import json; d=json.load(open('python/data/kg_export/.checkpoint.json')); print(len(d), '/ ~55600')"

  # If dead, restart:
  nohup python3 python/run_kg_population.py --fast > logs/kg_population_throttled.log 2>&1 &

  # Is Neo4j up?
  docker ps --filter name=neo4j-sec --format "{{.Status}}"
  # If down: docker start neo4j-sec

  # Is chatbot up?
  ps aux | grep streamlit | grep -v grep
  # If down: nohup streamlit run python/chatbot/app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true > logs/chatbot.log 2>&1 &

STEP 2 — Start the things that weren't running (5 min)
  bash run_parallel_collection.sh 2023 4 > logs/collection_2023.log 2>&1 &
  bash run_parallel_collection.sh 2024 4 > logs/collection_2024.log 2>&1 &
  python3 python/run_glossary.py --rules-only --index-chroma > logs/glossary_rebuild.log 2>&1 &

STEP 3 — Test the chatbot (10 min)
  Open: http://192.168.1.39:8501
  Test these questions in order:
    a. "What companies are currently in the graph?"      ← graph QA, no LLM risk
    b. "Which companies mention China in their filings?" ← geo market query
    c. "Show me supply chain risk mentions"              ← falls back to ChromaDB
    d. "What are the most common competitors mentioned?" ← cross-company
  Check: do answers cite sources? Is the Cypher expandable? Does context carry between turns?

STEP 4 — Chatbot Phase 2 improvements (main dev work)
  Issues likely found in Step 3:
    a. Company name resolution — graph has UPPER CASE names, user types natural case.
       Fix in router.py: after LLM routing, do a fuzzy MATCH against Company nodes in Neo4j
       to resolve "Tyson" → "TYSON FOODS INC".
    b. Cypher error recovery — if Neo4j rejects the generated query, ask the LLM to fix it
       once before returning empty results. Add to graph_qa.py.
    c. "No results" messaging — when graph is sparse (only ~1-3% populated), the synthesiser
       should always explain what IS in the graph instead of just saying "no data found".
       Already partially handled by the _overview fallback in graph_qa.py — verify it works.
    d. Session persistence — save conversation to JSON file so it survives chatbot restarts.
       Add to memory.py: save_to_file() / load_from_file().

STEP 5 — Chatbot Phase 3: graph visualisation panel (optional, if time)
  Add pyvis subgraph rendering to app.py.
  After each answer, extract node IDs from graph_rows and render a pyvis HTML component
  showing the subgraph of entities referenced in the answer.
  See CHATBOT_DESIGN.md Phase 3 section for details.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BIGGER PICTURE — after KG population completes (~15-20h from session end)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Once O-9 finishes:
  - Run LLM-mode KG population for a target company set (e.g. S&P 500 subset):
      python3 python/run_kg_population.py --section risk_factors
    This adds RiskFactor, RiskDriver, RiskConsequence, Mitigation nodes —
    unlocking the most valuable chatbot query types.
  - Start 1993-2014 historical collection:
      bash run_smart_collection.sh 1993 2014 4 6
  - Graph quality audit (E-4): Cypher queries to identify spaCy false-positive Competitor nodes
  - Cross-year semantic linking (E-1): SUPERSEDES edges between same risk across years
```

## Log Locations

| Log | What it covers |
|-----|----------------|
| `logs/kg_population_throttled.log` | KG population (current run — unthrottled, PID 16538) |
| `logs/chatbot.log` | Streamlit chatbot (PID 22221, port 8501) |
| `logs/collection_<year>_worker_N.log` | R data collection per year/worker |
| `logs/preprocessing.log` | Hourly preprocessing cron |
| `logs/daily_update.log` | Daily EDGAR collection cron |
