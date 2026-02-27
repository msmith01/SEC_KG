#!/usr/bin/env bash
# =============================================================================
# run_parallel_8k.sh
#
# Two-pass 8-K pipeline for a single year:
#   Pass 1 — get_8k_documents.R (parallel)   → raw text files in edgar_8K/<year>/
#   Pass 2 — get_8k_items.R    (parallel)    → structured events CSV in edgar_8K_items/<year>/
#
# Pass 2 runs only after Pass 1 completes successfully (raw files must exist
# for get8KItems to parse without re-downloading).
#
# Usage:
#   bash run_parallel_8k.sh <year> [workers] [total]
#   bash run_parallel_8k.sh 2023           # 4 workers, ~10021 companies
#   bash run_parallel_8k.sh 2022 8         # 8 workers
#   bash run_parallel_8k.sh 2021 4 1000    # 4 workers, first 1000
#   bash run_parallel_8k.sh 2023 4 0 items # skip Pass 1, run Pass 2 only
#
# Logs:
#   logs/8k_<year>_worker_N.log        ← Pass 1 (raw download)
#   logs/8k_items_<year>_worker_N.log  ← Pass 2 (structured events)
# =============================================================================

YEAR=${1:?Usage: $0 <year> [workers] [total] [pass]}
WORKERS=${2:-4}
TOTAL=${3:-10021}
PASS=${4:-both}          # "docs", "items", or "both" (default)
CHUNK=$(( (TOTAL + WORKERS - 1) / WORKERS ))

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

# ── Helper: wait for all PIDs, return 0 only if all succeeded ─────────────────
wait_all() {
    local pids=("$@")
    local all_ok=true
    for i in "${!pids[@]}"; do
        wait "${pids[$i]}"
        if [ $? -ne 0 ]; then
            echo "  Worker $i exited with non-zero status"
            all_ok=false
        else
            echo "  Worker $i done OK"
        fi
    done
    $all_ok
}

# ── Pass 1: raw 8-K text download ─────────────────────────────────────────────
run_pass1() {
    echo "============================================================"
    echo "Pass 1: Downloading raw 8-K text files"
    echo "  Year: $YEAR | Workers: $WORKERS | Companies: $TOTAL | Chunk: $CHUNK each"
    echo "  Logs: $LOG_DIR/8k_${YEAR}_worker_N.log"
    echo "============================================================"

    local PIDS=()
    for (( w=0; w<WORKERS; w++ )); do
        local OFFSET=$(( w * CHUNK ))
        local LOG="$LOG_DIR/8k_${YEAR}_worker_${w}.log"
        echo "  Worker $w: offset=$OFFSET limit=$CHUNK → $LOG"

        Rscript "$SCRIPT_DIR/get_8k_documents.R" \
            --year   "$YEAR"   \
            --offset "$OFFSET" \
            --limit  "$CHUNK"  \
            > "$LOG" 2>&1 &
        PIDS+=($!)
    done

    echo ""
    echo "  Workers started. Monitor with:"
    echo "    tail -f $LOG_DIR/8k_${YEAR}_worker_*.log"
    echo ""

    if wait_all "${PIDS[@]}"; then
        local N
        N=$(find "$SCRIPT_DIR/edgar_8K/$YEAR" -name "*.txt" 2>/dev/null | wc -l)
        echo ""
        echo "Pass 1 complete. Files in edgar_8K/$YEAR/: $N"
        return 0
    else
        echo "Pass 1 had failures — check logs before running Pass 2."
        return 1
    fi
}

# ── Pass 2: structured event extraction ───────────────────────────────────────
run_pass2() {
    echo "============================================================"
    echo "Pass 2: Extracting structured 8-K event items"
    echo "  Year: $YEAR | Workers: $WORKERS | Companies: $TOTAL | Chunk: $CHUNK each"
    echo "  Logs: $LOG_DIR/8k_items_${YEAR}_worker_N.log"
    echo "============================================================"

    local PIDS=()
    for (( w=0; w<WORKERS; w++ )); do
        local OFFSET=$(( w * CHUNK ))
        local LOG="$LOG_DIR/8k_items_${YEAR}_worker_${w}.log"
        echo "  Worker $w: offset=$OFFSET limit=$CHUNK → $LOG"

        Rscript "$SCRIPT_DIR/get_8k_items.R" \
            --year   "$YEAR"   \
            --offset "$OFFSET" \
            --limit  "$CHUNK"  \
            > "$LOG" 2>&1 &
        PIDS+=($!)
    done

    echo ""
    echo "  Workers started. Monitor with:"
    echo "    tail -f $LOG_DIR/8k_items_${YEAR}_worker_*.log"
    echo ""

    if wait_all "${PIDS[@]}"; then
        # Merge per-worker partial CSVs into a single events file
        merge_events_csv
        echo ""
        echo "Pass 2 complete."
        return 0
    else
        echo "Pass 2 had failures — check logs."
        return 1
    fi
}

# ── Merge per-worker event CSVs (each worker writes to the same file via ──────
# checkpoint-guarded appends, so this just reports the final row count) ────────
merge_events_csv() {
    local EVENTS_CSV="$SCRIPT_DIR/edgar_8K_items/$YEAR/events_${YEAR}.csv"
    if [ -f "$EVENTS_CSV" ]; then
        local N_ROWS
        N_ROWS=$(( $(wc -l < "$EVENTS_CSV") - 1 ))   # subtract header
        echo "  Structured events CSV: $EVENTS_CSV ($N_ROWS event rows)"
    else
        echo "  [!] No events CSV found at $EVENTS_CSV"
    fi
}

# ── Main ──────────────────────────────────────────────────────────────────────
case "$PASS" in
    docs)
        run_pass1
        ;;
    items)
        run_pass2
        ;;
    both)
        run_pass1 && run_pass2
        ;;
    *)
        echo "Unknown pass '$PASS'. Use: docs | items | both"
        exit 1
        ;;
esac
