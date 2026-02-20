rm(list = ls())
.libPaths(c("~/R/library", .libPaths()))
library(dplyr)
library(readr)
library(purrr)
library(edgar)
library(fs)

base_dir  <- "/home/matt/Documents/projects/SEC"
setwd(base_dir)
source("helper_functions.R")

userAgent <- "mattonline1@gmail.com"

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1: Download daily EDGAR master index CSVs
# ─────────────────────────────────────────────────────────────────────────────
csv_dir    <- file.path(base_dir, "edgar_DailyMasterCSVs")
dir.create(csv_dir, showWarnings = FALSE, recursive = TRUE)

start_date             <- as.Date("2025-01-01")
how_many_days_to_collect <- as.integer(Sys.Date() - start_date)

for (i in seq_len(how_many_days_to_collect)) {
  target_date <- Sys.Date() - i
  filename    <- file.path(csv_dir, paste0("dailyMasterData_", format(target_date, "%Y-%m-%d"), ".csv"))

  if (file.exists(filename)) {
    message("Already exists, skipping: ", filename)
    next
  }

  dailyMasterData <- tryCatch(
    getDailyMaster(input.date = target_date, useragent = userAgent),
    error = function(e) { message("Failed for ", target_date, ": ", e$message); NULL }
  )

  if (!is.null(dailyMasterData) && nrow(dailyMasterData) > 0) {
    write.csv(dailyMasterData, file = filename, row.names = FALSE, fileEncoding = "UTF-8")
    message("Written: ", filename)
  }
}

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2: Fetch 10-K data for the first 10 tickers
# ─────────────────────────────────────────────────────────────────────────────
ticker_cik <- read_csv(file.path(base_dir, "ticker_to_cik.csv"), show_col_types = FALSE)

# Take first 10 tickers; CIKs must be numeric for the edgar package
top10 <- ticker_cik %>%
  slice(1:10) %>%
  mutate(CIK = as.integer(CIK))

filing_year <- 2024   # most recent complete fiscal year

message("\nProcessing 10-K filings for: ", paste(top10$Ticker, collapse = ", "))

results <- pmap(list(cik = top10$CIK, ticker = top10$Ticker), function(cik, ticker) {
  message("\n── Fetching: ", ticker, " (CIK ", cik, ")")
  tryCatch(
    fetch10KData(cik = cik, year = filing_year, userAgent = userAgent),
    error = function(e) {
      message("  ERROR for ", ticker, ": ", e$message)
      NULL
    }
  )
})

names(results) <- top10$Ticker
message("\nDone. Results available in 'results' list, keyed by ticker.")
