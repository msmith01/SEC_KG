"""
Scans the risk_factors preprocessed JSON directory and builds a SQLite index
of companies and filings. Runs once on first startup; subsequent starts skip
re-indexing unless explicitly triggered via /api/reindex.
"""
import json
import logging
from pathlib import Path

from config import RISK_FACTORS_DIR
from database import get_connection

logger = logging.getLogger(__name__)


def needs_indexing() -> bool:
    conn = get_connection()
    count = conn.execute("SELECT COUNT(*) FROM filings").fetchone()[0]
    conn.close()
    return count == 0


def run_indexing() -> dict:
    if not RISK_FACTORS_DIR.exists():
        logger.warning("Risk factors directory not found: %s", RISK_FACTORS_DIR)
        return {"indexed": 0, "errors": 0}

    files = list(RISK_FACTORS_DIR.glob("*.json"))
    logger.info("Indexing %d risk factor files from %s ...", len(files), RISK_FACTORS_DIR)

    conn = get_connection()
    indexed = errors = 0

    for path in files:
        try:
            with open(path, "r", encoding="utf-8") as f:
                doc = json.load(f)

            meta = doc.get("metadata", {})
            cik          = str(meta.get("cik", "")).strip()
            ticker       = str(meta.get("ticker", "") or "").strip()
            name         = str(meta.get("company_name", "") or "").strip()
            accession    = str(meta.get("accession_number", "") or "").strip()
            form_type    = str(meta.get("form_type", "10-K") or "10-K").strip()
            filing_date  = str(meta.get("filing_date", "") or "").strip()
            fiscal_year  = meta.get("fiscal_year")

            if not cik or not accession or not filing_date:
                continue

            conn.execute(
                "INSERT OR REPLACE INTO companies (cik, ticker, name) VALUES (?, ?, ?)",
                (cik, ticker, name),
            )
            conn.execute(
                """INSERT OR REPLACE INTO filings
                   (accession, cik, ticker, company_name, form_type,
                    filing_date, fiscal_year, file_path)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (accession, cik, ticker, name, form_type,
                 filing_date, fiscal_year, str(path)),
            )
            indexed += 1

            if indexed % 500 == 0:
                conn.commit()
                logger.info("  … %d / %d indexed", indexed, len(files))

        except Exception as exc:
            errors += 1
            logger.warning("Error indexing %s: %s", path.name, exc)

    conn.commit()
    conn.close()
    logger.info("Indexing complete: %d indexed, %d errors", indexed, errors)
    return {"indexed": indexed, "errors": errors}
