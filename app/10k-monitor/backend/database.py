import sqlite3
from config import DB_PATH


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS companies (
            cik      TEXT PRIMARY KEY,
            ticker   TEXT NOT NULL,
            name     TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS filings (
            accession    TEXT PRIMARY KEY,
            cik          TEXT NOT NULL,
            ticker       TEXT NOT NULL,
            company_name TEXT NOT NULL,
            form_type    TEXT NOT NULL,
            filing_date  TEXT NOT NULL,
            fiscal_year  INTEGER,
            file_path    TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_filings_cik_date
            ON filings (cik, filing_date DESC);

        CREATE TABLE IF NOT EXISTS delta_cache (
            id         TEXT PRIMARY KEY,
            data       TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    conn.close()
