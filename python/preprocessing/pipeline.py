"""
Preprocessing pipeline orchestrator.

Takes raw .txt files produced by the R edgar extraction and emits
SectionDocument JSON files, one per section per filing.

Supported input directories:
  edgar_RiskFactors/    → SectionType.RISK_FACTORS
  edgar_BusinessDescr/  → SectionType.BUSINESS
  edgar_MgmtDisc/       → SectionType.MDA

R file format (from getRiskFactors / getBusinDescr / getMgmtDisc):
  CIK: <value>
  Company Name: <value>
  Form Type: <value>
  Filing Date: YYYY-MM-DD
  Accession Number: <value>

  <section text>

Usage:
    from preprocessing.pipeline import PreprocessingPipeline
    pp = PreprocessingPipeline()
    pp.run_all()                     # process every available file
    pp.run_file(path, section_type)  # process a single file
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


# ── Header parser ─────────────────────────────────────────────────────────────

_HEADER_FIELDS = {
    "cik":              re.compile(r"^CIK:\s*(.+)$",              re.IGNORECASE),
    "company_name":     re.compile(r"^Company Name:\s*(.+)$",     re.IGNORECASE),
    "form_type":        re.compile(r"^Form Type:\s*(.+)$",        re.IGNORECASE),
    "filing_date":      re.compile(r"^Filing Date:\s*(.+)$",      re.IGNORECASE),
    "accession_number": re.compile(r"^Accession Number:\s*(.+)$", re.IGNORECASE),
}


def _parse_header(lines: list[str]) -> tuple[dict, int]:
    """
    Parse the R-generated header block at the top of each extracted .txt file.

    Returns:
        (header_dict, first_body_line_index)
    """
    header = {}
    body_start = 0

    for i, line in enumerate(lines):
        line = line.strip()
        matched_any = False
        for field, rx in _HEADER_FIELDS.items():
            m = rx.match(line)
            if m:
                header[field] = m.group(1).strip()
                matched_any = True
                break

        # The header ends at the first blank line after at least one field
        if not matched_any and header and line == "":
            body_start = i + 1
            break

    return header, body_start


def _build_metadata(header: dict, ticker_map: dict[str, str]) -> FilingMetadata:
    """Construct FilingMetadata from parsed header dict."""
    cik = header.get("cik", "").lstrip("0") or header.get("cik", "")
    ticker = ticker_map.get(cik)

    filing_date_raw = header.get("filing_date", "")
    try:
        filing_date = datetime.strptime(filing_date_raw, "%Y-%m-%d").date()
    except ValueError:
        filing_date = date.today()

    return FilingMetadata(
        cik=header.get("cik", ""),
        ticker=ticker,
        company_name=header.get("company_name", ""),
        form_type=header.get("form_type", "10-K"),
        accession_number=header.get("accession_number", ""),
        filing_date=filing_date,
        fiscal_year=None,  # derived by validator
    )


# ── Main pipeline ─────────────────────────────────────────────────────────────

class PreprocessingPipeline:
    """
    Reads raw .txt files from R extraction dirs, runs the full preprocessing
    stack, and writes SectionDocument JSON to PREPROCESSED_DIR.
    """

    SECTION_MAP: dict[Path, SectionType] = {
        config.EDGAR_RISK_FACTORS_DIR: SectionType.RISK_FACTORS,
        config.EDGAR_BUSINESS_DIR:     SectionType.BUSINESS,
        config.EDGAR_MGMT_DISC_DIR:    SectionType.MDA,
    }

    def __init__(self):
        self._ticker_map = self._load_ticker_map()

    # ── Ticker map ────────────────────────────────────────────────────────────

    def _load_ticker_map(self) -> dict[str, str]:
        """Return {cik_no_leading_zeros: ticker} from ticker_to_cik.csv."""
        path = config.TICKER_CIK_FILE
        if not path.exists():
            return {}
        import pandas as pd
        df = pd.read_csv(path, dtype=str)
        df["CIK_clean"] = df["CIK"].str.lstrip("0")
        return dict(zip(df["CIK_clean"], df["Ticker"]))

    # ── Single file ───────────────────────────────────────────────────────────

    def run_file(
        self,
        path: Path,
        section_type: SectionType,
        overwrite: bool = False,
    ) -> Optional[SectionDocument]:
        """
        Process one .txt file and write its SectionDocument JSON.
        Returns the SectionDocument, or None if skipped.
        """
        out_path = self._output_path(path, section_type)
        if out_path.exists() and not overwrite:
            return None  # already processed

        raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        header, body_start = _parse_header(raw_lines)

        if not header.get("cik"):
            print(f"[pipeline] No header found in {path.name}, skipping.", file=sys.stderr)
            return None

        body_text = "\n".join(raw_lines[body_start:])
        body_text = clean(body_text)

        metadata = _build_metadata(header, self._ticker_map)

        sentences: list[TaggedSentence] = []
        seq = 0
        for para_idx, sent_idx, sent_text in iter_sentences(body_text):
            tags = tag_sentence(sent_text)
            word_count = len(sent_text.split())
            if word_count < 3:
                continue  # skip fragments

            sent_id = (
                f"{metadata.accession_number}_{section_type.value}_{seq:04d}"
            )
            sentences.append(
                TaggedSentence(
                    sentence_id=sent_id,
                    text=sent_text,
                    paragraph_index=para_idx,
                    sentence_index=sent_idx,
                    word_count=word_count,
                    has_company_coref=tags["has_company_coref"],
                    is_forward_looking=tags["is_forward_looking"],
                    fl_indicators=tags["fl_indicators"],
                    cik=metadata.cik,
                    ticker=metadata.ticker,
                    company_name=metadata.company_name,
                    accession_number=metadata.accession_number,
                    filing_date=metadata.filing_date,
                    fiscal_year=metadata.fiscal_year,
                    section_type=section_type,
                )
            )
            seq += 1

        section_id = (
            f"{metadata.cik}_{metadata.accession_number}_{section_type.value}"
        )
        doc = SectionDocument(
            section_id=section_id,
            section_type=section_type,
            metadata=metadata,
            sentences=sentences,
            source_file=str(path),
        )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            doc.model_dump_json(indent=2), encoding="utf-8"
        )
        return doc

    # ── Batch run ─────────────────────────────────────────────────────────────

    def run_directory(
        self,
        directory: Path,
        section_type: SectionType,
        overwrite: bool = False,
    ) -> list[SectionDocument]:
        """
        Process all .txt files in a directory.
        Handles both flat layout (legacy) and year-subdirectory layout:
          edgar_RiskFactors/<year>/<files>.txt
        """
        # Collect files from flat dir and all year subdirs
        files = sorted(directory.glob("*.txt"))
        for year_dir in sorted(directory.iterdir()) if directory.exists() else []:
            if year_dir.is_dir() and year_dir.name.isdigit():
                files = sorted(files + list(year_dir.glob("*.txt")))

        if not files:
            print(f"[pipeline] No .txt files found in {directory}", file=sys.stderr)
            return []

        results = []
        iterable = tqdm(files, desc=f"{section_type.value}") if _TQDM else files
        for f in iterable:
            doc = self.run_file(f, section_type, overwrite=overwrite)
            if doc:
                results.append(doc)
        return results

    def run_all(self, overwrite: bool = False) -> dict[str, int]:
        """
        Process all three section directories (including year subdirs).
        Returns counts per section type.
        """
        counts = {}
        for directory, section_type in self.SECTION_MAP.items():
            if not directory.exists():
                print(
                    f"[pipeline] Directory not found: {directory} — "
                    "run the R extraction first.",
                    file=sys.stderr,
                )
                counts[section_type.value] = 0
                continue
            docs = self.run_directory(directory, section_type, overwrite=overwrite)
            counts[section_type.value] = len(docs)
            print(f"[pipeline] {section_type.value}: {len(docs)} documents processed.")
        return counts

    # ── Output path ───────────────────────────────────────────────────────────

    def _output_path(self, source: Path, section_type: SectionType) -> Path:
        """
        e.g. edgar_RiskFactors/2488_10-K_2024-02-01_0000002488-24-000010.txt
          →  data/preprocessed/risk_factors/2488_10-K_2024-02-01_0000002488-24-000010.json
        """
        return (
            config.PREPROCESSED_DIR
            / section_type.value
            / source.with_suffix(".json").name
        )
