#!/usr/bin/env Rscript
# =============================================================================
# get_8k_documents.R
#
# Collect 8-K current event filings for companies in our ticker list.
#
# 8-Ks are filed within 4 days of a material event — acquisitions, CEO changes,
# earnings guidance, material agreements etc. Combine with 10-K data for
# event-level analysis alongside annual disclosures.
#
# Output:
#   edgar_8K/<year>/<cik>_8-K_<date>_<accession>.txt
#
# Resumable: skips companies where any 8-K already exists for the year.
#
# Usage:
#   Rscript get_8k_documents.R --year 2023
#   Rscript get_8k_documents.R --year 2022 --batch-size 200
#   Rscript get_8k_documents.R --year 2021 --offset 500 --limit 100
#   Rscript get_8k_documents.R --year 2020 --max-per-company 10
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

FILING_YEAR      <- get_arg_int("--year",            as.integer(format(Sys.Date(), "%Y")))
BATCH_SIZE       <- get_arg_int("--batch-size",      Inf)
OFFSET           <- get_arg_int("--offset",          0L)
LIMIT            <- get_arg_int("--limit",           Inf)
MAX_PER_COMPANY  <- get_arg_int("--max-per-company", 20L)   # cap filings per co per year

BASE_DIR   <- "/home/matt/Documents/projects/SEC"
USER_AGENT <- "mattonline1@gmail.com"

setwd(BASE_DIR)

message(sprintf("=== Collecting 8-K filings for year: %d ===", FILING_YEAR))
message(sprintf("    Max per company: %d", MAX_PER_COMPANY))

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

# Filter to 8-K form types
eightk_forms <- c("8-K", "8-K/A", "8-K12B", "8-K12G3", "8-K15D5")
eightk_filers <- master %>%
  filter(.data[[form_col]] %in% eightk_forms) %>%
  distinct(cik = as.character(as.integer(.data[[cik_col]])))

# Cross-reference with our ticker list
ticker_cik <- read_csv(file.path(BASE_DIR, "ticker_to_cik.csv"),
                       show_col_types = FALSE) %>%
  mutate(cik = as.character(as.integer(CIK)))

targets <- eightk_filers %>%
  inner_join(ticker_cik, by = "cik") %>%
  group_by(cik) %>%
  slice_min(Ticker, n = 1, with_ties = FALSE) %>%
  ungroup() %>%
  arrange(cik)

message(sprintf("Total 8-K filers in our list for %d: %d companies", FILING_YEAR, nrow(targets)))

# Apply offset / limit / batch-size
if (OFFSET > 0)            targets <- targets %>% slice((OFFSET + 1):n())
if (is.finite(LIMIT))      targets <- targets %>% slice(1:LIMIT)
if (is.finite(BATCH_SIZE)) targets <- targets %>% slice(1:BATCH_SIZE)

message(sprintf("Processing this run: %d companies (offset=%d)", nrow(targets), OFFSET))

# ── Output directory ──────────────────────────────────────────────────────────
yr_str  <- as.character(FILING_YEAR)
out_dir <- file.path(BASE_DIR, "edgar_8K", yr_str)
dir.create(out_dir, showWarnings = FALSE, recursive = TRUE)

# ── Helper: check if a company already has 8-Ks downloaded for this year ─────
is_collected <- function(cik_str) {
  length(Sys.glob(file.path(out_dir, paste0(cik_str, "_*.txt")))) > 0
}

# ── Helper: download + copy 8-Ks for one company ─────────────────────────────
fetch_8k_data <- function(cik, year) {
  filings <- tryCatch(
    getFilings(
      cik.no       = cik,
      form.type    = "8-K",
      filing.year  = year,
      quarter      = c(1, 2, 3, 4),
      downl.permit = "y",
      useragent    = USER_AGENT
    ),
    error = function(e) {
      message(sprintf("  getFilings error: %s", e$message))
      NULL
    }
  )

  if (is.null(filings) || nrow(filings) == 0) return(0L)

  # Sort by date descending and cap at MAX_PER_COMPANY
  filings <- filings[order(as.Date(as.character(filings$date.filed), "%Y-%m-%d"),
                            decreasing = TRUE), ]
  if (nrow(filings) > MAX_PER_COMPANY) filings <- filings[1:MAX_PER_COMPANY, ]

  n_copied <- 0L
  for (i in seq_len(nrow(filings))) {
    cik_str    <- as.character(filings$cik[i])
    date_filed <- as.character(filings$date.filed[i])
    ftype      <- gsub("/", "", filings$form.type[i])   # "8-K" → "8-K"
    accession  <- filings$accession.number[i]

    # getFilings downloads to: edgar_Filings/Form 8-K/<cik>/<cik>_8-K_<date>_<accession>.txt
    src <- file.path(
      "edgar_Filings", paste0("Form ", ftype), cik_str,
      paste0(paste(cik_str, ftype, date_filed, accession, sep = "_"), ".txt")
    )
    dest <- file.path(
      out_dir,
      paste0(paste(cik_str, ftype, date_filed, accession, sep = "_"), ".txt")
    )

    if (file.exists(src) && !file.exists(dest)) {
      file.copy(src, dest)
      n_copied <- n_copied + 1L
    }
  }

  message(sprintf("  Copied %d / %d filings to edgar_8K/%s/", n_copied, nrow(filings), yr_str))
  n_copied
}

# ── Main loop ─────────────────────────────────────────────────────────────────
n_total   <- nrow(targets)
n_done    <- 0L
n_skipped <- 0L
n_failed  <- 0L
t_start   <- proc.time()[3]

for (i in seq_len(n_total)) {
  row    <- targets[i, ]
  cik    <- as.integer(row$cik)
  ticker <- row$Ticker

  if (is_collected(as.character(cik))) {
    n_skipped <- n_skipped + 1L
    next
  }

  message(sprintf("\n[%d/%d] %s (CIK %d)", i, n_total, ticker, cik))

  n_copied <- tryCatch(
    fetch_8k_data(cik = cik, year = FILING_YEAR),
    error = function(e) {
      message(sprintf("  ERROR: %s", e$message))
      -1L
    }
  )

  if (n_copied >= 0) n_done <- n_done + 1L else n_failed <- n_failed + 1L

  if (i %% 10 == 0) gc(verbose = FALSE)

  if ((n_done + n_failed) %% 20 == 0) {
    elapsed   <- proc.time()[3] - t_start
    rate      <- (n_done + n_failed) / max(elapsed, 1)
    remaining <- n_total - i
    eta_hr    <- if (rate > 0) sprintf("%.1f hrs", remaining / rate / 3600) else "?"
    message(sprintf(
      "  Progress: %d done, %d skipped, %d failed | %.0fs elapsed | ETA: %s",
      n_done, n_skipped, n_failed, elapsed, eta_hr
    ))
  }
}

elapsed_total <- proc.time()[3] - t_start
n_files       <- length(list.files(out_dir, pattern = "\\.txt$"))
message(sprintf(
  "\n=== 8-K Year %d Done ===\n  Collected: %d\n  Skipped:   %d\n  Failed:    %d\n  Time:      %.1f min\n  Files in edgar_8K/%s/: %d",
  FILING_YEAR, n_done, n_skipped, n_failed, elapsed_total / 60, yr_str, n_files
))
