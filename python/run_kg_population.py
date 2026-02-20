"""
Run the KG population pipeline.

Usage:
    # Dry run (no Neo4j) — good for first test
    python python/run_kg_population.py --dry-run --section risk_factors --limit 1

    # Apply Neo4j schema (run once before first real run)
    python python/run_kg_population.py --apply-schema

    # Full run
    python python/run_kg_population.py --section risk_factors
    python python/run_kg_population.py   # all sections
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from models.schemas import SectionType
from kg_population.pipeline import KGPopulationPipeline


def main():
    parser = argparse.ArgumentParser(description="KG population pipeline")
    parser.add_argument("--dry-run", action="store_true",
                        help="Extract and normalise but skip Neo4j writes")
    parser.add_argument("--apply-schema", action="store_true",
                        help="Apply Neo4j constraints/indexes then exit")
    parser.add_argument("--section", choices=["business", "risk_factors", "mda"],
                        default=None, help="Process only one section type")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max documents to process (useful for testing)")
    parser.add_argument("--fast", action="store_true",
                        help="Use spaCy NER instead of LLM (no GPU/API needed)")
    args = parser.parse_args()

    with KGPopulationPipeline(dry_run=args.dry_run, fast_mode=args.fast) as pipe:
        if args.apply_schema:
            pipe.apply_schema()
            print("Schema applied.")
            return

        section_type = SectionType(args.section) if args.section else None
        results = pipe.run_all(section_type=section_type, limit=args.limit)

    total_nodes = sum(r["nodes"] for r in results)
    total_edges = sum(r["edges"] for r in results)
    print(f"\nDone. {len(results)} documents processed.")
    print(f"  Total nodes written: {total_nodes}")
    print(f"  Total edges written: {total_edges}")


if __name__ == "__main__":
    main()
