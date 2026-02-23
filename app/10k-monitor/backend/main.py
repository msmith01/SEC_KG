"""
10K Delta Monitor — FastAPI backend
Routes: /api/companies, /api/companies/{cik}, /api/filings/{accession},
        /api/delta/{acc_latest}/{acc_previous}, /api/reindex
"""
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from config import CORS_ORIGINS, DEFAULT_COMPANY_LIMIT
from database import get_connection, init_db
from delta import build_delta
from indexer import needs_indexing, run_indexing

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if needs_indexing():
        logger.info("Database is empty — running initial indexing (this may take ~30 s)…")
        result = run_indexing()
        logger.info("Indexing done: %s", result)
    else:
        logger.info("Existing index found — skipping re-index.")
    yield


app = FastAPI(title="10K Delta Monitor API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Companies ─────────────────────────────────────────────────────────────────

@app.get("/api/companies")
def list_companies(
    q:      str = Query("",  description="Search by ticker or company name"),
    limit:  int = Query(DEFAULT_COMPANY_LIMIT, ge=1, le=2000),
    offset: int = Query(0, ge=0),
):
    conn = get_connection()
    base_sql = """
        SELECT c.cik, c.ticker, c.name,
               COUNT(f.accession)    AS filing_count,
               MAX(f.filing_date)    AS latest_date,
               MIN(f.filing_date)    AS earliest_date
        FROM companies c
        LEFT JOIN filings f ON f.cik = c.cik
        {where}
        GROUP BY c.cik
        ORDER BY c.ticker
        LIMIT ? OFFSET ?
    """
    if q:
        like = f"%{q.upper()}%"
        sql  = base_sql.format(where="WHERE UPPER(c.ticker) LIKE ? OR UPPER(c.name) LIKE ?")
        rows = conn.execute(sql, (like, like, limit, offset)).fetchall()
    else:
        sql  = base_sql.format(where="")
        rows = conn.execute(sql, (limit, offset)).fetchall()

    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/companies/{cik}")
def get_company(cik: str):
    conn = get_connection()
    company = conn.execute("SELECT * FROM companies WHERE cik = ?", (cik,)).fetchone()
    if not company:
        conn.close()
        raise HTTPException(status_code=404, detail=f"Company {cik!r} not found")

    filings = conn.execute(
        "SELECT * FROM filings WHERE cik = ? ORDER BY filing_date DESC",
        (cik,),
    ).fetchall()
    conn.close()

    result = dict(company)
    result["filings"] = [dict(f) for f in filings]
    return result


# ── Filings ───────────────────────────────────────────────────────────────────

@app.get("/api/filings/{accession:path}")
def get_filing(accession: str):
    conn = get_connection()
    row = conn.execute("SELECT * FROM filings WHERE accession = ?", (accession,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail=f"Filing {accession!r} not found")
    return dict(row)


# ── Delta ─────────────────────────────────────────────────────────────────────

@app.get("/api/delta/{acc_latest:path}/{acc_previous:path}")
def get_delta(acc_latest: str, acc_previous: str):
    cache_key = f"{acc_latest}|{acc_previous}"

    conn = get_connection()

    # Return cached result if available
    cached = conn.execute(
        "SELECT data FROM delta_cache WHERE id = ?", (cache_key,)
    ).fetchone()
    if cached:
        conn.close()
        return json.loads(cached["data"])

    # Load filings from index
    latest   = conn.execute("SELECT * FROM filings WHERE accession = ?", (acc_latest,)).fetchone()
    previous = conn.execute("SELECT * FROM filings WHERE accession = ?", (acc_previous,)).fetchone()
    conn.close()

    if not latest:
        raise HTTPException(status_code=404, detail=f"Filing not found: {acc_latest}")
    if not previous:
        raise HTTPException(status_code=404, detail=f"Filing not found: {acc_previous}")

    try:
        delta = build_delta(dict(latest), dict(previous))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=f"Source file missing: {exc}")
    except Exception as exc:
        logger.exception("Delta computation failed")
        raise HTTPException(status_code=500, detail=str(exc))

    # Cache the result
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO delta_cache (id, data) VALUES (?, ?)",
        (cache_key, json.dumps(delta)),
    )
    conn.commit()
    conn.close()

    return delta


# ── Admin ─────────────────────────────────────────────────────────────────────

@app.post("/api/reindex")
def reindex():
    """Force a full re-index of the preprocessed JSON directory."""
    conn = get_connection()
    conn.execute("DELETE FROM filings")
    conn.execute("DELETE FROM companies")
    conn.execute("DELETE FROM delta_cache")
    conn.commit()
    conn.close()
    result = run_indexing()
    return {"status": "ok", **result}


@app.get("/api/health")
def health():
    conn = get_connection()
    filing_count  = conn.execute("SELECT COUNT(*) FROM filings").fetchone()[0]
    company_count = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    conn.close()
    return {"status": "ok", "filings": filing_count, "companies": company_count}
