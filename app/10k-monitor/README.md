# 10K Monitor — Risk Factor Delta MVP

Compares consecutive SEC 10-K **Risk Factor** sections (Item 1A) and highlights
what materially changed between annual filings, with severity scoring.

## Stack

| Layer | Tech |
|---|---|
| Frontend | Next.js 14 (App Router), TypeScript, Tailwind CSS |
| Backend | FastAPI (Python 3.10+) |
| Database | SQLite (auto-created at `backend/data/monitor.db`) |
| Data source | Existing preprocessed JSON in `../../python/data/preprocessed/risk_factors/` |

## Setup

### 1 — Backend

```bash
cd backend

# Create a virtualenv (or reuse the project venv)
python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

# Start the API server (first run indexes ~5 k files — takes ~30 s)
uvicorn main:app --reload --port 8000
```

API docs available at http://localhost:8000/docs once running.

### 2 — Frontend

```bash
cd frontend
npm install
npm run dev
```

App available at http://localhost:3000.

## Key Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Index stats |
| GET | `/api/companies?q=AMD` | List/search companies |
| GET | `/api/companies/{cik}` | Company detail + filing list |
| GET | `/api/delta/{acc_latest}/{acc_previous}` | Compute or retrieve diff |
| POST | `/api/reindex` | Force full re-index of JSON files |

## Pages

| Route | Description |
|---|---|
| `/` | Dashboard — searchable company grid |
| `/company/{cik}` | Filing timeline with Compare buttons |
| `/delta/{accA}/{accB}` | Side-by-side risk factor diff |

## Severity scoring

| Level | Triggered by |
|---|---|
| 🔴 HIGH | Going concern, material weakness, covenant breach, data breach, class action, sanctions, liquidity risk, restatement |
| 🟡 MED  | Cybersecurity, supply chain, interest rate, key personnel, concentration risk, regulatory compliance |
| 🟢 LOW  | Everything else |

## Notes

- The diff is computed sentence-by-sentence using Python `difflib.SequenceMatcher`.
- Results are cached in SQLite after first computation.
- Re-index after adding new preprocessed files: `POST /api/reindex` or restart backend with empty DB.
