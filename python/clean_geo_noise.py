"""
clean_geo_noise.py

Two-pass cleanup of GeographicMarket nodes from spaCy NER false positives.

Pass 1 — Merge aliases: redirect OPERATES_IN edges from known alias nodes
          to their canonical form, then delete the alias.
Pass 2 — Delete garbage: remove nodes whose names are clearly not geographic
          (short garbage codes, currency symbols, quarter labels, etc.)
          using a whitelist of valid 2/3-letter geographic codes.

Usage:
    python3 python/clean_geo_noise.py              # dry run
    python3 python/clean_geo_noise.py --execute    # apply all changes
    python3 python/clean_geo_noise.py --pass1      # alias merging only
    python3 python/clean_geo_noise.py --pass2      # garbage deletion only
"""
from __future__ import annotations

import argparse
import re
import sys
from neo4j import GraphDatabase

NEO4J_URI      = "bolt://localhost:7687"
NEO4J_USER     = "neo4j"
NEO4J_PASSWORD = "password"

# ── Pass 1: alias → canonical mapping ────────────────────────────────────────
# Each entry: alias_name → canonical_name
# The canonical node must already exist in the graph.
# Edges are re-pointed from alias → canonical, then alias deleted.
ALIAS_MAP: dict[str, str] = {
    # United States — canonical is "the United States" (most common in graph)
    "U.S.":                     "the United States",
    "U.S":                      "the United States",
    "US":                       "the United States",
    "USA":                      "the United States",
    "United States":            "the United States",
    "United States of America": "the United States",
    # United Kingdom — canonical is "UK" (most common in graph)
    "U.K.":        "UK",
    "U.K":         "UK",
    "Great Britain": "UK",
    "United Kingdom": "UK",
    # European Union — canonical is "EU" (most common short form)
    "E.U.":            "EU",
    "European Union":  "EU",
    # China — canonical is "China"
    "PRC":             "China",
    "People's Republic of China": "China",
    # California — canonical is "California"
    "CA":              "California",
}

# ── Pass 2: whitelist of valid geographic abbreviations ──────────────────────
# Short names (≤ 3 chars) in this set are KEPT. Everything else ≤ 3 chars deleted.
GEO_WHITELIST = {
    # US state postal codes
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC", "PR", "GU", "VI",
    # Common country / territory codes used in SEC filings
    "UK", "EU", "UAE", "NZ", "HK", "SG", "JP", "KR",
    "AU", "DE", "FR", "CH", "NL", "SE", "NO", "FI", "DK",
    "BE", "IT", "ES", "PT", "PL", "CZ", "AT", "GR", "TR",
    "IL", "ZA", "NG", "EG", "AE",
    # Canadian provinces
    "BC", "ON", "QC", "AB", "MB", "SK", "NS", "NB", "NL", "PE",
    # Australian states
    "NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT",
    # Other valid 3-letter geographic codes seen in filings
    "NYC", "DFW", "LAX", "SFO", "BOS",     # major cities
    "KSA",                                   # Kingdom of Saudi Arabia
    "GBP", "EUR", "JPY", "CNY",             # keep? these are currencies...
    # Note: currency codes above are borderline — they ARE geographic in context
    # but noisy. Excluded from whitelist — will be deleted.
}

# Remove currency codes from whitelist (we want to delete these)
_CURRENCY_CODES = {"GBP", "EUR", "JPY", "CNY", "USD", "CHF", "AUD", "CAD",
                   "MXN", "BRL", "INR", "KRW", "HKD", "SGD", "NOK", "SEK",
                   "DKK", "CZK", "PLN", "HUF", "RON", "BGN", "HRK", "RSD",
                   "TRY", "ILS", "ZAR", "AED", "SAR", "QAR", "KWD", "BHD",
                   "RUB", "UAH", "GEL", "AMD", "AZN", "KZT", "UZS",
                   "MYR", "IDR", "PHP", "THB", "VND", "PKR", "BDT",
                   "EGP", "NGN", "GHS", "KES", "ETB", "XOF", "XAF",
                   "SEK", "NZD", "TWD", "CLP", "COP", "PEN", "ARS",
                   "UYU", "BOB", "PYG", "VEF", "GTQ", "HNL", "NIO",
                   "CRC", "PAB", "DOP", "JMD", "TTD", "BBD", "XCD",
                   "HTG", "CUP", "BSD", "BZD", "AWG", "KYD",
                   "EUR", "MXN", "CNY"}
GEO_WHITELIST -= _CURRENCY_CODES

# Phrase patterns that disqualify a name regardless of length
NON_GEO_PHRASES = [
    "non-u.s.", "non-us", "non u.s", "non-u.s",
    "non-domestic", "non-domestic", "ex-u.s",
    "u.s. federal", "u.s. state",
    "quarter", " q1 ", " q2 ", " q3 ", " q4 ",
    "segment", "division", "operations",
    "non-gaap", "stock exchange",
    "reporting unit",
]

# Regex for names that are clearly not geographic
NON_GEO_REGEX = [
    re.compile(r'^\d'),                          # starts with digit
    re.compile(r'^\W'),                          # starts with non-word char (., -, +, %)
    re.compile(r'\$\s*\d'),                      # dollar + number
    re.compile(r'\.{2,}'),                       # multiple dots
    re.compile(r'^\s*$'),                        # blank
    re.compile(r'.{150,}', re.DOTALL),           # absurdly long
    re.compile(r'^Q[1-4]$', re.IGNORECASE),     # quarter labels (Q1, Q2, Q3, Q4)
    re.compile(r'\d{3,}'),                       # 3+ consecutive digits
    re.compile(r'[a-z]\d[a-z]', re.IGNORECASE), # OCR garbage (postp1, standal1)
]


def _is_garbage(name: str) -> bool:
    """Return True if this short-named geo node should be deleted."""
    stripped = name.strip()
    upper = stripped.upper()

    # If it's in the whitelist it's fine
    if upper in GEO_WHITELIST:
        return False

    # If it matches a non-geo phrase
    lower = stripped.lower()
    for phrase in NON_GEO_PHRASES:
        if phrase in lower:
            return True

    # Regex checks
    for pattern in NON_GEO_REGEX:
        if pattern.search(stripped):
            return True

    # Short names (≤ 3 chars) not in whitelist are almost always garbage
    if len(stripped) <= 3:
        return True

    return False


def get_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def count_geo(driver) -> int:
    with driver.session() as s:
        return s.run("MATCH (g:GeographicMarket) RETURN count(g) AS n").single()["n"]


# ── Pass 1: merge aliases ─────────────────────────────────────────────────────

def pass1_merge_aliases(driver, execute: bool) -> int:
    print("\n=== Pass 1: Alias merging ===")
    merged = 0

    for alias, canonical in ALIAS_MAP.items():
        # Check if the alias exists
        with driver.session() as s:
            alias_exists = s.run(
                "MATCH (g:GeographicMarket {name: $name}) RETURN count(g) AS n",
                name=alias,
            ).single()["n"]

        if alias_exists == 0:
            continue

        # Check if canonical exists
        with driver.session() as s:
            canon_exists = s.run(
                "MATCH (g:GeographicMarket {name: $name}) RETURN count(g) AS n",
                name=canonical,
            ).single()["n"]

        if canon_exists == 0:
            print(f"  SKIP  '{alias}' → '{canonical}' (canonical not in graph)")
            continue

        # Count edges to redirect
        with driver.session() as s:
            edge_count = s.run(
                "MATCH (src)-[:OPERATES_IN]->(g:GeographicMarket {name: $name}) "
                "RETURN count(src) AS n",
                name=alias,
            ).single()["n"]

        print(f"  MERGE '{alias}' ({edge_count} edges) → '{canonical}'", end="")

        if not execute:
            print(" (dry run)")
            merged += 1
            continue

        # Re-point edges: for each source node pointing to alias,
        # create edge to canonical (if not already exists), then delete alias.
        with driver.session() as s:
            s.run(
                "MATCH (src)-[:OPERATES_IN]->(alias:GeographicMarket {name: $alias}) "
                "MATCH (canon:GeographicMarket {name: $canonical}) "
                "MERGE (src)-[:OPERATES_IN]->(canon)",
                alias=alias, canonical=canonical,
            )
            s.run(
                "MATCH (g:GeographicMarket {name: $name}) DETACH DELETE g",
                name=alias,
            )
        print(f" done")
        merged += 1

    print(f"Pass 1 done: {'would merge' if not execute else 'merged'} {merged} alias nodes")
    return merged


# ── Pass 2: delete garbage ────────────────────────────────────────────────────

def pass2_delete_garbage(driver, execute: bool) -> int:
    print("\n=== Pass 2: Garbage deletion ===")

    batch_size = 5000
    skip = 0
    to_delete: list[str] = []

    print("Scanning GeographicMarket names...", flush=True)
    while True:
        with driver.session() as s:
            rows = s.run(
                "MATCH (g:GeographicMarket) RETURN g.name AS name "
                "SKIP $skip LIMIT $limit",
                skip=skip, limit=batch_size,
            ).data()
        if not rows:
            break
        for row in rows:
            name = row["name"] or ""
            if _is_garbage(name):
                to_delete.append(name)
        skip += batch_size
        print(f"  scanned {skip:,}, flagged {len(to_delete):,}", end="\r", flush=True)

    print(f"\nFlagged for deletion: {len(to_delete):,}")

    if not execute:
        print("(dry run — skipping deletion)")
        # Print sample
        print("Sample flagged names:")
        for n in sorted(to_delete, key=len)[:30]:
            print(f"  {n!r}")
        return len(to_delete)

    deleted = 0
    chunk = 1000
    for i in range(0, len(to_delete), chunk):
        batch = to_delete[i:i + chunk]
        with driver.session() as s:
            result = s.run(
                "UNWIND $names AS n "
                "MATCH (g:GeographicMarket {name: n}) "
                "DETACH DELETE g "
                "RETURN count(g) AS deleted",
                names=batch,
            ).single()
            deleted += result["deleted"] if result else 0
        print(f"  deleted {deleted:,} so far...", end="\r", flush=True)

    print(f"\nPass 2 done: deleted {deleted:,} garbage nodes")
    return deleted


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Clean GeographicMarket NER noise")
    parser.add_argument("--execute", action="store_true", help="Apply changes (default: dry run)")
    parser.add_argument("--pass1",   action="store_true", help="Alias merging only")
    parser.add_argument("--pass2",   action="store_true", help="Garbage deletion only")
    args = parser.parse_args()

    run_p1 = args.pass1 or (not args.pass1 and not args.pass2)
    run_p2 = args.pass2 or (not args.pass1 and not args.pass2)

    driver = get_driver()
    before = count_geo(driver)
    print(f"GeographicMarket nodes before: {before:,}")
    if not args.execute:
        print("DRY RUN — pass --execute to apply\n")

    p1 = p2 = 0
    if run_p1:
        p1 = pass1_merge_aliases(driver, args.execute)
    if run_p2:
        p2 = pass2_delete_garbage(driver, args.execute)

    if args.execute:
        after = count_geo(driver)
        print(f"\nGeographicMarket nodes after:  {after:,}")
        print(f"Total removed:                 {before - after:,}")
    else:
        print(f"\nEstimated: {p1} merges + {p2} deletions")
        print("Run with --execute to apply.")

    driver.close()


if __name__ == "__main__":
    main()
