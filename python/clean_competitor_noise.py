"""
clean_competitor_noise.py

Two-pass cleanup of Competitor nodes that are spaCy NER false positives.

Pass 1 — Blocklist: delete by exact name, phrase, or pattern match.
Pass 2 — Singletons: delete all Competitor nodes mentioned by only 1 company
          (they can never contribute to cross-company analysis).

Usage:
    python3 python/clean_competitor_noise.py            # dry run — counts only, no deletes
    python3 python/clean_competitor_noise.py --execute  # apply deletions
    python3 python/clean_competitor_noise.py --pass1    # blocklist only
    python3 python/clean_competitor_noise.py --pass2    # singletons only
"""

import argparse
import re
import sys
from neo4j import GraphDatabase

NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "password"

# ---------------------------------------------------------------------------
# Blocklist
# ---------------------------------------------------------------------------

# Exact-match names (case-insensitive — stored uppercased, matched via name.upper())
EXACT_BLOCKLIST = {
    # Regulatory / standards bodies
    "SEC", "GAAP", "FASB", "IFRS", "IRS", "FINRA", "NYSE", "NASDAQ",
    "ASC", "ASU", "PCAOB", "AICPA", "CPA", "CFA",
    "NIST", "USPTO", "FCA", "EEA", "CPRA", "ACA", "HIPAA",
    "GDPR", "CCPA", "FCPA", "FCRA", "FDCPA", "ERISA",
    "OSHA", "EPA", "FDA", "FTC", "DOJ", "DOD", "HHS", "CMS",
    "FINRA", "OCC", "FDIC", "CFPB", "CFTC",
    # Government programs
    "MEDICARE", "MEDICAID",
    # Legal entity suffixes
    "LLC", "LP", "LLP", "LTD", "INC", "CORP", "CO", "PLC",
    "INC.", "L.P.", "L.L.C.", "N.A.",
    # Placeholder / null values
    "N/A", "NA", "UNRESOLVED", "UNKNOWN", "NONE", "N/A.", "TBD", "TBA",
    # Single letters and very short noise
    "K", "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "L", "M",
    "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z",
    "AI", "ML", "IP", "IT", "HR", "PR", "IR",
    # Geopolitical acronyms
    "EU", "US", "UK", "UN", "WHO", "WTO", "IMF", "GDP", "IPO",
    "G7", "G20", "NATO", "WEF",
    # Health/pandemic
    "COVID-19", "COVID", "SARS", "SARS-COV-2",
    # Financial metrics & ratios
    "EBITDA", "EBIT", "EPS", "ROE", "ROI", "ROA",
    "SG&A", "MD&A", "R&D", "CAPEX", "OPEX",
    "ADJUSTED EBITDA", "ADJUSTED EBIT",
    # Market indices
    "S&P", "S&P 500", "DOW", "DJIA", "NASDAQ", "RUSSELL 2000",
    # Generic document/form terms
    "ACT", "LAW", "CODE", "RULE", "FORM", "ITEM",
    # Generic business nouns (not specific companies)
    "COMPANY", "COMPANIES", "CORPORATION", "CORPORATIONS",
    "GROUP", "HOLDINGS", "PARTNERS", "VENTURES",
    "MANAGEMENT", "OPERATIONS", "SERVICES", "SOLUTIONS",
    "TECHNOLOGIES", "TECHNOLOGY", "SYSTEMS", "PRODUCTS",
    "INTERNATIONAL", "GLOBAL", "NATIONAL", "AMERICAN",
    # Common adjectives/nouns spaCy mistakes for ORGs
    "FAIR", "DIGITAL", "CORPORATE", "DIRECT", "MAXIMUM", "MINIMUM",
    "BRANCH", "STATE", "MARKET", "CAPITAL", "EQUITY", "CREDIT",
    "GROWTH", "RISK", "PERFORMANCE", "COMPLIANCE",
    # Job titles
    "CEO", "CFO", "COO", "CTO", "CIO", "CISO", "CSO", "CLO",
    "CHAIRMAN", "DIRECTOR", "OFFICER", "COUNSEL",
    # Common OCR / parse garbage
    "MILEST1", "N1THELESS", "NONETHELESS", "HOWEVER",
    # High-frequency false positives observed in graph data
    # Regulatory / financial acronyms (not company names)
    "ATM", "PPP", "GHG", "API", "IRB", "NOL", "OECD",
    "NDA", "EC", "EMA", "IND", "LIBOR", "SOFR", "OTC",
    "ETF", "REIT", "CDO", "CDS", "ABS", "MBS",
    "MLA", "APR", "MAPR", "TILA", "ECOA", "EFTA", "UDAAP",
    "FDCA", "NADA", "RFID", "EHR", "ICD", "NDS", "LPR",
    "COMP", "KYC", "AML", "BSA", "DORA", "NIM", "ROC",
    "HMDA", "ACH", "SWIFT", "IBAN",
    "OPEC", "IASB", "IASC", "AIFMD", "UCITS",
    "DSCR", "LTV", "DTI", "PMI", "HELOC",
    "ESG", "TCFD", "SASB", "CSR",
    "COGS", "WACC", "CAPM",
    "MANAGEMENT'S",
    # Round 2: observed in top-remaining noise
    "SBA", "GCP", "ERP", "SAB", "REMS", "HITECH", "OFAC",
    "TCJA", "DEFERRED", "HIPAA",
    # Round 3
    "VIE", "OEM", "IRA", "GMP", "OEM", "UNITS", "UNIT",
    "RECOGNITION", "OMICRON", "OMICRON VARIANT",
    # Generic single-word common nouns that spaCy labels ORG
    "SEGMENTS", "SEGMENT", "DIVISION", "DIVISIONS",
    "ASSETS", "LIABILITIES", "REVENUES", "EXPENSES",
    "EMPLOYEES", "CUSTOMERS", "SUPPLIERS", "VENDORS",
    "CONTRACTS", "AGREEMENTS", "STANDARDS", "GUIDELINES",
    "REGULATIONS", "REQUIREMENTS", "PROCEDURES",
    "PROPERTY", "EURO", "DOLLAR", "BANK",
    "SECURITY", "PRIVACY", "PROTECTION",
    "INFRASTRUCTURE", "PLATFORM", "NETWORK",
    "DATA", "INFORMATION", "CONTENT", "MEDIA",
}

# Substring / phrase matches (case-insensitive)
PHRASE_BLOCKLIST = [
    # Governance / committee boilerplate
    "board of directors",
    "general counsel",
    "audit committee",
    "compensation committee",
    "nominating committee",
    "governance committee",
    "risk committee",
    "beneficial owners",
    # Regulatory bodies (full names)
    "securities and exchange commission",
    "financial accounting standards board",
    "public company accounting oversight",
    "internal revenue service",
    "federal reserve",
    "department of justice",
    "department of defense",
    "department of health",
    "centers for medicare",
    "food and drug administration",
    "federal trade commission",
    "consumer financial protection",
    "office of the comptroller",
    "u.s. government",
    "u.s. congress",
    "u.s. senate",
    "u.s. house",
    # International bodies
    "european union",
    "european commission",
    "european economic area",
    "world health organization",
    "world trade organization",
    # Form/filing navigation
    "form s-3", "form s-1", "form s-4",
    "form 10-k", "form 10-q", "form 8-k", "form 4",
    "item 1a", "item 1b", "item 1", "item 2", "item 7",
    "annual report", "quarterly report", "proxy statement",
    "current reports",
    "cybersecurity risk management",
    "off-balance sheet",
    "independent registered public accounting",
    # Financial statement line items
    "note payable", "notes payable",
    "accounts receivable", "accounts payable",
    "income tax", "net income", "operating income",
    "gross profit", "total revenue", "total assets",
    "common stock", "preferred stock",
    "per share", "earnings per share",
    "net interest", "interest income", "interest expense",
    "capital resources", "capital expenditure",
    "financial instruments", "financial statements",
    "credit facility", "revolving credit",
    "adjusted ebitda", "adjusted ebit",
    "research and development",
    "selling, general",
    # Job titles
    "chief executive officer", "chief financial officer",
    "chief operating officer", "chief technology officer",
    "chief information officer", "chief legal officer",
    "president and ceo", "vice president",
    "general partner", "limited partner",
    "management's discussion", "management discussion",
    # Accounting / legal concepts
    "business combinations",
    "intellectual property",
    "anti kickback",
    "stark law",
    "affordable care act",
    "class a", "class b", "class c",
    # Generic / structural
    "stock compensation",
    "stock-based compensation",
    "fair value",
    # High-frequency patterns observed in graph
    "management's",
    "management discussion",
    "regulation s-k", "regulation s-x", "regulation a",
    "accounting standards",
    "generally accepted",
    "stock exchange",
    "supplement", "supplementary data",
    "controls and procedures",
    "operations of the",
    "branch operations",
    "direct loan",
    "greenhouse gas",
    "net operating loss",
    "the toronto stock", "the london stock", "the new york stock",
    # Round 2: patterns from remaining top noise
    "consolidated financial",
    "intangibles",
    "inter partes",
    "qui tam",
    "business conduct",
    "good delivery",
    "national association",
    "loan servicing",
    "deferred tax",
    "staff accounting",
    "risk evaluation",
    # Round 3
    "non-gaap",
    "information technology",
    "business combination",
    "initial public offering",
    "goodwill goodwill",
    "good manufacturing",
]

# Regex patterns matched against the full name
REGEX_BLOCKLIST = [
    re.compile(r'^[\$\#\@\"\'\`]'),       # starts with $, #, @, ", ', `
    re.compile(r'^\d'),                   # starts with a digit
    re.compile(r'^\W'),                   # starts with non-word char
    re.compile(r'\$\s*\d'),               # contains dollar + number
    re.compile(r'^\s*\d[\d,\.]+\s'),      # numeric table fragments
    re.compile(r'["\u201c\u201d]'),       # contains curly quotes
    re.compile(r'\.{3,}'),               # ellipsis-style truncation
    re.compile(r'^\s*$'),                 # blank or whitespace only
    re.compile(r'.{200,}'),              # absurdly long "names"
    # Possessive of a common noun (e.g. "Management's", "Company's")
    re.compile(r"^[A-Z][a-z]+'s$", re.IGNORECASE),
    # "the [Something] Exchange/Commission/Authority/Board/Bureau/Agency"
    re.compile(
        r'^[Tt]he\s.*(exchange|commission|authority|bureau|authority|agency|board)$',
        re.IGNORECASE,
    ),
    # Pure all-caps 2–3 chars that are clearly not company ticker/names
    # (already handled via EXACT_BLOCKLIST, but catch any remainders)
    re.compile(r'^[A-Z]{1,2}$'),          # 1 or 2 capital letters only
    # OCR/parse garbage: word characters mixed with digits mid-word (e.g. postp1, standal1, teleph1)
    re.compile(r'[a-z]\d[a-z]?$'),
    # Names longer than 120 chars — almost certainly a document excerpt, not a company
    re.compile(r'.{120,}', re.DOTALL),
]


def is_blocklisted(name: str) -> bool:
    upper = name.upper().strip()
    if upper in EXACT_BLOCKLIST:
        return True
    lower = name.lower().strip()
    for phrase in PHRASE_BLOCKLIST:
        if phrase in lower:
            return True
    for pattern in REGEX_BLOCKLIST:
        if pattern.search(name):
            return True
    return False


# ---------------------------------------------------------------------------
# Neo4j helpers
# ---------------------------------------------------------------------------

def get_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def count_competitors(driver) -> int:
    with driver.session() as s:
        return s.run("MATCH (c:Competitor) RETURN count(c) AS n").single()["n"]


def count_mentions_by_company(driver, name: str) -> int:
    with driver.session() as s:
        result = s.run(
            "MATCH (c:Competitor {name: $name})<-[:COMPETES_WITH]-(f) "
            "RETURN count(DISTINCT f) AS n",
            name=name,
        ).single()
        return result["n"] if result else 0


# ---------------------------------------------------------------------------
# Pass 1 — Blocklist pass
# ---------------------------------------------------------------------------

def pass1_blocklist(driver, execute: bool):
    print("\n=== Pass 1: Blocklist cleanup ===")

    # Stream all Competitor names in batches
    batch_size = 5000
    skip = 0
    to_delete = []

    print("Scanning competitor names...", flush=True)
    while True:
        with driver.session() as s:
            rows = s.run(
                "MATCH (c:Competitor) RETURN c.name AS name SKIP $skip LIMIT $limit",
                skip=skip, limit=batch_size,
            ).data()
        if not rows:
            break
        for row in rows:
            name = row["name"] or ""
            if is_blocklisted(name):
                to_delete.append(name)
        skip += batch_size
        print(f"  scanned {skip:,} so far, blocklisted {len(to_delete):,}", end="\r", flush=True)

    print(f"\nBlocklisted: {len(to_delete):,} names")

    if not execute:
        print("(dry run — skipping deletion)")
        return len(to_delete)

    # Delete in batches of 1000
    deleted = 0
    chunk_size = 1000
    for i in range(0, len(to_delete), chunk_size):
        chunk = to_delete[i : i + chunk_size]
        with driver.session() as s:
            result = s.run(
                "UNWIND $names AS n "
                "MATCH (c:Competitor {name: n}) "
                "DETACH DELETE c "
                "RETURN count(c) AS deleted",
                names=chunk,
            ).single()
            deleted += result["deleted"] if result else 0
        print(f"  deleted {deleted:,} so far...", end="\r", flush=True)

    print(f"\nPass 1 done: deleted {deleted:,} nodes")
    return deleted


# ---------------------------------------------------------------------------
# Pass 2 — Singleton pass
# ---------------------------------------------------------------------------

def pass2_singletons(driver, execute: bool):
    print("\n=== Pass 2: Singleton cleanup ===")

    with driver.session() as s:
        count = s.run(
            "MATCH (c:Competitor) "
            "OPTIONAL MATCH (comp:Company)-[:COMPETES_WITH]->(c) "
            "WITH c, count(DISTINCT comp) AS n "
            "WHERE n <= 1 "
            "RETURN count(c) AS total"
        ).single()["total"]

    print(f"Singleton Competitor nodes (mentioned by ≤1 company): {count:,}")

    if not execute:
        print("(dry run — skipping deletion)")
        return count

    # Delete in batches to avoid OOM on large graphs
    total_deleted = 0
    batch = 10_000
    while True:
        with driver.session() as s:
            result = s.run(
                "MATCH (c:Competitor) "
                "OPTIONAL MATCH (comp:Company)-[:COMPETES_WITH]->(c) "
                "WITH c, count(DISTINCT comp) AS n "
                "WHERE n <= 1 "
                "WITH c LIMIT $batch "
                "DETACH DELETE c "
                "RETURN count(c) AS deleted",
                batch=batch,
            ).single()
            n = result["deleted"] if result else 0
        total_deleted += n
        print(f"  deleted {total_deleted:,} so far...", end="\r", flush=True)
        if n == 0:
            break

    print(f"\nPass 2 done: deleted {total_deleted:,} singleton nodes")
    return total_deleted


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Clean Competitor NER noise from Neo4j")
    parser.add_argument("--execute", action="store_true", help="Apply deletions (default: dry run)")
    parser.add_argument("--pass1", action="store_true", help="Run blocklist pass only")
    parser.add_argument("--pass2", action="store_true", help="Run singleton pass only")
    args = parser.parse_args()

    run_pass1 = args.pass1 or (not args.pass1 and not args.pass2)
    run_pass2 = args.pass2 or (not args.pass1 and not args.pass2)

    driver = get_driver()

    before = count_competitors(driver)
    print(f"Competitor nodes before: {before:,}")
    if not args.execute:
        print("DRY RUN — pass --execute to apply changes\n")

    p1_count = 0
    p2_count = 0

    if run_pass1:
        p1_count = pass1_blocklist(driver, args.execute)
    if run_pass2:
        p2_count = pass2_singletons(driver, args.execute)

    if args.execute:
        after = count_competitors(driver)
        print(f"\nCompetitor nodes after:  {after:,}")
        print(f"Total removed:           {before - after:,} ({100*(before-after)/before:.1f}%)")
    else:
        print(f"\nEstimated removals: {p1_count + p2_count:,} (pass1={p1_count:,}, pass2={p2_count:,})")
        print("Run with --execute to apply.")

    driver.close()


if __name__ == "__main__":
    main()
