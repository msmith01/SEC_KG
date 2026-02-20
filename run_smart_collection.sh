#!/usr/bin/env bash
# =============================================================================
# run_smart_collection.sh
#
# Uses all available CPU cores by running multiple years in parallel.
# Default: 4 concurrent years × 6 workers each = 24 total R processes.
#
# Years run newest-first (most valuable data collected first).
# Each year is resumable — already-collected companies are skipped.
#
# Usage:
#   bash run_smart_collection.sh                      # 1993–2024, 4 years×6 workers
#   bash run_smart_collection.sh 2010 2024            # specific range
#   bash run_smart_collection.sh 1993 2024 4 8        # 4 concurrent years, 8 workers each
#
# Logs: logs/collection_<year>_worker_N.log
# =============================================================================

START_YEAR=${1:-1993}
END_YEAR=${2:-2024}
CONCURRENT_YEARS=${3:-4}       # how many years run at the same time
WORKERS_PER_YEAR=${4:-6}       # R workers per year
TOTAL_WORKERS=$(( CONCURRENT_YEARS * WORKERS_PER_YEAR ))

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

echo "================================================================"
echo " SEC 10-K Smart Collection"
echo " Years:            $START_YEAR – $END_YEAR (newest first)"
echo " Concurrent years: $CONCURRENT_YEARS"
echo " Workers/year:     $WORKERS_PER_YEAR"
echo " Total R workers:  $TOTAL_WORKERS"
echo "================================================================"
echo ""

# Build list of years newest-first
YEARS=()
for (( y=END_YEAR; y>=START_YEAR; y-- )); do
    YEARS+=($y)
done

# Process years in batches of CONCURRENT_YEARS
TOTAL_YEARS=${#YEARS[@]}
BATCH_NUM=0

for (( i=0; i<TOTAL_YEARS; i+=CONCURRENT_YEARS )); do
    BATCH_NUM=$(( BATCH_NUM + 1 ))
    BATCH_YEARS=("${YEARS[@]:$i:$CONCURRENT_YEARS}")

    echo "──────────────────────────────────────────────────────────────"
    echo " Batch $BATCH_NUM: years ${BATCH_YEARS[*]}"
    echo "──────────────────────────────────────────────────────────────"

    BATCH_PIDS=()

    for year in "${BATCH_YEARS[@]}"; do
        LOG_STEM="$LOG_DIR/collection_${year}"

        echo " Starting $year ($WORKERS_PER_YEAR workers)..."

        # Launch WORKERS_PER_YEAR parallel workers for this year
        YEAR_PIDS=()
        TOTAL_COMPANIES=5128
        CHUNK=$(( (TOTAL_COMPANIES + WORKERS_PER_YEAR - 1) / WORKERS_PER_YEAR ))

        for (( w=0; w<WORKERS_PER_YEAR; w++ )); do
            OFFSET=$(( w * CHUNK ))
            LOG="${LOG_STEM}_worker_${w}.log"

            Rscript "$SCRIPT_DIR/get_all_companies.R" \
                --year   "$year"   \
                --offset "$OFFSET" \
                --limit  "$CHUNK"  \
                > "$LOG" 2>&1 &

            YEAR_PIDS+=($!)
        done

        # Store all pids for this year
        BATCH_PIDS+=("${YEAR_PIDS[@]}")
        echo "   PIDs: ${YEAR_PIDS[*]}"
    done

    echo ""
    echo " Waiting for batch $BATCH_NUM to complete..."

    # Wait for all workers in this batch
    BATCH_OK=true
    for pid in "${BATCH_PIDS[@]}"; do
        wait "$pid" || BATCH_OK=false
    done

    # Summary for this batch
    for year in "${BATCH_YEARS[@]}"; do
        RF=$(find "$SCRIPT_DIR/edgar_RiskFactors/$year" -name "*.txt" 2>/dev/null | wc -l)
        BD=$(find "$SCRIPT_DIR/edgar_BusinDescr/$year"  -name "*.txt" 2>/dev/null | wc -l)
        MD=$(find "$SCRIPT_DIR/edgar_MgmtDisc/$year"    -name "*.txt" 2>/dev/null | wc -l)
        DISK=$(df -h / | awk 'NR==2{print $4}')
        echo " $year done — RF:$RF BD:$BD MD:$MD  (disk free: $DISK)"
    done
    echo ""
done

echo "================================================================"
echo " All collection complete."
echo " Final file counts:"
for section in edgar_RiskFactors edgar_BusinDescr edgar_MgmtDisc; do
    total=$(find "$SCRIPT_DIR/$section" -name "*.txt" 2>/dev/null | wc -l)
    echo "   $section: $total files"
done
echo "================================================================"
