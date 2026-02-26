# SEC KG Chatbot — Design & Build Guide

A conversational interface over the SEC knowledge graph. Ask company-specific
questions, trace how risks evolved year-over-year, and compare across companies.
Runs as a Streamlit web app accessible from any browser on the LAN.

---

## What It Can Answer

| Question type | Example |
|---|---|
| **Company-specific** | "What are Tyson Foods' biggest supply chain risks?" |
| **Temporal** | "How did Microsoft's cybersecurity risk disclosures change from 2020 to 2024?" |
| **Cross-company** | "Which S&P 500 companies disclose the most tariff exposure?" |
| **Comparative** | "Compare Apple and Samsung's geographic market concentration" |
| **Trend** | "Which risk types have grown most since 2020?" |

---

## Architecture

```
User (browser on Windows)
        │  http://192.168.1.39:8501
        ▼
┌───────────────────────────────────────────────────────┐
│  Streamlit UI  (python/chatbot/app.py)                │
│  - chat window   - entity chips   - graph panel       │
└───────────────────────┬───────────────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────────────┐
│  Query Router  (python/chatbot/router.py)             │
│  LLM classifies intent + extracts: company, years,    │
│  topic, query_type (company | temporal | cross)       │
└───────┬──────────────────────────────┬────────────────┘
        │                              │
        ▼                              ▼
┌───────────────────┐      ┌───────────────────────────┐
│  Graph QA         │      │  Semantic QA              │
│  (graph_qa.py)    │      │  (semantic_qa.py)         │
│                   │      │                           │
│  LLM → Cypher     │      │  Embed question           │
│  → Neo4j          │      │  → ChromaDB search        │
│  → structured     │      │  → top-K sentences        │
│    result         │      │    with metadata          │
└───────┬───────────┘      └──────────────┬────────────┘
        │                                 │
        └──────────────┬──────────────────┘
                       ▼
        ┌──────────────────────────────┐
        │  Answer Synthesiser          │
        │  (synthesiser.py)            │
        │                              │
        │  Merges graph facts +        │
        │  semantic passages into a    │
        │  grounded natural-language   │
        │  answer with citations       │
        └──────────────┬───────────────┘
                       │
                       ▼
        ┌──────────────────────────────┐
        │  Conversation Memory         │
        │  (memory.py)                 │
        │                              │
        │  Sliding window of last N    │
        │  turns. Tracks active        │
        │  company / year range so     │
        │  follow-ups resolve correctly│
        └──────────────────────────────┘
```

---

## File Layout

```
python/chatbot/
├── __init__.py
├── app.py             # Streamlit entry point
├── router.py          # Intent classification + entity extraction
├── graph_qa.py        # Text-to-Cypher pipeline
├── semantic_qa.py     # ChromaDB retrieval
├── synthesiser.py     # Final answer generation
├── memory.py          # Conversation state
├── prompts.py         # All system/user prompt templates
└── run_chatbot.sh     # One-command launcher
```

---

## Component Detail

### 1. Conversation Memory (`memory.py`)

Stores:
- **turn history** — last N (question, answer, cypher, sources) tuples
- **active context** — current company ticker/CIK, active year range, active topic
- Context is passed to every subsequent prompt so "how did that change in 2022?"
  resolves correctly without re-stating the company

```python
@dataclass
class Turn:
    question: str
    cypher: str | None        # the Cypher that was generated
    graph_results: list[dict] # raw Neo4j rows
    semantic_hits: list[dict] # ChromaDB passages
    answer: str

@dataclass
class ConversationState:
    turns: list[Turn]
    active_company_name: str | None
    active_company_cik:  str | None
    active_year_range:   tuple[int,int] | None
    active_topic:        str | None
    window_size: int = 8
```

---

### 2. Query Router (`router.py`)

Single LLM call that outputs structured JSON:

```
Input:  conversation history (last N turns) + new question
Output: {
  "intent":  "company" | "temporal" | "cross_company" | "trend" | "clarify",
  "company": "TYSON FOODS INC" | null,       // resolved to graph name
  "cik":     "0000100493" | null,
  "years":   [2020, 2024] | null,            // [from, to]
  "topic":   "supply_chain" | "tariff" | "cybersecurity" | ...,
  "cypher_hint": "short description of what graph traversal is needed"
}
```

The router also resolves company aliases:
- "Tyson" → "TYSON FOODS INC" (fuzzy match against Company nodes)
- "KO" / "Coca-Cola" → "COCA COLA CO"
- "the company" → uses `active_company_name` from memory

---

### 3. Graph QA (`graph_qa.py`)

Two-step:

**Step A — Cypher generation**

Prompt includes:
1. The full graph schema (node types, relation types, key properties)
2. 6–8 worked examples covering each query pattern
3. The router's structured intent + cypher_hint
4. The question

Returns a valid Cypher query. Validated with a regex sanity check before
execution (must start with MATCH/CALL/WITH, no DETACH DELETE etc.)

**Step B — Execute + format**

```python
with neo4j_driver.session() as s:
    results = s.run(cypher).data()
```

Returns up to 50 rows passed to the synthesiser.

**Schema fed to the LLM:**

```
Node labels and key properties:
  Company          : name, cik, ticker, sic_code
  Filing           : accession_number, filing_date, fiscal_year, form_type
  Section          : section_type (risk_factors|business|mda)
  FiscalYear       : year
  RiskFactor       : summary, category, severity
  RiskDriver       : name, driver_type
  RiskConsequence  : description
  Mitigation       : description, mitigation_type
  GeographicMarket : name, iso_code
  Competitor       : name
  Product          : name, segment
  BusinessSegment  : name, revenue_pct
  FinancialMetric  : name, value, unit, period
  MacroFactor      : name, direction

Relationships:
  (Filing)-[:FILED_BY]->(Company)
  (Filing)-[:HAS_SECTION]->(Section)
  (Filing)-[:FILED_IN]->(FiscalYear)
  (FiscalYear)-[:PRECEDES]->(FiscalYear)
  (Company)-[:HAS_RISK]->(RiskFactor)        [via filing]
  (RiskFactor)-[:CAUSED_BY]->(RiskDriver)
  (RiskFactor)-[:MAY_RESULT_IN]->(RiskConsequence)
  (RiskFactor)-[:MITIGATED_BY]->(Mitigation)
  (RiskFactor)-[:SUPERSEDES]->(RiskFactor)   [cross-year]
  (Company)-[:OPERATES_IN]->(GeographicMarket)
  (Company)-[:COMPETES_WITH]->(Competitor)
  (Company)-[:HAS_OUTLOOK]->(ManagementOutlook)
  (FinancialMetric)-[:IMPACTED_BY]->(MacroFactor)
```

**Worked Cypher examples in the prompt:**

```cypher
-- Company-specific: all risk factors for a company's latest filing
MATCH (c:Company {name: $company})<-[:FILED_BY]-(f:Filing)-[:HAS_SECTION]->(s:Section)
WHERE s.section_type = 'risk_factors'
WITH f, s ORDER BY f.fiscal_year DESC LIMIT 1
MATCH (c)-[:HAS_RISK]->(rf:RiskFactor)
WHERE rf.accession_number = f.accession_number
RETURN rf.summary, rf.category, rf.severity
ORDER BY rf.severity DESC

-- Temporal: how a risk category changed across years
MATCH (c:Company {name: $company})<-[:FILED_BY]-(f:Filing)
MATCH (c)-[:HAS_RISK]->(rf:RiskFactor)
WHERE rf.accession_number = f.accession_number
AND rf.category = $topic
RETURN f.fiscal_year, rf.summary
ORDER BY f.fiscal_year

-- Cross-company: companies sharing a risk driver
MATCH (rd:RiskDriver {name: $driver})<-[:CAUSED_BY]-(rf:RiskFactor)
MATCH (c:Company)-[:HAS_RISK]->(rf)
RETURN DISTINCT c.name, count(rf) as risk_count
ORDER BY risk_count DESC LIMIT 20

-- Geographic exposure across companies
MATCH (c:Company)-[:OPERATES_IN]->(g:GeographicMarket {name: $country})
MATCH (c)<-[:FILED_BY]-(f:Filing)
WHERE f.fiscal_year = $year
RETURN c.name, c.ticker ORDER BY c.name

-- Temporal trend: risk category frequency year-over-year
MATCH (f:Filing)-[:FILED_IN]->(fy:FiscalYear)
MATCH (c:Company)<-[:FILED_BY]-(f)
MATCH (c)-[:HAS_RISK]->(rf:RiskFactor)
WHERE rf.category = $topic AND rf.accession_number = f.accession_number
RETURN fy.year, count(rf) as count ORDER BY fy.year
```

---

### 4. Semantic QA (`semantic_qa.py`)

Used when:
- The question asks for verbatim language ("how exactly do they describe...")
- Graph QA returns no results (LLM extraction is incomplete in fast mode)
- The question is about nuance/tone rather than structure

```python
from chromadb import PersistentClient

def search(question: str, company: str | None, n_results: int = 8):
    where = {"company_name": company} if company else None
    hits = collection.query(
        query_texts=[question],
        n_results=n_results,
        where=where,
    )
    return [
        {
            "text":     doc,
            "company":  meta["company_name"],
            "year":     meta["fiscal_year"],
            "section":  meta["section_type"],
            "distance": dist,
        }
        for doc, meta, dist in zip(
            hits["documents"][0],
            hits["metadatas"][0],
            hits["distances"][0],
        )
    ]
```

---

### 5. Answer Synthesiser (`synthesiser.py`)

Merges graph facts + semantic passages into a single grounded answer.

**Prompt structure:**

```
SYSTEM:
You are a financial analyst assistant specialising in SEC 10-K filings.
Answer questions using ONLY the provided context. Cite your sources as
[Company, FY20XX] after each claim. Never speculate beyond the filings.

USER:
Question: {question}

--- GRAPH FACTS ---
{formatted neo4j rows — bullet points}

--- FILING EXCERPTS ---
{top-K ChromaDB passages with metadata}

--- CONVERSATION HISTORY ---
{last N turns}

Answer concisely. If data is limited, say so explicitly.
```

---

### 6. Streamlit UI (`app.py`)

```
┌─────────────────────────────────────────────────────┐
│  SEC Knowledge Graph Chat                           │
├──────────────────────────┬──────────────────────────┤
│                          │  Live Graph Panel        │
│  [chat history here]     │                          │
│                          │  [Neo4j subgraph of the  │
│                          │   last answer, rendered  │
│                          │   with pyvis]            │
│                          │                          │
│  Context chips:          │                          │
│  [TYSON FOODS] [2020-24] │                          │
│  [supply_chain]          │                          │
│                          │                          │
│  > type question here    │                          │
└──────────────────────────┴──────────────────────────┘
```

Key Streamlit features:
- `st.chat_message` for the conversation
- `st.sidebar` for active context (company, years, topic) and model selector
- `pyvis` HTML component for the live graph panel (renders Neo4j subgraph
  of the nodes and edges referenced in the last answer)
- Expandable "Show Cypher" / "Show Sources" sections under each answer

---

## Build Plan — Phases

### Phase 1 — Working skeleton (1 session)

Goal: end-to-end pipeline, no UI polish. Proves the concept.

1. `memory.py` — dataclasses only, no persistence
2. `prompts.py` — schema string + 6 Cypher examples + synthesiser prompt
3. `graph_qa.py` — generate Cypher → execute → return rows
4. `semantic_qa.py` — ChromaDB query wrapper
5. `synthesiser.py` — merge + LLM call
6. `router.py` — intent + entity extraction
7. `app.py` — minimal: text input → print answer to page

Test with:
```bash
streamlit run python/chatbot/app.py --server.port 8501 --server.address 0.0.0.0
```
Access from Windows: `http://192.168.1.39:8501`

---

### Phase 2 — Conversation quality (1 session)

- Co-reference resolution ("the company", "that risk", "the previous year")
- Better company alias matching (fuzzy + CIK lookup from ticker_to_cik.csv)
- Cypher error recovery (if execution fails, ask LLM to fix the query once)
- Session persistence (save/load conversation to JSON)

---

### Phase 3 — UI and graph visualisation (1 session)

- `pyvis` graph panel showing nodes + edges relevant to the last answer
- Context chips (active company, year range, topic) with click-to-clear
- Model selector in sidebar (Ollama / Anthropic / OpenAI)
- "Show Cypher" expander for power users
- Export answer as markdown

---

### Phase 4 — Cross-company and trend queries (after LLM KG population)

These queries are most useful once the graph has LLM-extracted RiskFactor nodes
(i.e. after `python3 run_kg_population.py --section risk_factors` with LLM mode).

- Risk co-occurrence: "Which risks tend to appear together?"
- Sector comparison: "How does tech sector cybersecurity exposure compare to finance?"
- Temporal trends: "Which risk types emerged after 2022?"

---

## Installation

```bash
pip install streamlit pyvis chromadb neo4j
```

No new infrastructure needed — reuses existing Neo4j, ChromaDB, and LLMClient.

---

## Running

```bash
# From repo root
streamlit run python/chatbot/app.py --server.port 8501 --server.address 0.0.0.0
```

Access from Windows browser: `http://192.168.1.39:8501`

Or use the launcher:
```bash
bash python/chatbot/run_chatbot.sh
```

---

## Example Conversations

**Company-specific:**
```
You: What are Tyson Foods' supply chain risks?
Bot: Tyson Foods disclosed three primary supply chain risks in their FY2023 10-K:
     1. Live cattle and hog procurement concentration — they source from ~7,000
        independent producers [Tyson Foods, FY2023]
     2. Single-plant concentration for certain product lines [Tyson Foods, FY2023]
     3. Cold storage and refrigerated transport capacity [Tyson Foods, FY2022-23]

You: How has that changed since 2019?
Bot: Comparing FY2019 to FY2023, procurement concentration risk disclosures
     increased significantly — in 2019 Tyson described diversified sourcing,
     while 2021-2023 filings added explicit references to COVID-era disruptions
     and post-pandemic consolidation of their supplier base. [Tyson Foods, FY2019,
     FY2021, FY2023]
```

**Cross-company:**
```
You: Which food companies disclose the most tariff risk?
Bot: Across FY2022-2024 filings, the companies with the highest tariff risk
     exposure (by risk factor mentions) are:
     1. Tyson Foods     — 14 filings mentioning tariff/trade risk
     2. Estee Lauder    — 11 filings (China + EU exposure)
     3. Southern Copper — 9 filings (metal export tariffs)
     [Sources: FY2022-2024 risk_factors sections]

You: Drill into Southern Copper
Bot: [switches active_company to Southern Copper, answers follow-ups in context]
```

**Temporal trend:**
```
You: Has AI risk disclosure increased since 2022?
Bot: Yes — across all companies in the graph, mentions of AI-related risks
     jumped from 23 filings in FY2022 to 187 in FY2024, a 7x increase.
     The most common framing shifted from "AI as competitive opportunity" (2022)
     to "AI regulation and liability" (2024). [Cross-company trend, FY2022-2024]
```

---

## Limitations to Be Aware Of

| Limitation | Impact | Workaround |
|---|---|---|
| Fast-mode graph has no RiskFactor nodes | Company/temporal risk questions fall back to ChromaDB semantic search | Run LLM-mode KG population for target companies |
| 2025 tariff events not in data | Cannot answer "what is the impact of Trump's 2025 tariffs" | Latest filings (FY2024, filed early 2025) may have forward-looking mentions |
| ChromaDB covers preprocessed corpus only | New filings not in ChromaDB until preprocessing cron runs | Cron runs hourly automatically |
| LLM-generated Cypher can be wrong | Occasional bad queries, no results | Phase 2 adds error recovery |

---

## Key Design Decisions

**Why Text-to-Cypher over a pure vector approach?**
The graph structure encodes relationships that flat text search cannot express:
cross-year risk evolution, competitor networks, geographic exposure by sector.
Vector search is better for nuance/tone; graph is better for facts and structure.
The hybrid approach uses both.

**Why Streamlit over FastAPI?**
Faster to build. The goal is a working analytical tool, not a production API.
Swap to FastAPI + React later if needed.

**Why reuse LLMClient?**
Keeps provider-switching intact. You can run the chatbot on Ollama (free, local)
and switch to Anthropic for higher quality answers without changing any code —
just set `LLM_PROVIDER=anthropic` in `.env`.
