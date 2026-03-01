"""
8-K preprocessing pipeline (K-6).

Reads raw EDGAR SGML full-text files from edgar_8K/<year>/ and produces
SectionDocument JSON in python/data/preprocessed/8k/.

EDGAR SGML format (produced by get_8k_documents.R / edgar package):
  <SEC-DOCUMENT>...
  <SEC-HEADER>
    ACCESSION NUMBER:    0001234567-23-000001
    FILED AS OF DATE:    20230101
    ITEM INFORMATION:    Entry into a Material Definitive Agreement
    ITEM INFORMATION:    Financial Statements and Exhibits
    FILER:
      COMPANY DATA:
        COMPANY CONFORMED NAME:   ACME CORP
        CENTRAL INDEX KEY:        0001234567
  </SEC-HEADER>
  <DOCUMENT>
    <TYPE>8-K
    <TEXT>
      <HTML>...filing body...</HTML>
    </TEXT>
  </DOCUMENT>

Usage:
    python3 python/run_preprocessing_8k.py              # all years in edgar_8K/
    python3 python/run_preprocessing_8k.py --year 2023  # specific year
    python3 python/run_preprocessing_8k.py --overwrite  # reprocess existing
    python3 python/run_preprocessing_8k.py --limit 100  # first N files
"""
from __future__ import annotations

import json
import re
import sys
import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config
from models.schemas import (
    FilingMetadata,
    SectionDocument,
    SectionType,
    TaggedSentence,
)
from preprocessing.cleaner import clean
from preprocessing.segmenter import iter_sentences
from preprocessing.tagger import tag_sentence

try:
    from tqdm import tqdm
    _TQDM = True
except ImportError:
    _TQDM = False

SECTION_TYPE = SectionType.EIGHT_K
OUTPUT_DIR   = config.PREPROCESSED_DIR / "8k"


# ── SGML header parser ────────────────────────────────────────────────────────

_SGML_FIELDS = {
    "accession":    re.compile(r"^ACCESSION NUMBER:\s*(.+)$",        re.IGNORECASE),
    "filing_date":  re.compile(r"^FILED AS OF DATE:\s*(\d{8})$",     re.IGNORECASE),
    "company_name": re.compile(r"^COMPANY CONFORMED NAME:\s*(.+)$",  re.IGNORECASE),
    "cik":          re.compile(r"^CENTRAL INDEX KEY:\s*0*(\d+)$",    re.IGNORECASE),
}
_ITEM_RE = re.compile(r"^ITEM INFORMATION:\s*(.+)$", re.IGNORECASE)


def _parse_sgml_header(text: str) -> dict:
    """
    Extract metadata fields from the EDGAR SGML header block.
    Returns a dict with keys: accession, filing_date, company_name, cik, items.
    """
    header: dict = {"items": []}
    in_header = False

    for line in text.splitlines():
        stripped = line.strip()

        if stripped.startswith("<SEC-HEADER>"):
            in_header = True
            continue
        if stripped.startswith("</SEC-HEADER>"):
            break

        if not in_header:
            # Still look for ACCESSION NUMBER before the header tag (first line)
            m = _SGML_FIELDS["accession"].match(stripped)
            if m:
                header["accession"] = m.group(1).strip()
            continue

        # Item codes
        m = _ITEM_RE.match(stripped)
        if m:
            header["items"].append(m.group(1).strip())
            continue

        # Other fields
        for field, rx in _SGML_FIELDS.items():
            if field == "accession":
                continue
            m = rx.match(stripped)
            if m:
                header[field] = m.group(1).strip()
                break

    return header


def _parse_filing_date(date_str: str) -> date:
    """Parse YYYYMMDD → date. Returns today on failure."""
    try:
        return datetime.strptime(date_str.strip(), "%Y%m%d").date()
    except (ValueError, AttributeError):
        return date.today()


def _fiscal_year_from_date(d: date) -> int:
    """Q1 filings (month ≤ 3) report on prior year; otherwise current year."""
    return d.year - 1 if d.month <= 3 else d.year


# ── Document body extractor ───────────────────────────────────────────────────

_DOC_START = re.compile(r"<DOCUMENT>", re.IGNORECASE)
_DOC_TYPE  = re.compile(r"^<TYPE>8-K", re.IGNORECASE)
_TEXT_START = re.compile(r"^<TEXT>",   re.IGNORECASE)
_TEXT_END   = re.compile(r"^</TEXT>",  re.IGNORECASE)
_DOC_END    = re.compile(r"^</DOCUMENT>", re.IGNORECASE)


def _extract_body_text(raw: str) -> str:
    """
    Extract text content from the first 8-K DOCUMENT block.
    Strips HTML, returns plain text.
    """
    lines = raw.splitlines()
    in_8k_doc  = False
    in_text    = False
    body_lines = []

    for line in lines:
        if _DOC_START.search(line):
            in_8k_doc = False  # reset; check next line for TYPE
            continue

        if in_8k_doc is False and _DOC_TYPE.match(line.strip()):
            in_8k_doc = True
            continue

        if in_8k_doc and _TEXT_START.match(line.strip()):
            in_text = True
            continue

        if in_text and _TEXT_END.match(line.strip()):
            break

        if in_text:
            body_lines.append(line)

        if _DOC_END.match(line.strip()):
            break

    return "\n".join(body_lines) if body_lines else ""


# ── Main pipeline ─────────────────────────────────────────────────────────────

def _output_path(source: Path) -> Path:
    """Map edgar_8K/<year>/CIK_8-K_date_acc.txt → preprocessed/8k/CIK_8-K_date_acc.json"""
    return OUTPUT_DIR / source.with_suffix(".json").name


def process_file(
    path: Path,
    ticker_map: dict[str, str],
    overwrite: bool = False,
) -> Optional[SectionDocument]:
    """Process a single 8-K .txt file. Returns SectionDocument or None if skipped."""
    out = _output_path(path)
    if out.exists() and not overwrite:
        return None

    raw = path.read_text(encoding="utf-8", errors="replace")

    header = _parse_sgml_header(raw)
    cik    = header.get("cik", "").lstrip("0")
    if not cik:
        return None  # can't identify the company

    filing_date  = _parse_filing_date(header.get("filing_date", ""))
    fiscal_year  = _fiscal_year_from_date(filing_date)
    company_name = header.get("company_name", "")
    accession    = header.get("accession", path.stem)
    items        = header.get("items", [])

    ticker = ticker_map.get(cik, "")

    metadata = FilingMetadata(
        cik=cik,
        ticker=ticker or None,
        company_name=company_name,
        form_type="8-K",
        accession_number=accession,
        filing_date=filing_date,
        fiscal_year=fiscal_year,
    )

    # Extract and clean body
    body_raw  = _extract_body_text(raw)
    body_text = clean(body_raw)

    # Prepend item information as context (helps tagger / downstream LLM)
    if items:
        item_preamble = "Items reported: " + "; ".join(items) + ".\n\n"
        body_text = item_preamble + body_text

    # Segment and tag
    sentences: list[TaggedSentence] = []
    seq = 0
    for para_idx, sent_idx, sent_text in iter_sentences(body_text):
        tags      = tag_sentence(sent_text)
        word_count = len(sent_text.split())
        if word_count < 3:
            continue

        sent_id = f"{accession}_{SECTION_TYPE.value}_{seq:04d}"
        sentences.append(TaggedSentence(
            sentence_id=sent_id,
            text=sent_text,
            paragraph_index=para_idx,
            sentence_index=sent_idx,
            word_count=word_count,
            has_company_coref=tags["has_company_coref"],
            is_forward_looking=tags["is_forward_looking"],
            fl_indicators=tags["fl_indicators"],
            cik=cik,
            ticker=ticker or None,
            company_name=company_name,
            accession_number=accession,
            filing_date=filing_date,
            fiscal_year=fiscal_year,
            section_type=SECTION_TYPE,
        ))
        seq += 1

    section_id = f"{cik}_{accession}_{SECTION_TYPE.value}"
    doc = SectionDocument(
        section_id=section_id,
        section_type=SECTION_TYPE,
        metadata=metadata,
        sentences=sentences,
        source_file=str(path),
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc.model_dump_json(indent=2), encoding="utf-8")
    return doc


def _load_ticker_map() -> dict[str, str]:
    path = config.TICKER_CIK_FILE
    if not path.exists():
        return {}
    import pandas as pd
    df = pd.read_csv(path, dtype=str)
    df["CIK_clean"] = df["CIK"].str.lstrip("0")
    return dict(zip(df["CIK_clean"], df["Ticker"]))


class EightKPipeline:
    """Batch processor for all edgar_8K/<year>/ files."""

    def __init__(self):
        self._ticker_map = _load_ticker_map()

    def run_year(
        self,
        year: int,
        overwrite: bool = False,
        limit: int = 0,
    ) -> int:
        """Process all .txt files for a given year. Returns count processed."""
        year_dir = config.EDGAR_8K_DIR / str(year)
        if not year_dir.exists():
            print(f"[8k-pipeline] {year_dir} not found — skipping.")
            return 0

        files = sorted(year_dir.glob("*.txt"))
        if limit:
            files = files[:limit]

        processed = 0
        iterable = tqdm(files, desc=f"8K {year}") if _TQDM else files
        for f in iterable:
            doc = process_file(f, self._ticker_map, overwrite=overwrite)
            if doc is not None:
                processed += 1

        print(f"[8k-pipeline] {year}: {processed} new documents processed "
              f"({len(files)} total files).")
        return processed

    def run_all(
        self,
        overwrite: bool = False,
        limit: int = 0,
    ) -> dict[int, int]:
        """Process all years found in edgar_8K/. Returns {year: count}."""
        root = config.EDGAR_8K_DIR
        if not root.exists():
            print(f"[8k-pipeline] {root} not found.")
            return {}

        year_dirs = sorted(
            [d for d in root.iterdir() if d.is_dir() and d.name.isdigit()],
            key=lambda d: int(d.name),
        )
        results = {}
        for year_dir in year_dirs:
            results[int(year_dir.name)] = self.run_year(
                int(year_dir.name), overwrite=overwrite, limit=limit
            )
        return results
