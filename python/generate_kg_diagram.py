#!/usr/bin/env python3
"""
Generate a Mermaid diagram illustrating the SEC Knowledge Graph schema
and sample data for multiple companies and fiscal years.

Usage:
    python python/generate_kg_diagram.py              # print to stdout
    python python/generate_kg_diagram.py > graph.mmd  # save to file
    # Then paste into https://mermaid.live to render

    # Or embed in Markdown:
    # ```mermaid
    # <paste output here>
    # ```
"""

from __future__ import annotations
from typing import List


# ── Sample data ───────────────────────────────────────────────────────────────

FISCAL_YEARS = [2022, 2023, 2024]

COMPANIES = [
    # (node_id, display_name, ticker, cik)
    ("AAPL",  "Apple Inc.",       "AAPL", "0000320193"),
    ("MSFT",  "Microsoft Corp.",  "MSFT", "0000789019"),
    ("TSLA",  "Tesla Inc.",       "TSLA", "0001318605"),
]

# One 10-K filing per company per year (not all combos — keeps diagram readable)
FILINGS = [
    # (company_id, filing_node_id, fiscal_year)
    ("AAPL", "F_AAPL_22", 2022),
    ("AAPL", "F_AAPL_23", 2023),
    ("AAPL", "F_AAPL_24", 2024),
    ("MSFT", "F_MSFT_23", 2023),
    ("MSFT", "F_MSFT_24", 2024),
    ("TSLA", "F_TSLA_23", 2023),
]

SECTION_TYPES = [
    ("risk_factors", "Risk Factors (Item 1A)"),
    ("business",     "Business Desc (Item 1)"),
    ("mda",          "MD&A (Item 7)"),
]

# ── Extracted entities (Level 3) ─────────────────────────────────────────────

# Business Description — deduplicated shared nodes
GEO_MARKETS = [
    ("GEO_US",  "geo_us",  "United States"),
    ("GEO_CN",  "geo_cn",  "China"),
    ("GEO_EU",  "geo_eu",  "European Union"),
    ("GEO_JP",  "geo_jp",  "Japan"),
]

CUSTOMER_SEGMENTS = [
    ("CS_CONSUMER",   "cs_consumer",     "Consumer"),
    ("CS_ENTERPRISE", "cs_enterprise",   "Enterprise"),
    ("CS_GOVT",       "cs_government",   "Government"),
]

REGULATIONS = [
    ("REG_GDPR",    "reg_gdpr",            "GDPR"),
    ("REG_CCPA",    "reg_ccpa",            "CCPA"),
    ("REG_SOX",     "reg_sarbanes_oxley",  "Sarbanes-Oxley"),
]

# Company-specific (filing-scoped) business nodes
BUSINESS_ENTITIES = {
    "AAPL": {
        "products":  [("PROD_IPHONE", "iPhone"), ("PROD_MAC", "Mac"), ("PROD_IPAD", "iPad")],
        "segments":  [("SEG_AAPL_SERVICES",  "Services"),  ("SEG_AAPL_PRODUCTS", "Products")],
        "competitors": [("COMP_SAMSUNG", "Samsung Electronics"), ("COMP_GOOGLE", "Alphabet Inc.")],
    },
    "MSFT": {
        "products":  [("PROD_AZURE", "Azure Cloud"), ("PROD_OFFICE365", "Microsoft 365"), ("PROD_TEAMS", "Microsoft Teams")],
        "segments":  [("SEG_MSFT_CLOUD", "Intelligent Cloud"), ("SEG_MSFT_PRODUCTIVITY", "Productivity & Business")],
        "competitors": [("COMP_AMAZON", "Amazon Web Services"), ("COMP_GOOGLE", "Alphabet Inc.")],
    },
    "TSLA": {
        "products":  [("PROD_MODEL3", "Model 3"), ("PROD_MODELX", "Model X"), ("PROD_ENERGY", "Energy Products")],
        "segments":  [("SEG_TSLA_AUTO", "Automotive"), ("SEG_TSLA_ENERGY", "Energy Generation")],
        "competitors": [("COMP_GM", "General Motors"), ("COMP_FORD", "Ford Motor Co.")],
    },
}

# Risk Factors — shared RiskDriver / RiskConsequence nodes
RISK_DRIVERS = [
    ("RD_GEOPOL",    "rd_geopolitical_tension",     "Geopolitical Tension"),
    ("RD_SUPPLIER",  "rd_single_source_supplier",   "Single-Source Supplier"),
    ("RD_CYBER",     "rd_cybersecurity_breach",     "Cybersecurity Breach"),
    ("RD_RATES",     "rd_rising_interest_rates",    "Rising Interest Rates"),
]

RISK_CONSEQUENCES = [
    ("RC_REVENUE",  "rc_revenue_decline",       "Revenue Decline"),
    ("RC_MARGIN",   "rc_margin_compression",    "Margin Compression"),
    ("RC_REPUT",    "rc_reputational_damage",   "Reputational Damage"),
]

# Filing-specific risk nodes (one per company for brevity)
RISK_FACTORS = {
    "AAPL": [
        ("RF_AAPL_SUPPLY",  "Supply Chain Disruption Risk",   ["RD_GEOPOL", "RD_SUPPLIER"], ["RC_REVENUE"]),
        ("RF_AAPL_CYBER",   "Data Privacy & Security Risk",   ["RD_CYBER"],                 ["RC_REPUT"]),
    ],
    "MSFT": [
        ("RF_MSFT_CLOUD",   "Cloud Competition Risk",         ["RD_GEOPOL"],               ["RC_REVENUE", "RC_MARGIN"]),
        ("RF_MSFT_REG",     "Regulatory & Antitrust Risk",    [],                           ["RC_REPUT"]),
    ],
    "TSLA": [
        ("RF_TSLA_DEMAND",  "EV Demand Uncertainty Risk",     ["RD_RATES"],                 ["RC_REVENUE"]),
        ("RF_TSLA_SUPPLY",  "Battery Supply Chain Risk",      ["RD_SUPPLIER"],              ["RC_MARGIN"]),
    ],
}

# MD&A — shared MacroFactor nodes
MACRO_FACTORS = [
    ("MACRO_RATES",     "macro_interest_rates",     "Rising Interest Rates"),
    ("MACRO_INFLATION", "macro_inflation",           "Inflationary Pressures"),
    ("MACRO_FX",        "macro_fx_headwinds",        "Foreign Exchange Headwinds"),
    ("MACRO_AI",        "macro_ai_investment_cycle", "AI Investment Cycle"),
]

# Filing-specific financial metrics (one per company for brevity)
FINANCIAL_METRICS = {
    "AAPL": [
        ("FM_AAPL_REV",    "Revenue $394B +2% YoY",    "MACRO_FX"),
        ("FM_AAPL_MARGIN", "Gross Margin 44.1%",        "MACRO_INFLATION"),
    ],
    "MSFT": [
        ("FM_MSFT_CLOUD",  "Azure Revenue +28% YoY",   "MACRO_AI"),
        ("FM_MSFT_EPS",    "EPS $11.45 +20% YoY",      None),
    ],
    "TSLA": [
        ("FM_TSLA_AUTO",   "Auto Revenue -8% YoY",     "MACRO_RATES"),
        ("FM_TSLA_MARGIN", "Auto Gross Margin 16.3%",  "MACRO_INFLATION"),
    ],
}

MANAGEMENT_OUTLOOKS = {
    "AAPL": [("MO_AAPL_1", "Cautious on China demand near-term",      "FM_AAPL_REV")],
    "MSFT": [("MO_MSFT_1", "Positive on AI services growth",          "FM_MSFT_CLOUD")],
    "TSLA": [("MO_TSLA_1", "Expects margin recovery in H2 from cuts", "FM_TSLA_MARGIN")],
}


# ── Builder ───────────────────────────────────────────────────────────────────

def build_mermaid(show_all_filings: bool = True, show_cross_section: bool = True) -> str:
    lines: List[str] = []

    def ln(*args: str) -> None:
        lines.extend(args)

    # ── Header ────────────────────────────────────────────────────────────────
    ln(
        "graph TB",
        "",
        "    %% SEC Knowledge Graph — schema + sample data (Apple, Microsoft, Tesla)",
        "    %% Generated by python/generate_kg_diagram.py",
        "",
    )

    # ── Styles ────────────────────────────────────────────────────────────────
    ln(
        "    classDef temporal   fill:#2980b9,stroke:#1a5276,color:#fff,font-weight:bold",
        "    classDef filing     fill:#8e44ad,stroke:#6c3483,color:#fff",
        "    classDef section_rf fill:#c0392b,stroke:#922b21,color:#fff",
        "    classDef section_biz fill:#e67e22,stroke:#ca6f1e,color:#fff",
        "    classDef section_mda fill:#16a085,stroke:#0e6655,color:#fff",
        "    classDef biz        fill:#f39c12,stroke:#9a7d0a,color:#fff",
        "    classDef riskNode   fill:#e74c3c,stroke:#922b21,color:#fff",
        "    classDef mdaNode    fill:#1abc9c,stroke:#0e8072,color:#fff",
        "    classDef shared     fill:#7f8c8d,stroke:#515a5a,color:#fff",
        "",
    )

    # ── Level 1: FiscalYear temporal chain ───────────────────────────────────
    ln("    %% ═══════════════════════════════════════════════════════════")
    ln("    %% LEVEL 1 — Temporal layer (shared across all companies)")
    ln("    %% ═══════════════════════════════════════════════════════════")
    for year in FISCAL_YEARS:
        ln(f'    FY{year}["FiscalYear | fy_{year}"]:::temporal')
    ln("")
    for i in range(len(FISCAL_YEARS) - 1):
        ln(f"    FY{FISCAL_YEARS[i]} -->|PRECEDES| FY{FISCAL_YEARS[i+1]}")
    ln("")

    # ── Level 2: Companies ────────────────────────────────────────────────────
    ln("    %% ═══════════════════════════════════════════════════════════")
    ln("    %% LEVEL 2 — Filing layer (Company → Filing → FiscalYear)")
    ln("    %% ═══════════════════════════════════════════════════════════")
    for cid, name, ticker, cik in COMPANIES:
        ln(f'    {cid}["Company | {name} ({ticker})\\ncik: {cik}"]:::filing')
    ln("")

    # ── Level 2: Filings + Section nodes ─────────────────────────────────────
    for company_id, filing_id, year in FILINGS:
        ln(f"    %% -- {company_id} {year} -------------------------")
        ln(f'    {filing_id}["Filing | 10-K {year}"]:::filing')
        ln(f"    {filing_id} -->|FILED_BY| {company_id}")
        ln(f"    {filing_id} -->|FILED_IN| FY{year}")

        for stype, slabel in SECTION_TYPES:
            sid = f"SEC_{filing_id}_{stype.upper()}"
            style = {"risk_factors": "section_rf", "business": "section_biz", "mda": "section_mda"}[stype]
            ln(f'    {sid}["Section\\n{slabel}"]:::{style}')
            ln(f"    {filing_id} -->|HAS_SECTION| {sid}")
        ln("")

    # ── Level 3: Shared nodes (Geographic, CustomerSegment, Regulation, etc.) ─
    ln("    %% ═══════════════════════════════════════════════════════════")
    ln("    %% LEVEL 3 — Shared deduplicated nodes")
    ln("    %% ═══════════════════════════════════════════════════════════")

    for nid, key, label in GEO_MARKETS:
        ln(f'    {nid}["GeographicMarket\\n{key}\\n{label}"]:::shared')
    ln("")

    for nid, key, label in CUSTOMER_SEGMENTS:
        ln(f'    {nid}["CustomerSegment\\n{key}\\n{label}"]:::shared')
    ln("")

    for nid, key, label in REGULATIONS:
        ln(f'    {nid}["Regulation\\n{key}\\n{label}"]:::shared')
    ln("")

    for nid, key, label in RISK_DRIVERS:
        ln(f'    {nid}["RiskDriver\\n{key}\\n{label}"]:::riskNode')
    ln("")

    for nid, key, label in RISK_CONSEQUENCES:
        ln(f'    {nid}["RiskConsequence\\n{key}\\n{label}"]:::riskNode')
    ln("")

    for nid, key, label in MACRO_FACTORS:
        ln(f'    {nid}["MacroFactor\\n{key}\\n{label}"]:::mdaNode')
    ln("")

    # ── Level 3: Company-specific entities ───────────────────────────────────
    ln("    %% ═══════════════════════════════════════════════════════════")
    ln("    %% LEVEL 3 — Filing-specific extracted entities")
    ln("    %% ═══════════════════════════════════════════════════════════")

    for cid, _, _, _ in COMPANIES:
        entities = BUSINESS_ENTITIES[cid]
        ln(f"    %% -- {cid} Business Description entities --")

        for pid, name in entities["products"]:
            ln(f'    {pid}["Product | {name}"]:::biz')
            ln(f"    {cid} -->|OFFERS| {pid}")

        for sid, name in entities["segments"]:
            ln(f'    {sid}["BusinessSegment | {name}"]:::biz')
            ln(f"    {cid} -->|HAS_SEGMENT| {sid}")

        for comp_id, comp_name in entities["competitors"]:
            # Competitor nodes may be shared (e.g. Alphabet appears for both AAPL and MSFT)
            if f'    {comp_id}["Competitor' not in "\n".join(lines):
                ln(f'    {comp_id}["Competitor | {comp_name}"]:::shared')
            ln(f"    {cid} -->|COMPETES_WITH| {comp_id}")

        # Geo + customer + regulation edges (sampled)
        for geo_id, _, _ in GEO_MARKETS[:2]:
            ln(f"    {cid} -->|OPERATES_IN| {geo_id}")
        ln(f"    {cid} -->|TARGETS| CS_CONSUMER")
        ln(f"    {cid} -->|SUBJECT_TO| REG_GDPR")
        ln("")

        # Risk Factor entities
        ln(f"    %% -- {cid} Risk Factor entities --")
        for rf_id, rf_label, drivers, consequences in RISK_FACTORS[cid]:
            ln(f'    {rf_id}["RiskFactor\\n{rf_label}"]:::riskNode')
            ln(f"    {cid} -->|HAS_RISK| {rf_id}")
            for drv in drivers:
                ln(f"    {rf_id} -->|CAUSED_BY| {drv}")
            for rc in consequences:
                ln(f"    {rf_id} -->|MAY_RESULT_IN| {rc}")
        ln("")

        # MD&A entities
        ln(f"    %% -- {cid} MD&A entities --")
        for fm_id, fm_label, macro_id in FINANCIAL_METRICS[cid]:
            ln(f'    {fm_id}["FinancialMetric\\n{fm_label}"]:::mdaNode')
            ln(f"    {cid} -->|REPORTS| {fm_id}")
            if macro_id:
                ln(f"    {fm_id} -->|IMPACTED_BY| {macro_id}")

        for mo_id, mo_text, fm_ref in MANAGEMENT_OUTLOOKS[cid]:
            ln(f'    {mo_id}["ManagementOutlook\\n{mo_text}"]:::mdaNode')
            ln(f"    {cid} -->|HAS_OUTLOOK| {mo_id}")
            ln(f"    {mo_id} -->|REFERENCES| {fm_ref}")
        ln("")

    # ── Cross-section edges (reserved / planned) ──────────────────────────────
    if show_cross_section:
        ln("    %% ═══════════════════════════════════════════════════════════")
        ln("    %% CROSS-SECTION edges (reserved — not yet built)")
        ln("    %% Dashed arrows show planned linkages")
        ln("    %% ═══════════════════════════════════════════════════════════")
        cross_section_edges = [
            # RiskFactor → AFFECTS → BusinessSegment
            ("RF_AAPL_SUPPLY", "SEG_AAPL_PRODUCTS",  "AFFECTS"),
            ("RF_MSFT_CLOUD",  "SEG_MSFT_CLOUD",     "AFFECTS"),
            ("RF_TSLA_SUPPLY", "SEG_TSLA_AUTO",      "AFFECTS"),
            # RiskFactor → MATERIALISED_AS → FinancialMetric
            ("RF_AAPL_SUPPLY", "FM_AAPL_MARGIN",     "MATERIALISED_AS"),
            ("RF_TSLA_DEMAND", "FM_TSLA_AUTO",       "MATERIALISED_AS"),
            # MacroFactor → CITED_IN → RiskFactor
            ("MACRO_RATES",    "RF_TSLA_DEMAND",     "CITED_IN"),
            ("MACRO_FX",       "RF_AAPL_SUPPLY",     "CITED_IN"),
        ]
        for src, tgt, rel in cross_section_edges:
            ln(f"    {src} -.->|\"{rel}\"| {tgt}")
        ln("")

    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate Mermaid diagram for SEC KG")
    parser.add_argument(
        "--no-cross-section",
        action="store_true",
        help="Omit the reserved cross-section edges",
    )
    parser.add_argument(
        "--output",
        default="-",
        help="Output file path (default: stdout)",
    )
    args = parser.parse_args()

    diagram = build_mermaid(show_cross_section=not args.no_cross_section)

    if args.output == "-":
        print(diagram)
    else:
        with open(args.output, "w") as f:
            f.write(diagram)
        print(f"Diagram written to {args.output}")
