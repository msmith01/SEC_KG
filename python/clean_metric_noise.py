"""
Clean noisy FinancialMetric nodes from the knowledge graph.

The spaCy NER extractor populates FinancialMetric.name with sentence fragments
rather than actual metric names (e.g. "an increase of", "offset by a").
This script removes those noise nodes in bulk.

Usage:
    python3 python/clean_metric_noise.py --dry-run   # preview counts
    python3 python/clean_metric_noise.py             # execute deletions
"""
from __future__ import annotations

import argparse
import re
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
import config
from neo4j import GraphDatabase


# ── Noise patterns ────────────────────────────────────────────────────────────

# Names that start with these words are sentence fragments, not metric names.
NOISE_PREFIXES = [
    "an ", "a ", "the ", "of ", "as ", "due to", "primarily", "partially",
    "offset", "compared", "million", "billion", "approximately", "including",
    "net of", "in addition", "together with", "in connection", "pursuant to",
    "representing", "consisting", "resulting", "relating", "reflecting",
    "certain", "various", "other ", "these ", "those ", "which ", "such ",
    "this ", "its ", "our ", "their ", "all ", "no ", "any ", "each ",
]

# Names that end with these words are fragments trailing off.
NOISE_SUFFIXES = [
    " of", " by", " to", " a", " an", " the", " was", " were", " is", " are",
    " in", " and", " or", " for", " on", " at", " from", " with", " as",
    " than", " that", " which", " including", " approximately", " million",
    " billion", " thousand",
]

# Regex patterns for clear noise.
NOISE_REGEX = [
    r"^\d",                         # starts with a digit
    r"^[a-z]",                      # starts with lowercase (sentence mid-fragment)
    r"\bactivities (was|were|of)\b",  # cash flow fragments
    r"^(increase|decrease|change) (of|in)\b",
    r"\bcompared to\b",
    r"\boffset by\b",
    r"\bprimarily (due|driven|related)\b",
    r"^(total|aggregate) (of|amount)\b",
    r"\d+\s*(million|billion|thousand)",  # raw dollar amounts in the name
]

_COMPILED_REGEX = [re.compile(p, re.IGNORECASE) for p in NOISE_REGEX]


def _is_noise(name: str) -> bool:
    n = name.strip()
    if not n:
        return True
    if len(n) <= 3:
        return True
    nl = n.lower()
    for prefix in NOISE_PREFIXES:
        if nl.startswith(prefix):
            return True
    for suffix in NOISE_SUFFIXES:
        if nl.endswith(suffix):
            return True
    for pattern in _COMPILED_REGEX:
        if pattern.search(n):
            return True
    return False


def audit(driver) -> dict[str, int]:
    """Sample top metric names and count how many would be deleted."""
    with driver.session(database=config.NEO4J_DATABASE) as s:
        total = s.run("MATCH (n:FinancialMetric) RETURN count(n) AS c").single()["c"]
        rows = s.run(
            "MATCH (n:FinancialMetric) RETURN n.name AS name, count(*) AS cnt "
            "ORDER BY cnt DESC LIMIT 200"
        )
        names = [(r["name"], r["cnt"]) for r in rows]

    noise = [(n, c) for n, c in names if _is_noise(n)]
    clean = [(n, c) for n, c in names if not _is_noise(n)]

    print(f"\nTotal FinancialMetric nodes: {total:,}")
    print(f"\nTop noise names (would delete):")
    for name, cnt in noise[:20]:
        print(f"  {cnt:>8,}  {name!r}")
    print(f"\nTop clean names (would keep):")
    for name, cnt in clean[:20]:
        print(f"  {cnt:>8,}  {name!r}")
    return {"total": total, "noise_sample": len(noise), "clean_sample": len(clean)}


def execute(driver, batch_size: int = 10_000) -> int:
    """Delete noise nodes in batches. Returns total deleted."""
    total_deleted = 0

    with driver.session(database=config.NEO4J_DATABASE) as s:
        # Build a single Cypher filter from all patterns
        # We'll pull names and delete in Python-side batches to avoid timeout
        while True:
            result = s.run(
                "MATCH (n:FinancialMetric) "
                "WHERE NOT n.name IS NULL "
                "RETURN n.name AS name, n.node_id AS nid "
                "LIMIT $limit",
                limit=batch_size * 5,
            )
            rows = [(r["name"], r["nid"]) for r in result]
            if not rows:
                break

            noise_ids = [nid for name, nid in rows if _is_noise(name)]
            if not noise_ids:
                # No more noise in this batch — we might have processed all
                # Check if there are any left to scan
                remaining = s.run(
                    "MATCH (n:FinancialMetric) RETURN count(n) AS c"
                ).single()["c"]
                print(f"  Scanned batch, 0 noise found. Remaining: {remaining:,}")
                break

            deleted = s.run(
                "MATCH (n:FinancialMetric) WHERE n.node_id IN $ids "
                "DETACH DELETE n RETURN count(n) AS c",
                ids=noise_ids,
            ).single()["c"]
            total_deleted += deleted
            print(f"  Deleted {deleted:,} (running total: {total_deleted:,})")

    return total_deleted


def delete_all(driver, batch_size: int = 50_000) -> int:
    """Delete ALL FinancialMetric nodes in batches (used when audit shows 100% noise)."""
    total_deleted = 0
    with driver.session(database=config.NEO4J_DATABASE) as s:
        while True:
            result = s.run(
                "MATCH (n:FinancialMetric) "
                "WITH n LIMIT $limit "
                "DETACH DELETE n "
                "RETURN count(n) AS c",
                limit=batch_size,
            )
            deleted = result.single()["c"]
            if deleted == 0:
                break
            total_deleted += deleted
            print(f"  Deleted {deleted:,} (running total: {total_deleted:,})")
    return total_deleted


def main():
    parser = argparse.ArgumentParser(description="Clean noisy FinancialMetric nodes")
    parser.add_argument("--dry-run", action="store_true", help="Audit only, no deletions")
    parser.add_argument("--all",  action="store_true",
                        help="Delete ALL FinancialMetric nodes (use when 100%% are noise)")
    parser.add_argument("--batch-size", type=int, default=10_000)
    args = parser.parse_args()

    driver = GraphDatabase.driver(
        config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD)
    )

    audit(driver)

    if not args.dry_run:
        if args.all:
            print("\nDeleting ALL FinancialMetric nodes...")
            total = delete_all(driver, batch_size=50_000)
        else:
            print("\nExecuting pattern-based deletions...")
            total = execute(driver, batch_size=args.batch_size)
        with driver.session(database=config.NEO4J_DATABASE) as s:
            remaining = s.run(
                "MATCH (n:FinancialMetric) RETURN count(n) AS c"
            ).single()["c"]
        print(f"\nDone. Deleted {total:,} nodes. Remaining: {remaining:,}")

    driver.close()


if __name__ == "__main__":
    main()
