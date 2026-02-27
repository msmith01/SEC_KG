#!/usr/bin/env Rscript
# =============================================================================
# get_8k_items.R
#
# Extracts structured 8-K event data using the edgar package's get8KItems().
# Returns one row per triggered event per filing — e.g.:
#   CIK | company | date | accession | item_code | item_description
#
# Designed to run AFTER get_8k_documents.R has downloaded the raw 8-K files
# to edgar_Filings/Form 8-K/<cik>/. get8KItems() will use those cached files
# rather than re-downloading.
#
# Output:
#   edgar_8K_items/<year>/events_<year>.csv       ← merged structured table
#   edgar_8K_items/<year>/.checkpoint.txt         ← processed CIKs (for resume)
#
# Resumable: skips CIKs already recorded in the checkpoint file.
#
# Usage:
#   Rscript get_8k_items.R --year 2023
#   Rscript get_8k_items.R --year 2022 --batch-size 50
#   Rscript get_8k_items.R --year 2021 --offset 500 --limit 100
# =============================================================================

.libPaths(c("~/R/library", .libPaths()))
suppressPackageStartupMessages({
  library(dplyr)
  library(readr)
  library(edgar)
  library(fs)
})

# ── Parse args ────────────────────────────────────────────────────────────────
args <- commandArgs(trailingOnly = TRUE)

get_arg_int <- function(flag, default) {
  idx <- which(args == flag)
  if (length(idx) && length(args) >= idx + 1) as.integer(args[idx + 1]) else default
}

FILING_YEAR <- get_arg_int("--year",       as.integer(format(Sys.Date(), "%Y")))
BATCH_SIZE  <- get_arg_int("--batch-size", 50L)   # CIKs per get8KItems() call
OFFSET      <- get_arg_int("--offset",     0L)
LIMIT       <- get_arg_int("--limit",      .Machine$integer.max)

BASE_DIR   <- "/home/matt/Documents/projects/SEC"
USER_AGENT <- "mattonline1@gmail.com"

setwd(BASE_DIR)

message(sprintf("=== Collecting 8-K structured events for year: %d ===", FILING_YEAR))
message(sprintf("    Batch size: %d CIKs per call", BATCH_SIZE))

# ── Read master index for target year ─────────────────────────────────────────
read_master_index_year <- function(year) {
  idx_dir   <- file.path(BASE_DIR, "edgar_MasterIndex")
  rda_files <- Sys.glob(file.path(idx_dir, paste0(year, "master.Rda")))

  if (length(rda_files) == 0) {
    message(sprintf("  [!] No master index for %d.", year))
    message("      Run: Rscript get_historical_master.R")
    return(NULL)
  }

  bind_rows(lapply(rda_files, function(f) {
    e <- new.env(parent = emptyenv())
    tryCatch({
      load(f, envir = e)
      df <- get(ls(e)[[1]], envir = e)
      names(df) <- tolower(trimws(names(df)))
      names(df) <- gsub("[. ]", "_", names(df))
      if (!"form_type" %in% names(df) && "form.type" %in% names(df))
        df <- rename(df, form_type = form.type)
      if (!"form_type" %in% names(df) && "type" %in% names(df))
        df <- rename(df, form_type = type)
      if (!"cik" %in% names(df) && "cik_no" %in% names(df))
        df <- rename(df, cik = cik_no)
      as_tibble(df)
    }, error = function(e2) {
      message(sprintf("  [!] Failed to load %s: %s", basename(f), e2$message))
      NULL
    })
  }))
}

# ── Build target CIK list ─────────────────────────────────────────────────────
current_year <- as.integer(format(Sys.Date(), "%Y"))

if (FILING_YEAR >= current_year) {
  message("Building target list from daily master CSVs (current year)...")
  csv_files <- list.files(file.path(BASE_DIR, "edgar_DailyMasterCSVs"),
                          pattern = "\\.csv$", full.names = TRUE)
  master <- bind_rows(lapply(csv_files, function(f) {
    tryCatch(read_csv(f, show_col_types = FALSE), error = function(e) NULL)
  }))
  form_col <- if ("form.type" %in% names(master)) "form.type" else "form_type"
  cik_col  <- if ("cik" %in% names(master)) "cik" else "CIK"
} else {
  message(sprintf("Building target list from master index for %d...", FILING_YEAR))
  master   <- read_master_index_year(FILING_YEAR)
  form_col <- "form_type"
  cik_col  <- "cik"
}

if (is.null(master) || nrow(master) == 0) {
  message("No master data found. Exiting.")
  quit(status = 1)
}

# Filter to 8-K form types and cross-reference with our ticker list
eightk_forms <- c("8-K", "8-K/A", "8-K12B", "8-K12G3", "8-K15D5")
eightk_filers <- master %>%
  filter(.data[[form_col]] %in% eightk_forms) %>%
  distinct(cik = as.integer(.data[[cik_col]]))

ticker_cik <- read_csv(file.path(BASE_DIR, "ticker_to_cik.csv"),
                       show_col_types = FALSE) %>%
  mutate(cik = as.integer(CIK))

targets <- eightk_filers %>%
  inner_join(ticker_cik, by = "cik") %>%
  group_by(cik) %>%
  slice_min(Ticker, n = 1, with_ties = FALSE) %>%
  ungroup() %>%
  arrange(cik)

message(sprintf("Total 8-K filers in our list for %d: %d companies", FILING_YEAR, nrow(targets)))

# Apply offset / limit
if (OFFSET > 0)              targets <- targets %>% slice((OFFSET + 1):n())
if (LIMIT < .Machine$integer.max) targets <- targets %>% slice(1:LIMIT)

message(sprintf("Processing this run: %d companies (offset=%d)", nrow(targets), OFFSET))

# ── Output directory + checkpoint ─────────────────────────────────────────────
yr_str      <- as.character(FILING_YEAR)
out_dir     <- file.path(BASE_DIR, "edgar_8K_items", yr_str)
dir.create(out_dir, showWarnings = FALSE, recursive = TRUE)

out_csv        <- file.path(out_dir, sprintf("events_%d.csv", FILING_YEAR))
checkpoint_file <- file.path(out_dir, ".checkpoint.txt")

# Load already-processed CIKs
done_ciks <- integer(0)
if (file.exists(checkpoint_file)) {
  done_ciks <- as.integer(readLines(checkpoint_file))
  message(sprintf("Resuming: %d CIKs already processed", length(done_ciks)))
}

# Filter to unprocessed targets
pending <- targets %>% filter(!cik %in% done_ciks)
message(sprintf("Remaining: %d companies to process", nrow(pending)))

if (nrow(pending) == 0) {
  message("Nothing to do — all CIKs already processed.")
  quit(status = 0)
}

# ── Batch processing ──────────────────────────────────────────────────────────
cik_vec   <- pending$cik
n_total   <- length(cik_vec)
n_batches <- ceiling(n_total / BATCH_SIZE)
n_done    <- 0L
n_failed  <- 0L
t_start   <- proc.time()[3]

# Open output CSV (append mode if resuming, write header only on first write)
first_write <- !file.exists(out_csv)

for (b in seq_len(n_batches)) {
  batch_start <- (b - 1) * BATCH_SIZE + 1
  batch_end   <- min(b * BATCH_SIZE, n_total)
  batch_ciks  <- cik_vec[batch_start:batch_end]

  message(sprintf("\n[Batch %d/%d] CIKs %d–%d (%d companies)",
                  b, n_batches, batch_start, batch_end, length(batch_ciks)))

  result <- tryCatch(
    get8KItems(
      cik.no      = batch_ciks,
      filing.year = FILING_YEAR,
      useragent   = USER_AGENT
    ),
    error = function(e) {
      message(sprintf("  ERROR: %s", e$message))
      NULL
    },
    warning = function(w) {
      # edgar package emits warnings on missing filings — suppress and continue
      withCallingHandlers(
        get8KItems(
          cik.no      = batch_ciks,
          filing.year = FILING_YEAR,
          useragent   = USER_AGENT
        ),
        warning = function(w2) invokeRestart("muffleWarning")
      )
    }
  )

  if (!is.null(result) && is.data.frame(result) && nrow(result) > 0) {
    # Normalise column names for consistent CSV output
    names(result) <- tolower(gsub("[. ]", "_", names(result)))

    write_csv(result,
              out_csv,
              append    = !first_write,
              col_names = first_write)
    first_write <- FALSE

    n_done <- n_done + length(batch_ciks)
    message(sprintf("  Wrote %d event rows", nrow(result)))
  } else {
    message("  No events returned for this batch (filings may not yet be downloaded)")
    n_failed <- n_failed + length(batch_ciks)
  }

  # Update checkpoint — mark batch as processed regardless of result
  # (avoids infinite retry on genuinely empty filers)
  write(as.character(batch_ciks), checkpoint_file, append = TRUE)

  if (b %% 5 == 0) {
    elapsed   <- proc.time()[3] - t_start
    rate      <- b / max(elapsed, 1)          # batches per second
    remaining <- n_batches - b
    eta_min   <- if (rate > 0) sprintf("%.0f min", remaining / rate / 60) else "?"
    message(sprintf(
      "  Progress: %d/%d batches | %d done, %d failed/empty | ETA: %s",
      b, n_batches, n_done, n_failed, eta_min
    ))
  }

  gc(verbose = FALSE)
}

# ── Summary ───────────────────────────────────────────────────────────────────
elapsed_total <- proc.time()[3] - t_start
n_rows <- if (file.exists(out_csv)) nrow(read_csv(out_csv, show_col_types = FALSE)) else 0L

message(sprintf(
  "\n=== 8-K Items Year %d Done ===\n  Batches processed: %d\n  Companies attempted: %d\n  Failed/empty:       %d\n  Time:               %.1f min\n  Output:             %s\n  Total event rows:   %d",
  FILING_YEAR, n_batches, n_done, n_failed,
  elapsed_total / 60, out_csv, n_rows
))
