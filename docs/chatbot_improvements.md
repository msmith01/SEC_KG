# Chatbot Q&A Improvements

_Last updated: 2026-02-27_

---

## Diagnosed Bugs (from "TSLA MD&A 2017" failure)

The query _"What was TSLA's MD&A opinions in 2017?"_ returned no useful results despite
Tesla data existing in the graph. Root causes, in order of severity:

---

### BUG-1 — Wrong property name in schema doc: `summary` vs `text`

**File:** `python/chatbot/prompts.py`, `GRAPH_SCHEMA`

The schema doc says:
```
ManagementOutlook: summary (string), sentiment (string), horizon (string)
```
The actual Neo4j property is **`text`**, not `summary`. There is no `summary` property.
Querying `mo.summary` returns `null` for every node, making all ManagementOutlook
results silently empty.

**Fix:** Change schema doc to `text (string)`. Audit all other node property names in
`GRAPH_SCHEMA` against actual graph properties. Confirmed correct: `text`, `sentiment`,
`horizon`, `accession`, `cik`, `provenance_section_type`, `provenance_filing_ref`.

---

### BUG-2 — Ticker alias not converted to graph-searchable form before Cypher

**File:** `python/chatbot/router.py`, `_resolve_company()`

The router resolves `"TSLA"` → CIK `"1318605"` via the ticker CSV, but leaves
`routing["company"] = "TSLA"`. The Cypher template then generates:
```cypher
WHERE toLower(c.name) CONTAINS 'tsla'
```
`"TESLA INC"` toLower is `"tesla inc"` — this does **not** contain `"tsla"`.
The match silently returns zero rows.

**Fix (two-part):**
1. When CIK is resolved, pass it to Cypher and use exact CIK matching:
   ```cypher
   WHERE c.cik = "1318605"   -- no fuzzy needed
   ```
   Add `{cik}` to `CYPHER_TEMPLATE` and include a rule: _"If cik is provided, match
   on `c.cik = '{cik}'` instead of name CONTAINS"_.

2. Alternatively (belt-and-suspenders): after resolving CIK, do a single Neo4j lookup
   to fetch the canonical company name and replace `routing["company"]` with it:
   ```cypher
   MATCH (c:Company) WHERE c.cik = $cik RETURN c.name LIMIT 1
   ```
   Then Cypher generation uses the exact graph name.

---

### BUG-3 — No year filtering path for ManagementOutlook

**File:** `python/chatbot/prompts.py`, `CYPHER_EXAMPLES`

`ManagementOutlook` has **no `fiscal_year` property**. To filter by year you must join
through `Filing` via the `accession` property:
```cypher
MATCH (c:Company)-[:HAS_OUTLOOK]->(mo:ManagementOutlook)
WHERE c.cik = "1318605"
MATCH (f:Filing)
WHERE f.accession_number = mo.accession
  AND f.fiscal_year = 2017
RETURN mo.text, mo.sentiment, mo.horizon
LIMIT 30
```
No example of this pattern exists in `CYPHER_EXAMPLES`, so the LLM generates
`WHERE mo.fiscal_year = 2017` which matches nothing.

Same issue applies to `FinancialMetric`, `RiskFactor`, `Competitor`, `GeographicMarket` —
any node type that stores `accession_number` / `accession` rather than `fiscal_year`
directly needs this join pattern.

**Fix:** Add a dedicated example to `CYPHER_EXAMPLES`:
```
EXAMPLE — MD&A outlook for a company in a specific year:
MATCH (c:Company)-[:HAS_OUTLOOK]->(mo:ManagementOutlook)
WHERE c.cik = "1318605"
MATCH (f:Filing) WHERE f.accession_number = mo.accession AND f.fiscal_year = 2017
RETURN mo.text AS outlook, mo.sentiment, mo.horizon
LIMIT 30
```
Also add a schema note: _"ManagementOutlook.accession links to Filing.accession_number
for year filtering"_.

---

### BUG-4 — Misleading "overview" fallback when query returns empty

**File:** `python/chatbot/graph_qa.py`, `run()`

When a Cypher query returns zero rows (or errors), `graph_qa.py` falls back to:
```cypher
MATCH (n) RETURN labels(n)[0] AS type, count(n) AS count ORDER BY count DESC
```
This returns "ManagementOutlook: 1,900,000 nodes" etc. The synthesiser then produces
the misleading response: _"The graph has 1.9M ManagementOutlook nodes but no TSLA 2017
data was retrieved"_ — implying the data exists but can't be found, when the real
problem is a bad query.

**Fix:**
- Before triggering the overview fallback, log the generated Cypher so it can be debugged.
- Change the synthesiser's instruction to say: _"If `_overview` rows appear it means the
  specific query returned nothing — state that clearly and tell the user what years/companies
  ARE available for that topic."_
- Add a targeted follow-up query instead of a generic overview:
  ```cypher
  -- When company + year query returns empty, check what years ARE available for that company:
  MATCH (c:Company)<-[:FILED_BY]-(f:Filing)
  WHERE c.cik = $cik
  RETURN collect(DISTINCT f.fiscal_year) AS available_years
  ```
  This lets the bot say "Tesla has filings for 2018–2024 in the graph; 2017 is not available"
  rather than dumping a node count.

---

### BUG-5 — No Cypher retry on syntax/property error

**File:** `python/chatbot/graph_qa.py`, `_execute()`

If the LLM generates invalid Cypher (wrong property name, bad syntax), the error is
silently swallowed and the overview fallback fires. The LLM is never told it was wrong.

**Fix:** On exception, send the error + original Cypher back to the LLM for one retry:
```python
def _execute_with_retry(self, cypher: str, question: str, routing: dict) -> list[dict]:
    rows = self._execute(cypher)
    if rows and rows[0].get("error"):
        # Ask LLM to fix it
        fixed_cypher = self._fix_cypher(cypher, rows[0]["error"])
        if fixed_cypher and fixed_cypher != cypher:
            rows = self._execute(fixed_cypher)
    return rows

def _fix_cypher(self, cypher: str, error: str) -> str | None:
    prompt = f"This Cypher query failed:\n{cypher}\n\nError: {error}\n\nFix it. Output only the corrected Cypher."
    raw = self.llm.complete(prompt, system=CYPHER_SYSTEM)
    fixed = self._clean_cypher(raw)
    return fixed if self._is_safe(fixed) else None
```

---

## Structural Improvements (not bugs, but significant quality gains)

---

### IMP-1 — Semantic search is a better primary path for MD&A questions

The graph's ManagementOutlook nodes are spaCy-extracted — they are essentially every
sentence from MDA sections tagged as "outlook", not curated summaries. For a question
like "what were TSLA's MD&A opinions in 2017?" the **ChromaDB semantic search** over
the preprocessed MDA section text will return far more relevant, readable results than
graph traversal.

**Fix:** In `graph_qa.py` / `app.py`, route `intent == "company"` + `section = "mda"`
questions **primarily** to ChromaDB semantic search, with graph as supplement.
The router should emit `"primary_source": "semantic"` for MD&A/opinion/tone questions
and `"primary_source": "graph"` for structured queries (competitors, geo markets,
financial metrics, risk factors).

---

### IMP-2 — Show the generated Cypher in the UI

Users can't debug or trust the chatbot if they can't see what query was run.
The Cypher is already returned from `graph_qa.run()` as the first tuple element —
it just isn't displayed.

**Fix:** In `app.py`, add an expander below each assistant response:
```python
with st.expander("View Cypher query"):
    st.code(cypher, language="cypher")
```

---

### IMP-3 — Company name resolution via Neo4j lookup

The ticker CSV only maps ticker → CIK. It doesn't help when users type partial names
like "Tesla", "Tyson", "J&J", "Apple". And the CONTAINS fuzzy match on the company
name passed through from the LLM is unreliable (see BUG-2).

**Fix:** After the LLM extracts a company entity, run a single Neo4j query to snap it
to the canonical graph name:
```python
def resolve_company_name(driver, name: str) -> tuple[str, str] | None:
    """Returns (canonical_name, cik) or None."""
    with driver.session() as s:
        rows = list(s.run(
            "MATCH (c:Company) WHERE toLower(c.name) CONTAINS toLower($term) "
            "OR toLower(c.ticker) = toLower($term) "
            "RETURN c.name, c.cik, c.ticker ORDER BY c.name LIMIT 5",
            term=name
        ))
    if rows:
        return rows[0]["c.name"], rows[0]["c.cik"]
    return None
```
Do this in `router.py` after LLM extraction, before Cypher generation.
Then Cypher can use exact `c.cik = $cik` instead of fuzzy name CONTAINS.

---

### IMP-4 — Session persistence across restarts

Conversation history is lost when the Streamlit process restarts. `memory.py` holds
everything in-memory.

**Fix:** Add `save(path)` / `load(path)` to `ConversationState` in `memory.py`:
```python
def save(self, path: str):
    import json
    with open(path, "w") as f:
        json.dump({"turns": self.turns, "active_company": ..., ...}, f)

def load(self, path: str):
    import json
    if os.path.exists(path):
        data = json.load(open(path))
        self.turns = data.get("turns", [])
        ...
```
Call `save()` after every new turn; call `load()` at `ConversationState.__init__`.
Session file: `python/data/chatbot_session.json`.

---

### IMP-5 — "What years are available?" diagnostic query

When a user asks about a specific company + year and nothing is found, the bot should
automatically follow up with what IS available:
```cypher
MATCH (c:Company)<-[:FILED_BY]-(f:Filing)
WHERE c.cik = $cik
RETURN collect(DISTINCT f.fiscal_year) AS available_years
ORDER BY f.fiscal_year
```
Show: _"Tesla filings available in graph: 2018, 2019, 2020, 2021, 2022, 2023, 2024.
The 2017 filing was not collected."_

---

### IMP-6 — ManagementOutlook quality is low for spaCy extraction

The 1.9M ManagementOutlook nodes were all created by spaCy (fast mode), which applies
a heuristic to tag any sentence from an MDA section as "outlook". Most of these are
accounting boilerplate, not actual management opinions.

**Long-term fix:** Run LLM-mode KG population (`run_kg_population.py` without `--fast`)
on a priority company set (e.g. S&P 500 subset). This extracts genuine ManagementOutlook
nodes with curated summaries, higher-quality sentiment, and proper horizon labels.
Until then, semantic search on the raw MDA text (ChromaDB) is a better substitute.

---

## Priority Order for Implementation

| Priority | Bug/Improvement | Effort | Impact |
|----------|----------------|--------|--------|
| 1 | BUG-2: CIK-based Cypher matching | Small | High — fixes all ticker queries |
| 2 | BUG-1: Fix `summary` → `text` in schema doc | Trivial | High — fixes all ManagementOutlook queries |
| 3 | BUG-3: Add year-join Cypher example | Small | High — fixes all year-filtered queries |
| 4 | IMP-3: Neo4j company name resolver | Small | High — fixes all partial name queries |
| 5 | BUG-4: Better "no results" fallback | Medium | Medium — less confusing responses |
| 6 | BUG-5: Cypher retry on error | Medium | Medium — self-healing queries |
| 7 | IMP-2: Show Cypher in UI | Trivial | Medium — debuggability |
| 8 | IMP-1: Semantic primary for MD&A | Medium | High — but needs routing logic change |
| 9 | IMP-5: "Available years" diagnostic | Small | Medium — better UX when data missing |
| 10 | IMP-4: Session persistence | Small | Low-medium — convenience |
