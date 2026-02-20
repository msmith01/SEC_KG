#!/usr/bin/env bash
# =============================================================================
# run_all_years.sh
#
# Outer loop: runs parallel collection for every fiscal year 1993 → current.
# Each year runs sequentially (not all years in parallel) to stay within
# EDGAR's rate limits and not overwhelm the machine.
#
# Prerequisites:
#   1. Run get_historical_master.R once to download all quarterly indexes
#   2. This script calls run_parallel_collection.sh for each year
#
# Usage:
#   bash run_all_years.sh                        # 1993 → current year, 4 workers
#   bash run_all_years.sh 2010                   # 2010 → current year
#   bash run_all_years.sh 2010 2020              # 2010–2020 only
#   bash run_all_years.sh 1993 2024 8            # 8 workers per year
#
# Logs: logs/collection_<year>_worker_N.log (one set per year)
# =============================================================================

START_YEAR=${1:-1993}
END_YEAR=${2:-$(date +%Y)}
WORKERS=${3:-4}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "================================================================"
echo " SEC 10-K collection: years $START_YEAR – $END_YEAR, $WORKERS workers/year"
echo "================================================================"
echo ""

YEARS_DONE=0
YEARS_FAILED=0

for (( year=START_YEAR; year<=END_YEAR; year++ )); do
    echo "──────────────────────────────────────────"
    echo " Starting year $year"
    echo "──────────────────────────────────────────"

    bash "$SCRIPT_DIR/run_parallel_collection.sh" "$year" "$WORKERS"
    STATUS=$?

    if [ $STATUS -eq 0 ]; then
        YEARS_DONE=$(( YEARS_DONE + 1 ))
        echo "  Year $year complete."
    else
        YEARS_FAILED=$(( YEARS_FAILED + 1 ))
        echo "  Year $year had errors — check logs."
    fi

    echo ""
done

echo "================================================================"
echo " All years processed."
echo "   Successful: $YEARS_DONE"
echo "   With errors: $YEARS_FAILED"
echo ""
echo " File counts by section:"
for section in edgar_RiskFactors edgar_BusinDescr edgar_MgmtDisc; do
    total=$(find "$SCRIPT_DIR/$section" -name "*.txt" 2>/dev/null | wc -l)
    echo "   $section: $total files"
done
echo "================================================================"
