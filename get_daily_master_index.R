#!/usr/bin/env Rscript
# =============================================================================
# get_daily_master_index.R
#
# Downloads EDGAR daily master index CSVs for the last N days.
# Skips dates that already have a CSV file (fully resumable).
# Does NOT fetch any filings — just builds the index.
#
# Usage:
#   Rscript get_daily_master_index.R            # last 90 days
#   Rscript get_daily_master_index.R --days 30  # last 30 days
# =============================================================================

.libPaths(c("~/R/library", .libPaths()))
suppressPackageStartupMessages({
  library(edgar)
  library(fs)
})

args      <- commandArgs(trailingOnly = TRUE)
idx       <- which(args == "--days")
DAYS_BACK <- if (length(idx) && length(args) >= idx + 1) as.integer(args[idx + 1]) else 90

BASE_DIR  <- "/home/matt/Documents/projects/SEC"
USER_AGENT <- "mattonline1@gmail.com"
csv_dir   <- file.path(BASE_DIR, "edgar_DailyMasterCSVs")
dir.create(csv_dir, showWarnings = FALSE, recursive = TRUE)

message(sprintf("Downloading daily master index: last %d days (skipping existing)", DAYS_BACK))

n_new <- 0
n_skip <- 0

for (i in seq_len(DAYS_BACK)) {
  target_date <- Sys.Date() - i
  filename    <- file.path(csv_dir, paste0("dailyMasterData_", format(target_date, "%Y-%m-%d"), ".csv"))

  if (file.exists(filename)) {
    n_skip <- n_skip + 1
    next
  }

  result <- tryCatch(
    getDailyMaster(input.date = target_date, useragent = USER_AGENT),
    error = function(e) { message("  Failed: ", target_date, " — ", e$message); NULL }
  )

  if (!is.null(result) && nrow(result) > 0) {
    write.csv(result, file = filename, row.names = FALSE, fileEncoding = "UTF-8")
    message("  Written: ", basename(filename), " (", nrow(result), " rows)")
    n_new <- n_new + 1
  }
}

message(sprintf("Done. New: %d | Skipped: %d", n_new, n_skip))
