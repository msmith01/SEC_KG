# Reinstallation Guide

How to rebuild the SEC 10-K Knowledge Graph pipeline from scratch on a new machine.

---

## Prerequisites

| Dependency | Version | Purpose |
|------------|---------|---------|
| R | ≥ 4.3 | EDGAR data collection |
| Python | ≥ 3.11 | NLP + KG pipeline |
| Docker | any | Neo4j graph database |
| Ollama | latest | Local LLM (optional — can use Anthropic/OpenAI instead) |

---

## 1. Clone the Repo

```bash
git clone git@github.com:msmith01/SEC_KG.git
cd SEC_KG
```

---

## 2. Environment Config

```bash
cp .env.example .env
```

Edit `.env` and fill in:
- `NEO4J_PASSWORD` — set to whatever you use when starting Docker below
- `LLM_PROVIDER` — `ollama` (local), `anthropic`, or `openai`
- API keys if using Anthropic or OpenAI

---

## 3. R Dependencies

```r
install.packages(c("edgar", "dplyr", "stringr", "lubridate"))
```

The `edgar` CRAN package handles all EDGAR HTTP access, HTML/XBRL parsing, and rate limiting.

---

## 4. Python Dependencies

```bash
pip install -r python/requirements.txt
python -m spacy download en_core_web_lg   # large model (preferred)
# or: python -m spacy download en_core_web_sm  # fallback if disk is tight
```

> **Note:** No virtualenv is required. The pipeline uses `python3` directly. If you prefer a venv, create one first and activate it before running `pip install`.

---

## 5. Start Neo4j (Docker)

```bash
docker run -d \
  --name neo4j-sec \
  -p 7474:7474 -p 7687:7687 \
  -v $(pwd)/neo4j_data:/data \
  -v $(pwd)/neo4j_logs:/logs \
  -e NEO4J_AUTH=neo4j/password \
  -e NEO4J_dbms_memory_pagecache_size=2G \
  -e NEO4J_dbms_memory_heap_max__size=4G \
  neo4j:5
```

Wait ~20 seconds for it to boot, then apply the schema (constraints + indexes):

```bash
python3 python/run_kg_population.py --apply-schema
```

Browser UI: http://localhost:7474 (login: `neo4j` / `password`)

---

## 6. (Optional) Start Ollama

Only needed if `LLM_PROVIDER=ollama` in `.env`.

```bash
ollama serve &
ollama pull gpt-oss:20b   # or whichever model you prefer
```

If running on an RTX 5090 (Blackwell), disable GSP firmware to prevent CUDA crashes:

```bash
echo 'options nvidia NVreg_EnableGpuFirmware=0' | sudo tee /etc/modprobe.d/nvidia-gsp.conf
sudo update-initramfs -u
# reboot required
```

---

## 7. R Data Collection

### Option A — Full historical corpus (1993–present)

Download quarterly master indexes first:

```bash
Rscript get_historical_master.R   # downloads all .Rda index files to edgar_MasterIndex/
```

Then collect all companies, all years (runs for many hours — use tmux or nohup):

```bash
nohup bash run_all_years.sh 1993 2024 4 >> logs/collection_full.log 2>&1 &
```

`4` = number of parallel workers per year. Up to 6 is safe within EDGAR rate limits.

### Option B — Recent years only (faster start)

```bash
nohup bash run_all_years.sh 2015 2024 4 >> logs/collection_2015_2024.log 2>&1 &
```

### Option C — Single year

```bash
bash run_parallel_collection.sh 2023 4
```

Output directories (created automatically):
- `edgar_RiskFactors/<year>/` — Item 1A text files
- `edgar_BusinDescr/<year>/` — Item 1 text files
- `edgar_MgmtDisc/<year>/` — Item 7 text files

Raw filings in `edgar_Filings/` are deleted after extraction to save disk space (~4 TB if kept).

---

## 8. Python Pipeline

Run the three stages in order. Each is resumable — re-running skips already-processed files.

### Stage 1 — Preprocessing

Cleans text, segments sentences, tags forward-looking language and company coreferences.

```bash
python3 python/run_preprocessing.py
```

Output: `python/data/preprocessed/{risk_factors,business,mda}/`

### Stage 2 — Glossary Extraction

Builds a cross-company domain glossary. Use `--rules-only` for speed (no LLM required).

```bash
python3 python/run_glossary.py --rules-only --index-chroma
```

Output: `python/data/glossary/glossary.json` + ChromaDB at `python/data/chroma/`

### Stage 3 — KG Population

Writes nodes and edges into Neo4j. `--fast` uses spaCy NER (no GPU required); omit for LLM extraction.

```bash
# Fast mode (spaCy NER) — recommended for first full run
python3 python/run_kg_population.py --fast

# LLM mode — higher quality, requires Ollama/API
python3 python/run_kg_population.py

# One section at a time (chainable)
python3 python/run_kg_population.py --fast --section risk_factors
python3 python/run_kg_population.py --fast --section business
python3 python/run_kg_population.py --fast --section mda
```

Checkpoint file at `python/data/kg_export/.checkpoint.json` — delete it to force a full re-run.

---

## 9. Cron Jobs (Optional)

Keep the pipeline current with daily EDGAR updates:

```bash
crontab -e
```

Add:

```
# Daily: download new EDGAR filings + preprocess (6am)
0 6 * * * cd /path/to/SEC_KG && bash run_daily_update.sh >> logs/cron_daily.log 2>&1

# Hourly: preprocess any new .txt files from ongoing collection
0 * * * * cd /path/to/SEC_KG && python3 python/run_preprocessing.py >> logs/cron_preprocessing.log 2>&1
```

Replace `/path/to/SEC_KG` with the actual clone path.

---

## Directory Layout After Full Run

```
SEC_KG/
├── edgar_MasterIndex/       # quarterly EDGAR index .Rda files
├── edgar_RiskFactors/       # extracted Item 1A text, organised by year
│   ├── 2015/
│   └── ...
├── edgar_BusinDescr/        # extracted Item 1 text
├── edgar_MgmtDisc/          # extracted Item 7 text
├── python/data/
│   ├── preprocessed/        # SectionDocument JSON files
│   ├── glossary/            # domain glossary JSON
│   ├── chroma/              # ChromaDB vector store
│   └── kg_export/           # KG population checkpoint
├── neo4j_data/              # Neo4j database files (Docker volume)
└── logs/                    # all pipeline logs
```

---

## Estimated Scale (2015–2024, ~7,880 companies)

| Stage | Input | Output | Time |
|-------|-------|--------|------|
| R collection | EDGAR | ~117,000 `.txt` files | ~13 hrs (4 workers) |
| Preprocessing | `.txt` files | ~117,000 JSON files | ~3 hrs |
| KG population (fast) | JSON files | millions of nodes/edges | ~8–12 hrs |
