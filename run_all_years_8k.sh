#!/usr/bin/env bash
# =============================================================================
# run_all_years_8k.sh
#
# Runs the two-pass 8-K pipeline (raw download + structured events) across
# multiple years. Years run in parallel batches of CONCURRENT_YEARS, each
# year using WORKERS parallel R processes.
#
# Usage:
#   bash run_all_years_8k.sh [start_year] [end_year] [workers] [concurrent]
#
#   bash run_all_years_8k.sh                    # 2014→2024, 4 workers, 3 concurrent
#   bash run_all_years_8k.sh 2020               # 2020→2024
#   bash run_all_years_8k.sh 2020 2022          # 2020–2022
#   bash run_all_years_8k.sh 2014 2024 4 2      # 2 years in parallel, 4 workers each
#
# Logs:
#   logs/8k_<year>_worker_N.log        ← Pass 1 per year/worker
#   logs/8k_items_<year>_worker_N.log  ← Pass 2 per year/worker
#   logs/8k_all_years.log              ← this script's progress
# =============================================================================

START_YEAR=${1:-2014}
END_YEAR=${2:-2024}
WORKERS=${3:-4}
CONCURRENT_YEARS=${4:-3}   # years running simultaneously

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"
MASTER_LOG="$LOG_DIR/8k_all_years.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$MASTER_LOG"; }

log "=== 8-K multi-year pipeline ==="
log "Years: $START_YEAR → $END_YEAR | Workers/year: $WORKERS | Concurrent: $CONCURRENT_YEARS"
log "Master log: $MASTER_LOG"
log ""

YEARS=()
for (( y=START_YEAR; y<=END_YEAR; y++ )); do
    YEARS+=($y)
done

N_YEARS=${#YEARS[@]}
log "Total years to process: $N_YEARS"

# ── Run years in batches of CONCURRENT_YEARS ─────────────────────────────────
batch_start=0
while [ $batch_start -lt $N_YEARS ]; do
    batch_end=$(( batch_start + CONCURRENT_YEARS - 1 ))
    if [ $batch_end -ge $N_YEARS ]; then
        batch_end=$(( N_YEARS - 1 ))
    fi

    BATCH_YEARS=("${YEARS[@]:$batch_start:$((batch_end - batch_start + 1))}")
    log "--- Batch: years ${BATCH_YEARS[*]} ---"

    PIDS=()
    for YEAR in "${BATCH_YEARS[@]}"; do
        YEAR_LOG="$LOG_DIR/8k_year_${YEAR}_controller.log"
        log "  Starting year $YEAR (log: $YEAR_LOG)"

        bash "$SCRIPT_DIR/run_parallel_8k.sh" "$YEAR" "$WORKERS" > "$YEAR_LOG" 2>&1 &
        PIDS+=($!)
    done

    # Wait for all years in this batch
    for i in "${!PIDS[@]}"; do
        YEAR="${BATCH_YEARS[$i]}"
        wait "${PIDS[$i]}"
        STATUS=$?
        if [ $STATUS -eq 0 ]; then
            RAW_N=$(find "$SCRIPT_DIR/edgar_8K/$YEAR"       -name "*.txt" 2>/dev/null | wc -l)
            EVENTS_CSV="$SCRIPT_DIR/edgar_8K_items/$YEAR/events_${YEAR}.csv"
            if [ -f "$EVENTS_CSV" ]; then
                EVENTS_N=$(( $(wc -l < "$EVENTS_CSV") - 1 ))
            else
                EVENTS_N=0
            fi
            log "  Year $YEAR done: $RAW_N raw files | $EVENTS_N event rows"
        else
            log "  Year $YEAR FAILED (exit $STATUS) — check $LOG_DIR/8k_year_${YEAR}_controller.log"
        fi
    done

    batch_start=$(( batch_end + 1 ))
    log ""
done

# ── Final summary ─────────────────────────────────────────────────────────────
log "=== All years complete ==="
for (( y=START_YEAR; y<=END_YEAR; y++ )); do
    RAW_N=$(find "$SCRIPT_DIR/edgar_8K/$y"       -name "*.txt" 2>/dev/null | wc -l)
    EVENTS_CSV="$SCRIPT_DIR/edgar_8K_items/$y/events_${y}.csv"
    if [ -f "$EVENTS_CSV" ]; then
        EVENTS_N=$(( $(wc -l < "$EVENTS_CSV") - 1 ))
    else
        EVENTS_N=0
    fi
    log "  $y: $RAW_N raw 8-K files | $EVENTS_N structured event rows"
done
