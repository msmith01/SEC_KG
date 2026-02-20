"""
Run the full preprocessing pipeline over all extracted R files.

Usage:
    python python/run_preprocessing.py
    python python/run_preprocessing.py --overwrite
    python python/run_preprocessing.py --section risk_factors
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from preprocessing.pipeline import PreprocessingPipeline
from models.schemas import SectionType


def main():
    parser = argparse.ArgumentParser(description="SEC preprocessing pipeline")
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Re-process files even if JSON output already exists"
    )
    parser.add_argument(
        "--section", choices=["business", "risk_factors", "mda"],
        default=None,
        help="Process only one section type (default: all three)"
    )
    args = parser.parse_args()

    pp = PreprocessingPipeline()

    if args.section:
        section_type = SectionType(args.section)
        dirs = {
            SectionType.RISK_FACTORS: pp.SECTION_MAP.get(
                next(k for k, v in pp.SECTION_MAP.items() if v == SectionType.RISK_FACTORS)
            ),
        }
        directory = next(
            k for k, v in pp.SECTION_MAP.items() if v == section_type
        )
        docs = pp.run_directory(directory, section_type, overwrite=args.overwrite)
        print(f"\nDone. {len(docs)} documents written.")
    else:
        counts = pp.run_all(overwrite=args.overwrite)
        total = sum(counts.values())
        print(f"\nDone. Total documents written: {total}")
        for section, n in counts.items():
            print(f"  {section}: {n}")


if __name__ == "__main__":
    main()
