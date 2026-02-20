#!/usr/bin/env Rscript
# =============================================================================
# get_historical_master.R
#
# Downloads quarterly EDGAR master index files for every year from 1993
# to the current year.  These index files are used by get_all_companies.R
# to build per-year target lists without hammering EDGAR search endpoints.
#
# Run this ONCE before starting multi-year collection, then re-run
# occasionally to pick up newly-closed quarters.
#
# Files are saved to edgar_MasterIndex/ by the edgar package.
#
# Usage:
#   Rscript get_historical_master.R               # 1993 → current year
#   Rscript get_historical_master.R 2000          # 2000 → current year
#   Rscript get_historical_master.R 2000 2010     # 2000–2010 only
# =============================================================================

.libPaths(c("~/R/library", .libPaths()))
suppressPackageStartupMessages(library(edgar))

args       <- commandArgs(trailingOnly = TRUE)
START_YEAR <- if (length(args) >= 1) as.integer(args[1]) else 1993L
END_YEAR   <- if (length(args) >= 2) as.integer(args[2]) else as.integer(format(Sys.Date(), "%Y"))
USER_AGENT <- "mattonline1@gmail.com"
BASE_DIR   <- "/home/matt/Documents/projects/SEC"

setwd(BASE_DIR)
dir.create("edgar_MasterIndex", showWarnings = FALSE)

message(sprintf("Downloading EDGAR master indexes: %d–%d", START_YEAR, END_YEAR))
message("Files will be saved to edgar_MasterIndex/\n")

for (year in START_YEAR:END_YEAR) {
  # Check if already downloaded (edgar package creates one Rda per quarter)
  existing <- file.path(BASE_DIR, "edgar_MasterIndex", paste0(year, "master.Rda"))
  if (file.exists(existing)) {
    message(sprintf("  %d — already downloaded, skipping.", year))
    next
  }

  message(sprintf("  %d ...", year))
  tryCatch(
    getMasterIndex(filing.year = year, useragent = USER_AGENT),
    error = function(e) message(sprintf("    ERROR %d: %s", year, e$message))
  )
}

n_files <- length(Sys.glob(file.path(BASE_DIR, "edgar_MasterIndex", "*.Rda")))
message(sprintf("\nDone. %d master index file(s) in edgar_MasterIndex/", n_files))
message("Next step: run get_all_companies.R --year <YYYY>")
