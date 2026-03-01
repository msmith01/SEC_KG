"""
Central configuration for the SEC KG pipeline.
All paths and settings are resolved here so nothing is hardcoded downstream.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent          # /projects/SEC
PYTHON_DIR = Path(__file__).parent               # /projects/SEC/python

# R extraction outputs (read-only from Python's perspective).
# Files are organised as edgar_RiskFactors/<year>/<cik>_*.txt
EDGAR_RISK_FACTORS_DIR  = BASE_DIR / "edgar_RiskFactors"
EDGAR_BUSINESS_DIR      = BASE_DIR / "edgar_BusinDescr"
EDGAR_MGMT_DISC_DIR     = BASE_DIR / "edgar_MgmtDisc"
EDGAR_FILINGS_DIR       = BASE_DIR / "edgar_Filings"
EDGAR_DAILY_CSV_DIR     = BASE_DIR / "edgar_DailyMasterCSVs"
EDGAR_MASTER_INDEX_DIR  = BASE_DIR / "edgar_MasterIndex"
EDGAR_8K_DIR            = BASE_DIR / "edgar_8K"
EDGAR_8K_ITEMS_DIR      = BASE_DIR / "edgar_8K_items"

TICKER_CIK_FILE         = BASE_DIR / "ticker_to_cik.csv"

# Python pipeline outputs
DATA_DIR                = PYTHON_DIR / "data"
PREPROCESSED_DIR        = DATA_DIR / "preprocessed"
GLOSSARY_DIR            = DATA_DIR / "glossary"
KG_EXPORT_DIR           = DATA_DIR / "kg_export"

for d in [PREPROCESSED_DIR, GLOSSARY_DIR, KG_EXPORT_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ── LLM ───────────────────────────────────────────────────────────────────────
# Provider: "ollama" | "anthropic" | "openai"
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")

# Ollama
OLLAMA_BASE_URL  = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL     = os.getenv("OLLAMA_MODEL", "gpt-oss:latest")

# Anthropic (Claude)
ANTHROPIC_API_KEY   = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL     = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

# OpenAI
OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL    = os.getenv("OPENAI_MODEL", "gpt-4o")

# ── Neo4j ─────────────────────────────────────────────────────────────────────
NEO4J_URI      = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
NEO4J_USER     = os.getenv("NEO4J_USER",     "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "secpassword")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

# ── ChromaDB ──────────────────────────────────────────────────────────────────
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", str(DATA_DIR / "chroma"))
CHROMA_COLLECTION_SENTENCES  = "sec_sentences"
CHROMA_COLLECTION_GLOSSARY   = "sec_glossary"

# ── Preprocessing ─────────────────────────────────────────────────────────────
SPACY_MODEL = "en_core_web_lg"       # fallback: en_core_web_sm

# Forward-looking indicators (safe-harbour language)
FORWARD_LOOKING_PATTERNS = [
    r"\bwill\b", r"\bwould\b", r"\bexpect[s]?\b", r"\bexpected\b",
    r"\bexpecting\b", r"\banticipate[ds]?\b", r"\bbelieve[ds]?\b",
    r"\bintend[s]?\b", r"\bintended\b", r"\bplan[s]?\b", r"\bplanned\b",
    r"\bmay\b", r"\bmight\b", r"\bcould\b", r"\bshould\b",
    r"\bforecast[s]?\b", r"\bguidance\b", r"\boutlook\b",
    r"\bprojec(?:t|ts|ted|tion)\b", r"\bestimate[ds]?\b",
    r"\bforward.looking\b", r"\bsafe.harbour\b", r"\bsafe.harbor\b",
    r"we believe", r"we expect", r"we anticipate", r"we intend",
    r"in the future", r"going forward",
]

# Coreference surface forms that resolve to the filing company
COMPANY_COREFS = [
    r"\bwe\b", r"\bour\b", r"\bours\b", r"\bus\b",
    r"\bthe company\b", r"\bthe corporation\b", r"\bthe registrant\b",
    r"\bthe firm\b",
]
