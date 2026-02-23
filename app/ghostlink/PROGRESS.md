# Ghostlink — Progress Tracker

> Living document. Update at the end of every session.
> Covers: session log, feature backlog, architecture decisions, blockers, and ideas.

---

## How to Use This File

| Section | Purpose |
|---------|---------|
| [Session Log](#session-log) | What was done each session, with completion status |
| [Feature Backlog](#feature-backlog) | All planned features, prioritised |
| [Architecture Decisions](#architecture-decisions) | Why we built things the way we did |
| [Blockers & Open Questions](#blockers--open-questions) | What is stopping progress right now |
| [Future Ideas](#future-ideas) | Unfiltered ideas — not yet scoped or prioritised |
| [Data Notes](#data-notes) | What data is available and in what state |
| [Key Metrics](#key-metrics) | Stats to track as the app grows |

---

## Session Log

| # | Date | Description | Done |
|---|------|-------------|------|
| 1 | 2026-02-21 | Project setup — explored SEC pipeline, wrote `SEC_PROJECT_REFERENCE.md`, created `PROGRESS.md` | [x] |

---

## Feature Backlog

Features are grouped by theme and ordered by priority within each group.
Priority: **P0** = must have, **P1** = should have, **P2** = nice to have, **P3** = future.

### Core Infrastructure
- [ ] **P0** Scaffold Ghostlink app (framework choice: Next.js / FastAPI / other)
- [ ] **P0** Connect to Neo4j (bolt://localhost:7687)
- [ ] **P0** Connect to preprocessed JSON data (`python/data/preprocessed/`)
- [ ] **P0** Environment config (`.env` with Neo4j + LLM keys)
- [ ] **P1** Health check endpoint — verify Neo4j + data are reachable
- [ ] **P1** Company search/lookup by ticker or name

### Risk Intelligence
- [ ] **P1** Risk factor timeline — view a company's risk factors across years
- [ ] **P1** Risk factor diff — side-by-side sentence comparison between two years
- [ ] **P1** Risk severity scoring — flag HIGH/MED/LOW risk sentences
- [ ] **P1** Forward-looking sentence filter — show only flagged future-tense text
- [ ] **P2** Risk driver frequency — what causes risk most often across a sector
- [ ] **P2** Risk consequence map — what outcomes are most commonly cited
- [ ] **P2** Mitigation extraction — what actions does the company say it is taking
- [ ] **P2** Risk emergence detection — first year a risk driver appears for a company
- [ ] **P3** Cross-year semantic linking — track risk as it evolves (requires `PERSISTED_TO` edges)

### Competitive Intelligence
- [ ] **P1** Competitor graph — who does company X compete with (`COMPETES_WITH`)
- [ ] **P2** Shared risk exposure — companies sharing the same risk drivers
- [ ] **P2** Sector risk landscape — aggregate risk profile for an industry
- [ ] **P2** Market position map — products, segments, geographies per company
- [ ] **P3** Sector consolidation signals — tracking competitor mentions over time

### Financial Intelligence (MD&A)
- [ ] **P2** Financial metrics timeline — revenue, margin, guidance trends
- [ ] **P2** Macro factor exposure — which companies cite inflation, FX, rates, etc.
- [ ] **P2** Management outlook sentiment — bullish vs cautious language
- [ ] **P3** Cross-section linking — connect a risk factor to a financial metric it impacted

### Search & Discovery
- [ ] **P1** Full-text search over preprocessed sentences
- [ ] **P2** Semantic search via ChromaDB (`python/data/chroma/`)
- [ ] **P2** Cypher query builder — natural language to graph query
- [ ] **P3** RAG interface — ask questions, get answers with source citations

### Alerts & Monitoring
- [ ] **P2** Company watchlist — save companies to monitor
- [ ] **P2** Risk change alerts — notify when a company's risk profile changes materially
- [ ] **P3** Sector pulse — weekly digest of risk changes across an industry
- [ ] **P3** New filing detection — alert when a new 10-K is processed

### Reporting
- [ ] **P2** Peer comparison view — how does company X's risk disclosure compare to peers
- [ ] **P3** Due diligence export — generate PDF/markdown report for a company
- [ ] **P3** Sector quarterly report — automated SectorPulse document

---

## Architecture Decisions

Record every significant technical choice here so we can refer back to it.

| Date | Decision | Rationale | Alternatives Considered |
|------|----------|-----------|------------------------|
| 2026-02-21 | Reading from preprocessed JSON files directly for initial features | Avoids Neo4j dependency; ~18,746 files already processed; same approach used in 10k-monitor | Querying Neo4j directly — graph is still sparse (~13% populated) |
| 2026-02-21 | Will use Neo4j for graph-based features (competitor networks, risk drivers) | Graph is the right structure for multi-hop queries | PostgreSQL — no native graph traversal |
| — | TBD: Frontend framework | — | Next.js, Svelte, plain HTML |
| — | TBD: Backend framework | — | FastAPI, Express, none |

---

## Blockers & Open Questions

Things that are actively preventing progress or need a decision before work can start.

- [ ] **Framework choice** — What stack are we building Ghostlink in? (Next.js + FastAPI? Svelte? Other?)
- [ ] **App purpose** — What is the primary persona / use case for Ghostlink? (Investor tool? Analyst dashboard? API-first?)
- [ ] **Neo4j population** — Graph is currently ~13% populated (spaCy NER, noisy). Are we relying on Neo4j or flat JSON for initial features?
- [ ] **LLM access** — Ollama/GPU is unstable (RTX 5090 GSP bug). For LLM features, should we default to Anthropic API?
- [ ] **Auth** — Does the app need user accounts / login for MVP?

---

## Future Ideas

Unfiltered. No commitment to build any of these — capture everything, triage later.

### Product Ideas
- **RiskRadar** — watchlist-based alert service: "AMD just added a new AI competition risk"
- **SectorPulse** — quarterly automated report on the top risks across a sector
- **DealRoom** — M&A due diligence mode: compare two companies side-by-side, highlight risk overlap
- **DisclosureScore** — benchmark a company's disclosure quality against its peers (coverage, specificity, forward-looking ratio)
- **RiskAtlas** — geographic heat map of where companies report operational risk exposure
- **TimelineView** — visual timeline showing when risk factors were introduced, modified, dropped
- **GhostQuery** — natural language question interface: "What risks did semiconductor companies add in 2022?"
- **PeerBenchmark** — "How does NVDA's supply chain risk disclosure compare to AMD and Intel?"
- **EarlyWarning** — flag risk factor language patterns that historically preceded bad outcomes
- **ESGLayer** — extract ESG-specific risks (climate, diversity, governance) and score them

### Technical Ideas
- Cache Neo4j query results in Redis or SQLite for fast repeated access
- Nightly job to re-index new preprocessed JSON into the app's cache
- Streaming responses for LLM-generated summaries
- Export to CSV / JSON for analysts who want raw data
- Embeddable widget: drop a risk summary card into any web page
- Graph visualisation using D3.js or vis.js for competitor networks
- Side-by-side diff view with colour-coded sentence additions/deletions/rewrites

### Data Enrichment Ideas
- Enrich `Company` nodes with sector/industry (SIC codes from EDGAR)
- Map `GeographicMarket` nodes to revenue contribution data
- Link `Regulation` nodes to actual regulatory bodies (SEC, CFTC, FDA, etc.)
- Add sentiment scores to `RiskFactor` sentences (positive/negative/neutral)
- Pull stock price history and correlate with risk factor changes
- Add earnings call transcript data as a fourth section alongside Item 1/1A/7

---

## Data Notes

Quick reference for what data is available and in what state. See `SEC_PROJECT_REFERENCE.md` for full detail.

| Data Source | Location | State | Notes |
|-------------|----------|-------|-------|
| Preprocessed risk factors | `python/data/preprocessed/risk_factors/` | ~6,074 JSON files, 2015–2024 | Ready to use |
| Preprocessed business desc | `python/data/preprocessed/business/` | ~6,463 JSON files, 2015–2024 | Ready to use |
| Preprocessed MD&A | `python/data/preprocessed/mda/` | ~6,209 JSON files, 2015–2024 | Ready to use |
| Neo4j graph | bolt://localhost:7687 | ~4,526 nodes, ~6,291 edges | Sparse (~13% of docs). NER-based, some noise |
| ChromaDB vector store | `python/data/chroma/` | Populated | Sentence-level embeddings for semantic search |
| Ticker → CIK map | `ticker_to_cik.csv` | ~5,128 entries | Use for company lookup |
| Raw .txt filings (R output) | `edgar_RiskFactors/<year>/` etc. | ~18,746 files | Source of truth; read-only |

**Data quality caveats:**
- Neo4j graph is noisy — spaCy NER misclassifies some financial phrases as ORG/GPE
- Not all companies have all years 2015–2024 — gaps exist especially 2017–2023
- CIK is the stable company identifier (tickers can change)
- Fiscal year = filing year − 1 for Q1 filings (month ≤ 3)

---

## Key Metrics

Track these as the app develops.

| Metric | Baseline (2026-02-21) | Current |
|--------|----------------------|---------|
| Preprocessed documents | 18,746 | — |
| Neo4j nodes | ~4,526 | — |
| Neo4j edges | ~6,291 | — |
| Companies with data | ~7,880 (CIKs) | — |
| Years covered | 2015–2024 | — |
| App endpoints built | 0 | — |
| Features shipped | 0 | — |
