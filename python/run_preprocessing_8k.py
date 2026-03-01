"""
K-6: Run 8-K preprocessing pipeline.

Reads raw EDGAR 8-K text files from edgar_8K/<year>/ and produces
SectionDocument JSON in python/data/preprocessed/8k/.

Usage:
    python3 python/run_preprocessing_8k.py                  # all years
    python3 python/run_preprocessing_8k.py --year 2023      # one year
    python3 python/run_preprocessing_8k.py --year 2022 2023 # multiple years
    python3 python/run_preprocessing_8k.py --overwrite      # reprocess existing
    python3 python/run_preprocessing_8k.py --limit 50       # first N files per year
    python3 python/run_preprocessing_8k.py --dry-run        # count files, no output
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
import config
from preprocessing.pipeline_8k import EightKPipeline


def main():
    parser = argparse.ArgumentParser(description="8-K preprocessing pipeline (K-6)")
    parser.add_argument("--year",      nargs="+", type=int, help="Year(s) to process")
    parser.add_argument("--overwrite", action="store_true",  help="Reprocess existing files")
    parser.add_argument("--limit",     type=int, default=0,  help="Max files per year (0 = all)")
    parser.add_argument("--dry-run",   action="store_true",  help="Count files only, no output")
    args = parser.parse_args()

    if args.dry_run:
        root = config.EDGAR_8K_DIR
        if not root.exists():
            print(f"edgar_8K/ not found at {root}")
            return
        years = args.year or sorted(
            int(d.name) for d in root.iterdir() if d.is_dir() and d.name.isdigit()
        )
        total = 0
        for year in years:
            n = len(list((root / str(year)).glob("*.txt"))) if (root / str(year)).exists() else 0
            print(f"  {year}: {n:,} .txt files")
            total += n
        print(f"Total: {total:,} files")
        return

    pipe = EightKPipeline()

    if args.year:
        results = {}
        for year in args.year:
            results[year] = pipe.run_year(year, overwrite=args.overwrite, limit=args.limit)
    else:
        results = pipe.run_all(overwrite=args.overwrite, limit=args.limit)

    total = sum(results.values())
    print(f"\nDone. Total new documents processed: {total:,}")
    for year, count in sorted(results.items()):
        print(f"  {year}: {count:,}")


if __name__ == "__main__":
    main()
