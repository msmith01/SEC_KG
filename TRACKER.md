# SEC Knowledge Graph — Task Tracker

Last updated: **2026-02-21 18:15**

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
| I-1 | Neo4j Docker container (`neo4j-sec`) | ✅ | 2026-02-19 | 2026-02-19 | Exposed on `0.0.0.0:7474/7687`; accessible from Windows at `192.168.1.38` |
| I-2 | ChromaDB local vector store | ✅ | 2026-02-19 | 2026-02-19 | Sentence-level embeddings; populated alongside preprocessing |
| I-3 | Python package structure (`python/`) | ✅ | 2026-02-19 | 2026-02-19 | `config.py`, `models/`, `preprocessing/`, `glossary/`, `ontology/`, `kg_population/` |
| I-4 | `.env` config file | ✅ | 2026-02-19 | 2026-02-19 | `LLM_PROVIDER`, Neo4j creds, paths — copy from `.env.example` |
| I-5 | RTX 5090 GSP firmware crash fix | ✅ | 2026-02-19 | 2026-02-19 | `NVreg_EnableGpuFirmware=0` in `/etc/modprobe.d/nvidia-gsp.conf` |
| I-6 | Cron jobs (daily collect + hourly preprocess) | ✅ | 2026-02-20 | 2026-02-20 | `0 6 * * *` → `run_daily_update.sh`; `0 * * * *` → `run_preprocessing.py` |
| I-7 | Python venv broken — all deps in user Python | ⚠️ | 2026-02-20 | — | `.venv/` exists but empty; use `python3` directly (`~/.local/lib/python3.13/`) |
| I-8 | CLAUDE.md project instructions | ✅ | 2026-02-20 | 2026-02-20 | Documents all commands, architecture, data flow |
| I-9 | Fix company count in collection scripts (5128 → 10021) | ✅ | 2026-02-21 | 2026-02-21 | Fixed in `run_smart_collection.sh` and `run_parallel_collection.sh` |

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

### Collection progress by year (as of 2026-02-21 ~18:00)

| Year | Risk Factors | Business | MD&A | Status |
|------|-------------|----------|------|--------|
| 2024 | 2,403 | 2,433 | 2,567 | 🔄 In progress |
| 2023 | 1,812 | 1,814 | 1,934 | 🔄 In progress |
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
| P-6 | Preprocess all currently collected files | 🔄 | 2026-02-20 | — | ~10,603 RF / 11,012 business / 11,305 MDA preprocessed; cron keeping pace with collection |
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
| O-3 | `ontology/neo4j_schema.py` — constraints + indexes | ✅ | 2026-02-19 | 2026-02-19 | 18 uniqueness constraints + 7 indexes applied |
| O-4 | `FiscalYear` anchor nodes + `PRECEDES` chain | ✅ | 2026-02-20 | 2026-02-20 | Multi-year graph scaffold; `FILED_IN` edges per filing |
| O-5 | `kg_population/extractor.py` — LLM entity/relation extractor | ✅ | 2026-02-19 | 2026-02-19 | Section-tailored prompts; unreliable due to GPU crashes |
| O-6 | `kg_population/ner_extractor.py` — spaCy fast extractor | ✅ | 2026-02-19 | 2026-02-19 | No GPU needed; some NER noise (ORG false positives) |
| O-7 | Checkpoint system (`.checkpoint.json`) | ✅ | 2026-02-19 | 2026-02-19 | Per-document; restarts skip already-done sections |
| O-8 | Ollama retry / `keep_alive=-1` fix | ✅ | 2026-02-19 | 2026-02-19 | Exponential backoff; prevents VRAM eviction |
| O-9 | **KG population (fast/spaCy) — full corpus** | ⏸ | 2026-02-21 | — | 560 docs checkpointed after rebuild; not currently running — resume after preprocessing settles |
| O-10 | **LLM-mode KG re-population** | ⚠️ | — | — | Blocked on GPU; will replace spaCy NER noise with higher-quality entities |

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
[Now — running]
  R-9  → collect 2023 + 2024 (2 workers, active)
  P-7  → preprocess new files (cron, hourly)

[Next — when preprocessing settles + RAM frees]
  O-9  → resume KG population --fast (spaCy, no GPU)
  G-5  → rebuild glossary from full corpus (rules-only, lightweight)

[After 2023/2024 collection completes]
  R-10 → start 1993-2014 historical collection

[After full corpus in graph]
  E-4  → graph quality audit / NER noise cleanup
  E-1  → cross-year semantic linking  ← biggest graph value-add
  E-2  → cross-section linking

[After enrichment]
  A-1  → risk co-occurrence
  A-3  → temporal trends

[Product layer]
  Q-1  → RAG query interface
  Q-3  → analyst dashboard
```
