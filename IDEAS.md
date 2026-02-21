# SEC Knowledge Graph — Business Use Cases & Product Ideas

*What can you do with a structured knowledge graph of every public US company's 10-K filings,
spanning 30+ years, with typed entities, relationships, temporal links, and semantic search?*

---

## What This Project Actually Produces

Before the use cases, it helps to be precise about the data assets:

| Asset | Description |
|-------|-------------|
| **~7,880 companies** | Every publicly listed US company that filed a 10-K |
| **30+ years** | 1993–2024 (2015–2024 active, 1993–2014 queued) |
| **~3 sections per filing** | Business Description (Item 1), Risk Factors (Item 1A), MD&A (Item 7) |
| **~117K section files** | For 2015–2024 alone |
| **Typed entities** | Company, Filing, BusinessSegment, Product, GeographicMarket, CustomerSegment, Competitor, Regulation, RiskFactor, RiskDriver, RiskConsequence, Mitigation, FinancialMetric, ManagementOutlook |
| **25 relation types** | COMPETES_WITH, HAS_RISK, CAUSED_BY, MAY_RESULT_IN, MITIGATED_BY, OPERATES_IN, SUBJECT_TO, DRIVEN_BY, and more |
| **Temporal layer** | FiscalYear anchor nodes with PRECEDES chains — every entity is time-stamped |
| **Vector store** | ChromaDB sentence-level embeddings for semantic similarity search |

The fundamental advantage: 10-K filings are **legally mandated, standardised, and comparable across every public US company**. This isn't scraped PR copy — it is sworn disclosure text. The signal quality is unusually high.

---

## 1. Investment & Asset Management

The most natural commercial fit. Investors have always read 10-Ks; this makes the reading systematic.

### Risk Signal Generation (Alpha)
- **New risk emergence** — detect when a company adds a risk factor that wasn't in the prior year's filing. New disclosures often precede negative events.
- **Risk escalation** — same risk factor reappearing with stronger consequence language year-over-year.
- **Risk de-escalation** — a previously prominent risk disappearing (potential positive signal, or a red flag if the underlying condition hasn't changed).
- **Idiosyncratic vs sector risk** — distinguish risks a company mentions that its peers don't. Idiosyncratic risks are more company-specific and potentially more actionable.

### Portfolio Risk Mapping
- Map all holdings across a portfolio onto the risk taxonomy.
- Answer: *"Across my 80-stock portfolio, what fraction of my companies are exposed to China supply chain risk?"*
- Stress-test a portfolio against a macro scenario (e.g., rising interest rates) by finding all companies with `RiskDriver: interest_rate` nodes.

### Competitive Intelligence
- The `COMPETES_WITH` graph — derived from companies naming each other as competitors — is a structured market map. Cross-reference it: if Company A names Company B, does Company B name Company A? Who names whom as a threat?
- Find companies that are named as competitors by many others but are themselves private → acquisition targets or IPO watch.

### Thematic / Macro Investing
- *"Find all companies with material exposure to semiconductor supply chain risk"* — graph traversal across `HAS_RISK → RiskDriver: semiconductor_supply`
- Track emerging themes: when did "AI" first appear as a competitive risk factor? Which sectors led?
- Climate transition risk: extract companies with Regulation nodes tied to carbon/emissions disclosures.

### Pre-Earnings Screening
- Companies that substantially changed their forward-looking language (ManagementOutlook) in Q4 filings sometimes signal earnings surprises. Combine with ChromaDB semantic search for sentiment shifts.

---

## 2. Credit & Fixed Income

Credit analysts spend significant time reading 10-K risk sections. Automation here has clear value.

### Credit Due Diligence Automation
- On a new bond issuance, instantly extract and structure all risk disclosures from the issuer's last 3–5 filings.
- Cross-reference against sector peers: is this issuer disclosing materially more or fewer risks than comparable companies? Gaps can indicate disclosure quality issues.

### Leading Indicator Signals
- **Consequence severity tracking** — `RiskConsequence` nodes with "material adverse effect", "going concern", "significant impairment" language are structured distress signals.
- **Liquidity risk concentration** — companies that simultaneously add liquidity + refinancing + covenant risk nodes in a single year.
- **New regulation nodes** — companies citing new regulatory obligations they weren't subject to previously.

### Covenant Monitoring (Post-Issuance)
- Set up alerts: when a borrower's 10-K adds a risk factor category not present at issuance, flag for covenant review.
- Track changes in geographic market exposure for borrowers with geographic covenants.

---

## 3. Insurance & Underwriting

Insurers price risk. 10-K risk disclosures are the most standardised risk self-assessments available for public companies.

### Commercial Lines Underwriting
- Sector-wide risk landscapes: what risks are semiconductor companies disclosing vs five years ago? Use this to inform pricing models.
- Product liability: extract companies with `Product` nodes in specific categories + related `RiskFactor` nodes citing product safety/recall.
- Business interruption: which companies disclose single-supplier dependencies as a risk driver?

### D&O (Directors & Officers) Insurance
- Governance and litigation risk signals in risk factor language.
- Companies disclosing regulatory investigations or material weakness in controls → elevated D&O risk.
- Benchmark a company's disclosure quality against peers — thin disclosure can signal governance risk.

### Cyber Insurance
- Track the growth and specificity of cyber risk disclosures year-over-year across a sector.
- Companies whose cyber risk disclosures became significantly more detailed are either maturing their security posture or experiencing incidents.

### Emerging Risk Identification
- New `RiskFactor` nodes that appear for the first time across many companies in a short window = emerging systemic risk.
- Examples the graph would have caught early: pandemic risk (2019→2020), AI-competition risk (2022→2023), interest rate risk re-emergence (2021→2022).

---

## 4. M&A and Private Equity

Due diligence is the most time-intensive and legally consequential use case for 10-K reading.

### Automated Due Diligence Package
- For a target company: instantly produce a structured risk profile — all disclosed risks, drivers, consequences, and mitigations across the last 5 years.
- Cross-reference against sector norms: which risks does the target disclose that peers don't? Which do peers disclose that the target omits (potential blind spots or disclosure gaps)?

### Deal Risk Assessment
- Idiosyncratic risk score: ratio of target's unique risk nodes vs sector-common risk nodes.
- Identify key person risk, customer concentration risk, single-market exposure from structured entities.

### Sector Landscape Mapping for Origination
- Use the `COMPETES_WITH` graph to map competitive clusters.
- Use `HAS_SEGMENT + OPERATES_IN + TARGETS` to find companies with similar business models → roll-up candidates.
- Find sectors where `FinancialMetric` outlook nodes cluster positively → sector momentum.

### Portfolio Company Monitoring
- For PE-backed companies (those that later go public or have public comps), track peer risk evolution to anticipate what your portfolio company may face.

---

## 5. Legal & Compliance

Law firms, general counsel, and compliance teams have direct use for structured disclosure data.

### Disclosure Adequacy Benchmarking
- *"Are our client's 10-K risk disclosures in line with peers, or materially thinner?"*
- For a given industry, extract the median number of risk factors, risk drivers per factor, and mitigation disclosures — benchmark a specific company against those norms.
- Material gaps in disclosure relative to peers are a litigation and regulatory risk.

### Regulatory Change Monitoring
- Track how companies updated their `Regulation` nodes and related `RiskFactor` disclosures in the year following a major regulatory event (e.g., GDPR, Dodd-Frank, CHIPS Act).
- Which companies adapted their disclosures quickly? Which lagged?

### Securities Litigation Signals
- Companies with material omissions — risks that later materialised (captured in `MAY_RESULT_IN → RiskConsequence`) but were not adequately disclosed in prior filings.
- Cross-reference the graph with SEC enforcement actions to train a risk-of-omission model.

### Antitrust / Market Structure Analysis
- The `COMPETES_WITH` graph is structured evidence of market definition — useful in merger review or antitrust matters.
- Bidirectional COMPETES_WITH citations between two companies are strong evidence they operate in the same product market.

---

## 6. Management Consulting & Corporate Strategy

### Sector Risk Landscape Reports
- Automated quarterly reports: *"The 10 most common risk drivers in the pharmaceutical sector, and how they changed from 2023 to 2024."*
- Compare a client's risk profile against sector distribution — what are they over-disclosing (overly cautious) or under-disclosing (potentially exposed)?

### Competitive Intelligence Service
- Track named competitors: when Company B is named in Company A's `COMPETES_WITH` nodes, monitor Company B's risk profile for changes.
- Identify emerging competitors: new companies appearing in `COMPETES_WITH` nodes of established players.

### Geopolitical Exposure Mapping
- All companies with `OPERATES_IN` nodes for specific geographies (China, Russia, Middle East, etc.)
- Cross-reference with `RiskFactor` nodes citing geopolitical/sanctions/tariff risk.
- Answer: *"Which S&P 500 companies have the most concentrated revenue exposure to China + the highest tariff risk disclosure?"*

### Supply Chain Risk Clusters
- Find companies that share common `RiskDriver` nodes (e.g., semiconductor shortage, freight costs, lithium supply).
- These companies form implicit supply chain risk communities — useful for clients assessing systemic exposure.

---

## 7. Corporate and IR Teams

### Peer Benchmarking for IR / Legal
- Before filing, run your draft risk factors through the graph: how do they compare in coverage, specificity, and language to the top 20 peers?
- Flag risks peers disclose that you haven't addressed — reduces litigation exposure.

### Risk Committee Reporting
- Automated, structured dashboard fed directly from the company's own filings over time.
- Show the board: which risk factors are new this year, which escalated, which were removed?
- Compare to peers on the same dashboard.

### Competitor Watch Alerts
- Alert when a named competitor files a 10-K with a materially new or changed risk profile.
- Alert when a new company names you as a competitor for the first time.

---

## 8. Government and Regulators

### SEC Disclosure Quality Monitoring
- Flag companies whose 10-K risk sections are materially thinner (fewer risk factors, shorter, fewer drivers cited) than sector peers of similar size.
- Identify disclosure cliff drops: companies that went from detailed to sparse risk disclosure after an event.

### Systemic Risk Identification
- Risks that simultaneously appear across many companies in a short period = macro shocks or systemic vulnerabilities.
- The graph would clearly show COVID-19 risk propagating across every sector simultaneously in 2020 filings.
- Could give regulators an early warning dashboard.

### Industry Health Monitoring
- Track `FinancialMetric` trend nodes and `ManagementOutlook` sentiment across a sector over time.
- Combine with risk factor trends for a composite sector health score.

---

## 9. Data Products & SaaS Opportunities

This project's output is itself a high-value data product. Potential commercialisation paths:

### Risk Intelligence API
- REST API over the Neo4j graph: query risk factors by company, sector, year, risk type, driver.
- Subscription tiers: single company, sector, full market.
- Target buyers: quant funds, credit analysts, insurers.

### Alert / Monitoring Subscriptions
- **RiskRadar** — weekly digest: here's what changed in the 10-K risk profiles of your watchlist companies.
- **SectorPulse** — quarterly report: top emerging and declining risks across a sector, built entirely from this graph.
- **CompetitorWatch** — alert when a company named as your competitor files a material change.

### Due Diligence Reports (PDF/API)
- On-demand: submit a company ticker, receive a structured due diligence brief — risk taxonomy, peer comparison, 5-year risk evolution, idiosyncratic risk flags.
- Target buyers: M&A advisors, PE firms, credit desks.

### ESG Intelligence Layer
- Extract and classify climate, social, and governance-related risk factors, regulations, and mitigations from the graph.
- Sell as an ESG risk data product — differentiated from ratings agencies by being bottom-up, text-derived, and auditable.

---

## 10. Research and Academic Use Cases

### Finance / Economics Research
- *Do companies that add new risk factor categories predict negative earnings surprises?* (risk disclosure as earnings signal)
- *How do risk disclosures propagate across industry peers?* (herding behaviour in disclosure)
- *Does risk disclosure quality predict SEC enforcement actions?*
- *How did COVID-19 risk appear and propagate across the 10-K corpus?*

### NLP Research
- The corpus is an excellent benchmark for financial NLP: named entity recognition, relation extraction, temporal reasoning, coreference resolution.
- The structured labels produced by the pipeline (RiskFactor → RiskDriver → RiskConsequence) are valuable training data for supervised models.

### Policy Research
- *How did companies respond to GDPR, CHIPS Act, climate disclosure rules in their filings?*
- *Which sectors show the most regulatory risk accumulation over time?*
- *Do disclosure mandates actually improve information quality?*

---

## 11. Example Queries the Graph Can Answer

These are all answerable with Cypher + ChromaDB, using the current schema:

```cypher
-- Top risk drivers across semiconductor companies, 2022
MATCH (c:Company)-[:FILED_BY]-(:Filing)-[:FILED_IN]-(:FiscalYear {year: 2022})
MATCH (c)-[:HAS_RISK]->(r:RiskFactor)-[:CAUSED_BY]->(d:RiskDriver)
WHERE c.sic_code STARTS WITH '367'
RETURN d.name, count(*) AS mentions ORDER BY mentions DESC LIMIT 10

-- Which companies first mentioned generative AI as a competitive risk?
MATCH (c:Company)-[:HAS_RISK]->(r:RiskFactor)
WHERE r.text CONTAINS 'generative AI' OR r.text CONTAINS 'large language model'
MATCH (r)<-[:HAS_RISK]-(c)-[:FILED_BY]->(f:Filing)-[:FILED_IN]->(fy:FiscalYear)
RETURN c.name, fy.year ORDER BY fy.year ASC LIMIT 20

-- Companies that COMPETES_WITH each other bidirectionally (competitive clusters)
MATCH (a:Company)-[:COMPETES_WITH]->(b:Company)-[:COMPETES_WITH]->(a)
RETURN a.name, b.name

-- Risk factors in 2019 that materialised in 2020 (cross-year linkage, post-implementation)
MATCH (r2019:RiskFactor {year: 2019})-[:SUPERSEDES|PERSISTED_TO]->(r2020:RiskFactor {year: 2020})
MATCH (r2020)-[:MAY_RESULT_IN]->(rc:RiskConsequence)
WHERE rc.severity = 'high'
RETURN r2019.name, r2020.name, rc.description

-- Companies with simultaneous supply chain + labour + inflation risk in 2022
MATCH (c:Company)-[:HAS_RISK]->(r1:RiskFactor)-[:CAUSED_BY]->(:RiskDriver {category: 'supply_chain'})
MATCH (c)-[:HAS_RISK]->(r2:RiskFactor)-[:CAUSED_BY]->(:RiskDriver {category: 'labour'})
MATCH (c)-[:HAS_RISK]->(r3:RiskFactor)-[:CAUSED_BY]->(:RiskDriver {category: 'inflation'})
WHERE r1.year = 2022 AND r2.year = 2022 AND r3.year = 2022
RETURN c.name

-- What mitigations do pharma companies most commonly cite for regulatory risk?
MATCH (c:Company)-[:HAS_RISK]->(r:RiskFactor)-[:CAUSED_BY]->(:RiskDriver {category: 'regulatory'})
MATCH (r)-[:MITIGATED_BY]->(m:Mitigation)
WHERE c.sic_code STARTS WITH '283'
RETURN m.description, count(*) AS freq ORDER BY freq DESC LIMIT 10
```

---

## 12. Highest-Value Near-Term Build Targets

Ranking by effort vs commercial potential:

| Priority | Build | Why |
|----------|-------|-----|
| 1 | **Natural language query interface (RAG over graph)** | Makes the graph accessible without Cypher. Highest demo value. |
| 2 | **Risk evolution timeline UI** | Visual: show how a company's risk profile changed year-over-year. Intuitive and fundable. |
| 3 | **Peer comparison report generator** | Automated PDF/JSON: company X vs sector peers on risk taxonomy. Direct sale to IR/legal teams. |
| 4 | **Cross-year semantic linking** (`PERSISTED_TO`, `EMERGED_IN`) | Unlocks temporal queries. Foundational for most of the above. |
| 5 | **Alert/watch service** | Lowest infrastructure lift; high recurring revenue potential. |
| 6 | **Sector risk dashboard (Streamlit)** | Fast to build, good for demos, potential enterprise sales entry point. |

---

## 13. Moat and Defensibility

What makes this hard to replicate:

- **Data depth** — 30 years × 7,880 companies × 3 sections is a significant ETL effort
- **Temporal graph structure** — the FiscalYear scaffold + cross-year edges are non-trivial to build correctly
- **Extraction quality** — the ontology is carefully designed around actual 10-K structure; generic extraction tools miss the RiskFactor → RiskDriver → RiskConsequence chain
- **Compounding data advantage** — the graph improves with each year added; competitors starting today are perpetually behind
- **ChromaDB + graph hybrid** — combining structured graph queries with vector similarity is a meaningful technical differentiator vs pure-text competitors

The weakest point: all data is public (SEC EDGAR is free). The moat is entirely in the quality of extraction, structuring, and interface — not data exclusivity.
