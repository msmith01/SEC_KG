#!/usr/bin/env bash
# =============================================================================
# run_daily_update.sh
#
# Daily pipeline: download new EDGAR index → collect new 10-K filings →
# preprocess new files. Safe to run multiple times (all steps are resumable).
#
# Usage:
#   bash run_daily_update.sh          # runs for current year
#   bash run_daily_update.sh 2025     # explicit year
#
# Cron example (runs at 6am daily):
#   0 6 * * * /home/matt/Documents/projects/SEC/run_daily_update.sh >> /home/matt/Documents/projects/SEC/logs/cron_daily.log 2>&1
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

YEAR=${1:-$(date +%Y)}
LOG="$LOG_DIR/daily_update_$(date +%Y%m%d).log"

echo "================================================================" | tee -a "$LOG"
echo " Daily update started: $(date)" | tee -a "$LOG"
echo " Year: $YEAR" | tee -a "$LOG"
echo "================================================================" | tee -a "$LOG"

# ── Step 1: Download new daily master index CSVs ──────────────────────────────
echo "" | tee -a "$LOG"
echo "--- Step 1: Daily master index ---" | tee -a "$LOG"
Rscript "$SCRIPT_DIR/get_daily_master_index.R" --days 90 >> "$LOG" 2>&1
echo "  Exit: $?" | tee -a "$LOG"

# ── Step 2: Collect new 10-K filings for the year ─────────────────────────────
# Resumable — already-collected companies are skipped automatically
echo "" | tee -a "$LOG"
echo "--- Step 2: Collecting new 10-K filings ($YEAR) ---" | tee -a "$LOG"
bash "$SCRIPT_DIR/run_parallel_collection.sh" "$YEAR" 4 >> "$LOG" 2>&1
echo "  Exit: $?" | tee -a "$LOG"

# ── Step 3: Preprocess any new .txt files ─────────────────────────────────────
# Only processes files not yet in python/data/preprocessed/
echo "" | tee -a "$LOG"
echo "--- Step 3: Preprocessing new files ---" | tee -a "$LOG"
python3 "$SCRIPT_DIR/python/run_preprocessing.py" >> "$LOG" 2>&1
echo "  Exit: $?" | tee -a "$LOG"

# ── Summary ───────────────────────────────────────────────────────────────────
echo "" | tee -a "$LOG"
RF=$(find "$SCRIPT_DIR/edgar_RiskFactors" -name "*.txt" | wc -l)
BD=$(find "$SCRIPT_DIR/edgar_BusinDescr"  -name "*.txt" | wc -l)
MD=$(find "$SCRIPT_DIR/edgar_MgmtDisc"    -name "*.txt" | wc -l)
PP=$(find "$SCRIPT_DIR/python/data/preprocessed" -name "*.json" | wc -l)
echo "Files — RF: $RF | BD: $BD | MD: $MD | Preprocessed JSON: $PP" | tee -a "$LOG"
echo "" | tee -a "$LOG"
echo "Daily update complete: $(date)" | tee -a "$LOG"
