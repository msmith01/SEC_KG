#!/usr/bin/env bash
# =============================================================================
# git_backup.sh
#
# Daily git backup to GitHub. Stages all code changes (data dirs are
# gitignored), commits with a timestamp message, and pushes to origin/main.
# Safe to run when there are no changes — exits cleanly with no empty commit.
#
# Cron example (runs at 2am daily):
#   0 2 * * * bash /home/matt/Documents/projects/SEC/git_backup.sh
#
# Log: logs/git_backup.log
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/git_backup.log"

cd "$SCRIPT_DIR" || { echo "$(date): ERROR — could not cd to $SCRIPT_DIR" >> "$LOG"; exit 1; }

TIMESTAMP=$(date '+%Y-%m-%d %H:%M')

echo "" >> "$LOG"
echo "======================================================" >> "$LOG"
echo " Git backup: $TIMESTAMP" >> "$LOG"
echo "======================================================" >> "$LOG"

# Stage all changes (respects .gitignore — data dirs, logs, .env excluded)
git add -A >> "$LOG" 2>&1

# Exit cleanly if nothing to commit
if git diff --cached --quiet; then
    echo " Nothing to commit — working tree clean." >> "$LOG"
    exit 0
fi

# Show what will be committed
echo " Staged changes:" >> "$LOG"
git diff --cached --name-status >> "$LOG" 2>&1

# Commit
git commit -m "Auto-backup: $TIMESTAMP" >> "$LOG" 2>&1
COMMIT_EXIT=$?

if [ $COMMIT_EXIT -ne 0 ]; then
    echo " ERROR: commit failed (exit $COMMIT_EXIT)" >> "$LOG"
    exit $COMMIT_EXIT
fi

# Push
git push origin main >> "$LOG" 2>&1
PUSH_EXIT=$?

if [ $PUSH_EXIT -ne 0 ]; then
    echo " ERROR: push failed (exit $PUSH_EXIT)" >> "$LOG"
    exit $PUSH_EXIT
fi

COMMIT_SHA=$(git rev-parse --short HEAD)
echo " Backup complete: $COMMIT_SHA" >> "$LOG"
