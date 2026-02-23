#!/usr/bin/env bash
# =============================================================================
# run_parallel_collection.sh
#
# Runs get_all_companies.R across N parallel workers for a single fiscal year.
#
# Usage:
#   bash run_parallel_collection.sh <year> [workers] [total]
#   bash run_parallel_collection.sh 2024           # 4 workers, ~5128 companies
#   bash run_parallel_collection.sh 2020 8         # 8 workers
#   bash run_parallel_collection.sh 2020 4 1000    # 4 workers, first 1000
#
# Logs: logs/collection_<year>_worker_N.log
# =============================================================================

YEAR=${1:?Usage: $0 <year> [workers] [total]}
WORKERS=${2:-4}
TOTAL=${3:-10021}
CHUNK=$(( (TOTAL + WORKERS - 1) / WORKERS ))

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

echo "Year: $YEAR | Workers: $WORKERS | Companies: $TOTAL | Chunk: $CHUNK each"
echo "Logs: $LOG_DIR/collection_${YEAR}_worker_N.log"
echo ""

PIDS=()

for (( w=0; w<WORKERS; w++ )); do
    OFFSET=$(( w * CHUNK ))
    LOG="$LOG_DIR/collection_${YEAR}_worker_${w}.log"

    echo "Worker $w: offset=$OFFSET limit=$CHUNK → $LOG"

    Rscript "$SCRIPT_DIR/get_all_companies.R" \
        --year   "$YEAR"  \
        --offset "$OFFSET" \
        --limit  "$CHUNK"  \
        > "$LOG" 2>&1 &

    PIDS+=($!)
done

echo ""
echo "All workers started. PIDs: ${PIDS[*]}"
echo "Monitor with: tail -f $LOG_DIR/collection_${YEAR}_worker_*.log"
echo ""

ALL_OK=true
for i in "${!PIDS[@]}"; do
    wait "${PIDS[$i]}"
    STATUS=$?
    if [ $STATUS -ne 0 ]; then
        echo "Worker $i exited with status $STATUS — check $LOG_DIR/collection_${YEAR}_worker_${i}.log"
        ALL_OK=false
    else
        echo "Worker $i done OK"
    fi
done

if $ALL_OK; then
    echo ""
    echo "All workers completed for year $YEAR."
    RF=$(find "$SCRIPT_DIR/edgar_RiskFactors/$YEAR" -name "*.txt" 2>/dev/null | wc -l)
    BD=$(find "$SCRIPT_DIR/edgar_BusinDescr/$YEAR"  -name "*.txt" 2>/dev/null | wc -l)
    MD=$(find "$SCRIPT_DIR/edgar_MgmtDisc/$YEAR"    -name "*.txt" 2>/dev/null | wc -l)
    echo "Files — RiskFactors: $RF | BusinDescr: $BD | MgmtDisc: $MD"
fi
