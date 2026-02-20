

getRiskFactors <- function(cik.no, filing.year, useragent="", output.dir=NULL) {
  #useragent= userAgent
  #cik.no = 0001318605
  #filing.year = year
  f.type <- c("10-K", "10-K405", "10KSB", "10-KSB", "10KSB40")
  
  
  # Check for valid user agent
  if (useragent == "") {
    cat("Please provide a valid User Agent.\nVisit https://www.sec.gov/os/accessing-edgar-data for more information\n")
    return()
  }
  
  # Check the year validity
  if (!is.numeric(filing.year)) {
    cat("Please check the input year.")
    return()
  }
  
  output <- getFilings(cik.no = cik.no, form.type = f.type, filing.year,
                       quarter = c(1, 2, 3, 4), downl.permit = "y", useragent)
  if (is.null(output)) {
    cat("No annual statements found for given CIK(s) and year(s).")
    return()
  }
  
  cat("Extracting 'Item 1A' section...\n")
  progress.bar <- txtProgressBar(min = 0, max = nrow(output), style = 3)
  
  # Function for text cleaning
  CleanFiling <- function(text) {
    text <- gsub("[[:digit:]]+", "", text)
    text <- gsub("\\s{1,}", " ", text)
    text <- gsub('"', "", text)
    return(text)
  }
  
  new.dir <- if (!is.null(output.dir)) output.dir else
               file.path("edgar_RiskFactors", as.character(filing.year))
  dir.create(new.dir, showWarnings = FALSE, recursive = TRUE)
  
  output$extract.status <- 0
  output$company.name <- toupper(as.character(output$company.name))
  output$company.name <- gsub("\\s{2,}", " ", output$company.name)
  
  for (i in seq_len(nrow(output))) {
    ftype <- gsub("/", "", output$form.type[i])
    cname <- output$company.name[i]
    cik <- output$cik[i]
    date.filed <- output$date.filed[i]
    accession <- output$accession.number[i]
    
    dest.filename <- file.path("edgar_Filings", paste0("Form ", ftype),
                               cik, paste(cik, ftype, date.filed, accession, sep = "_"))
    dest.filename <- paste0(dest.filename, ".txt")
    
    out.file <- file.path(new.dir, paste(cik, ftype, date.filed, accession, sep = "_"))
    out.file <- paste0(out.file, ".txt")
    if (file.exists(out.file)) {
      output$extract.status[i] <- 1
      next
    }
    
    filing.text <- readLines(dest.filename, warn = FALSE)
    tryCatch({
      filing.text <- filing.text[grep("<DOCUMENT>", filing.text, ignore.case = TRUE)[1]:
                                   grep("</DOCUMENT>", filing.text, ignore.case = TRUE)[1]]
    }, error = function(e) {
      filing.text <- filing.text
    })
    
    if (any(grepl("<xml>|<type>xml|<html>|10k.htm|<XBRL>", filing.text, ignore.case = TRUE))) {
      doc <- XML::htmlParse(filing.text, asText = TRUE, useInternalNodes = TRUE)
      f.text <- XML::xpathSApply(doc, "//text()[not(ancestor::script)][not(ancestor::style)]", XML::xmlValue)
      f.text <- iconv(f.text, "latin1", "ASCII", sub = " ")
    } else {
      f.text <- filing.text
    }
    
    f.text <- gsub("\\n|\\t|$", " ", f.text)
    f.text <- gsub("^\\s+", "", f.text)
    f.text <- f.text[!grepl("^\\s*$", f.text)]
    
    # Identify Risk Factors section
    startline <- grep("^Item\\s{0,}1A\\b", f.text, ignore.case = TRUE)
    endline <- grep("^Item\\s{0,}(1B|2)\\b", f.text, ignore.case = TRUE)
    
    if (length(startline) && length(endline)) {
      # choose the last valid match
      s <- startline[length(startline)]
      e <- endline[endline > s][1] - 1
      if (is.na(e)) e <- max(seq_along(f.text))
      
      section <- paste(f.text[s:e], collapse = " ")
      section <- gsub("\\s{2,}", " ", section)
      hdr <- paste0("CIK: ", cik, "\n",
                    "Company Name: ", cname, "\n",
                    "Form Type: ", ftype, "\n",
                    "Filing Date: ", date.filed, "\n",
                    "Accession Number: ", accession)
      content <- paste0(hdr, "\n\n", section)
      
      if (stringr::str_count(section, "\\S+") > 50) {
        writeLines(content, out.file)
        output$extract.status[i] <- 1
      }
    }
    
    setTxtProgressBar(progress.bar, i)
  }
  
  close(progress.bar)
  output$date.filed <- as.Date(as.character(output$date.filed), "%Y-%m-%d")
  names(output)[names(output) == "status"] <- "downld.status"
  
  cat("Risk Factors sections are stored in 'edgar_RiskFactors' directory.\n")
  return(output)
}



fetch10KData <- function(cik, year, userAgent,
                         risk_dir = NULL, busi_dir = NULL, mgmt_dir = NULL) {
  formType <- "10-K"

  # Resolve year-specific output directories
  yr_str   <- as.character(year)
  risk_dir <- if (!is.null(risk_dir)) risk_dir else file.path("edgar_RiskFactors", yr_str)
  busi_dir <- if (!is.null(busi_dir)) busi_dir else file.path("edgar_BusinDescr",  yr_str)
  mgmt_dir <- if (!is.null(mgmt_dir)) mgmt_dir else file.path("edgar_MgmtDisc",    yr_str)
  for (d in c(risk_dir, busi_dir, mgmt_dir)) dir.create(d, showWarnings = FALSE, recursive = TRUE)

  cik_str <- as.character(cik)

  # Helper: move newly created CIK files from a flat dir into the year subdir
  move_to_year_dir <- function(flat_dir, year_dir) {
    new_files <- Sys.glob(file.path(flat_dir, paste0(cik_str, "_*.txt")))
    already   <- Sys.glob(file.path(year_dir, paste0(cik_str, "_*.txt")))
    to_move   <- setdiff(new_files, already)
    if (length(to_move) > 0)
      file.rename(to_move, file.path(year_dir, basename(to_move)))
  }

  # 1) Get all 10-K filings for the specified year and quarters
  filings <- getFilings(
    cik.no      = cik,
    form.type   = formType,
    filing.year = year,
    quarter     = c(1, 2, 3, 4),
    downl.permit = "y",
    useragent   = userAgent
  )

  # 2) Management Discussion & Analysis → move to year subdir
  mgmtDisc <- tryCatch(
    getMgmtDisc(cik.no = cik, filing.year = year, useragent = userAgent),
    error = function(e) { message("  MgmtDisc error: ", e$message); NULL }
  )
  move_to_year_dir("edgar_MgmtDisc", mgmt_dir)

  # 3) Business Description → move to year subdir
  businDescr <- tryCatch(
    getBusinDescr(cik.no = cik, filing.year = year, useragent = userAgent),
    error = function(e) { message("  BusinDescr error: ", e$message); NULL }
  )
  move_to_year_dir("edgar_BusinDescr", busi_dir)

  # 4) Risk Factors → written directly to year subdir
  riskFacts <- tryCatch(
    getRiskFactors(cik.no = cik, filing.year = year, useragent = userAgent,
                   output.dir = risk_dir),
    error = function(e) { message("  RiskFactors error: ", e$message); NULL }
  )

  # 5) Filing Header
  header.df <- tryCatch(
    getFilingHeader(cik.no = cik, form.type = formType,
                    filing.year = year, useragent = userAgent),
    error = function(e) { message("  FilingHeader error: ", e$message); NULL }
  )

  # Delete raw filing files to preserve disk space — sections are already extracted
  raw_filing_dirs <- Sys.glob(file.path("edgar_Filings", "Form*", cik_str))
  for (d in raw_filing_dirs) {
    files_to_del <- list.files(d, full.names = TRUE)
    if (length(files_to_del) > 0) file.remove(files_to_del)
  }

  list(
    filings    = filings,
    mgmtDisc   = mgmtDisc,
    businDescr = businDescr,
    riskFactors = riskFacts,
    header     = header.df
  )
}