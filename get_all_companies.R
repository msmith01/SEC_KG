#!/usr/bin/env Rscript
# =============================================================================
# get_all_companies.R
#
# Collect 10-K section data (Risk Factors, Business Description, MD&A) for
# all listed companies that filed in a given fiscal year.
#
# For the current year  → builds target list from edgar_DailyMasterCSVs/
# For historical years  → builds target list from edgar_MasterIndex/ Rda files
#                         (download these first with get_historical_master.R)
#
# Output is organised by year:
#   edgar_RiskFactors/<year>/
#   edgar_BusinDescr/<year>/
#   edgar_MgmtDisc/<year>/
#
# Resumable: re-running skips companies whose output files already exist.
#
# Usage:
#   Rscript get_all_companies.R --year 2024
#   Rscript get_all_companies.R --year 2020 --batch-size 100
#   Rscript get_all_companies.R --year 2020 --offset 500 --limit 100
# =============================================================================

.libPaths(c("~/R/library", .libPaths()))
suppressPackageStartupMessages({
  library(dplyr)
  library(readr)
  library(purrr)
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
BATCH_SIZE  <- get_arg_int("--batch-size", Inf)
OFFSET      <- get_arg_int("--offset",     0L)
LIMIT       <- get_arg_int("--limit",      Inf)

BASE_DIR   <- "/home/matt/Documents/projects/SEC"
USER_AGENT <- "mattonline1@gmail.com"

setwd(BASE_DIR)
source("helper_functions.R")

message(sprintf("=== Collecting year: %d ===", FILING_YEAR))

# ── Helper: read master index for a historical year ───────────────────────────
read_master_index_year <- function(year) {
  idx_dir   <- file.path(BASE_DIR, "edgar_MasterIndex")
  # edgar package saves as: {year}master.Rda  (e.g. 2024master.Rda)
  rda_files <- Sys.glob(file.path(idx_dir, paste0(year, "master.Rda")))

  if (length(rda_files) == 0) {
    message(sprintf("  [!] No master index found for %d.", year))
    message("      Run: Rscript get_historical_master.R")
    return(NULL)
  }

  bind_rows(lapply(rda_files, function(f) {
    e <- new.env(parent = emptyenv())
    tryCatch({
      load(f, envir = e)
      df <- get(ls(e)[[1]], envir = e)
      # Normalise column names regardless of edgar package version
      names(df) <- tolower(trimws(names(df)))
      names(df) <- gsub("[. ]", "_", names(df))
      # Ensure we have form_type (might be 'type' or 'form.type')
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

# ── Build target list ─────────────────────────────────────────────────────────
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

# Filter to 10-K form types
tenk_forms <- c("10-K", "10-K405", "10KSB", "10-KSB", "10KSB40")
tenk_filers <- master %>%
  filter(.data[[form_col]] %in% tenk_forms) %>%
  distinct(cik = as.character(as.integer(.data[[cik_col]])))

# Cross-reference with our ticker list
ticker_cik <- read_csv(file.path(BASE_DIR, "ticker_to_cik.csv"),
                       show_col_types = FALSE) %>%
  mutate(cik = as.character(as.integer(CIK)))

targets <- tenk_filers %>%
  inner_join(ticker_cik, by = "cik") %>%
  group_by(cik) %>%
  slice_min(Ticker, n = 1, with_ties = FALSE) %>%
  ungroup() %>%
  arrange(cik)

message(sprintf("Total targets for %d: %d companies", FILING_YEAR, nrow(targets)))

# Apply offset / limit / batch-size
if (OFFSET > 0)           targets <- targets %>% slice((OFFSET + 1):n())
if (is.finite(LIMIT))     targets <- targets %>% slice(1:LIMIT)
if (is.finite(BATCH_SIZE)) targets <- targets %>% slice(1:BATCH_SIZE)

message(sprintf("Processing this run: %d companies (offset=%d)", nrow(targets), OFFSET))

# ── Year-organised output dirs ────────────────────────────────────────────────
yr_str   <- as.character(FILING_YEAR)
risk_dir <- file.path(BASE_DIR, "edgar_RiskFactors", yr_str)
busi_dir <- file.path(BASE_DIR, "edgar_BusinDescr",  yr_str)
mgmt_dir <- file.path(BASE_DIR, "edgar_MgmtDisc",    yr_str)

dir.create(risk_dir, showWarnings = FALSE, recursive = TRUE)
dir.create(busi_dir, showWarnings = FALSE, recursive = TRUE)
dir.create(mgmt_dir, showWarnings = FALSE, recursive = TRUE)

# ── Helper: check if a company is already fully collected for this year ───────
is_collected <- function(cik_str) {
  patterns <- c(
    file.path(risk_dir, paste0(cik_str, "_*.txt")),
    file.path(busi_dir, paste0(cik_str, "_*.txt")),
    file.path(mgmt_dir, paste0(cik_str, "_*.txt"))
  )
  all(sapply(patterns, function(p) length(Sys.glob(p)) > 0))
}

# ── Main loop ─────────────────────────────────────────────────────────────────
n_total   <- nrow(targets)
n_done    <- 0
n_skipped <- 0
n_failed  <- 0
t_start   <- proc.time()[3]

for (i in seq_len(n_total)) {
  row    <- targets[i, ]
  cik    <- as.integer(row$cik)
  ticker <- row$Ticker

  if (is_collected(as.character(cik))) {
    n_skipped <- n_skipped + 1
    next
  }

  message(sprintf("\n[%d/%d] %s (CIK %d, year %d)", i, n_total, ticker, cik, FILING_YEAR))

  result <- tryCatch(
    fetch10KData(cik = cik, year = FILING_YEAR, userAgent = USER_AGENT,
                 risk_dir = risk_dir, busi_dir = busi_dir, mgmt_dir = mgmt_dir),
    error = function(e) {
      message(sprintf("  ERROR: %s", e$message))
      NULL
    }
  )

  if (!is.null(result)) n_done <- n_done + 1 else n_failed <- n_failed + 1

  # Force R garbage collection every 10 companies to prevent memory accumulation
  if (i %% 10 == 0) gc(verbose = FALSE)

  if ((n_done + n_failed) %% 10 == 0) {
    elapsed   <- proc.time()[3] - t_start
    rate      <- (n_done + n_failed) / max(elapsed, 1)
    remaining <- n_total - i
    eta_hr    <- if (rate > 0) sprintf("%.1f hrs", remaining / rate / 3600) else "unknown"
    message(sprintf(
      "  Progress: %d done, %d skipped, %d failed | Elapsed: %.0fs | ETA: %s",
      n_done, n_skipped, n_failed, elapsed, eta_hr
    ))
  }
}

elapsed_total <- proc.time()[3] - t_start
message(sprintf(
  "\n=== Year %d Done ===\n  Collected: %d\n  Skipped:   %d\n  Failed:    %d\n  Time:      %.1f min",
  FILING_YEAR, n_done, n_skipped, n_failed, elapsed_total / 60
))
