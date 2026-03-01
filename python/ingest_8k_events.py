"""
K-8: Ingest structured 8-K event CSVs into Neo4j.

Reads edgar_8K_items/<year>/events_<year>.csv files and creates:
  - Event8K nodes (item code + description, date, accession)
  - (Company)-[:HAS_8K_EVENT]->(Event8K) edges (matched by CIK)
  - (Event8K)-[:FILED_IN]->(FiscalYear) edges

Idempotent: uses MERGE on node_id. Resumable: --years flag picks specific years.

Usage:
    python3 python/ingest_8k_events.py                  # all years in edgar_8K_items/
    python3 python/ingest_8k_events.py --years 2022 2023
    python3 python/ingest_8k_events.py --dry-run        # print stats, no writes
    python3 python/ingest_8k_events.py --apply-schema   # create constraint + index first
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import config
from neo4j import GraphDatabase


# ── Item-code table ────────────────────────────────────────────────────────────
# Maps the leading numeric code in item_name to a short category tag.
_ITEM_CATEGORIES: dict[str, str] = {
    "1.01": "material_agreement",
    "1.02": "agreement_termination",
    "1.03": "bankruptcy",
    "2.01": "asset_acquisition",
    "2.02": "earnings_results",
    "2.03": "direct_obligation",
    "2.04": "triggering_events",
    "2.05": "asset_disposal",
    "2.06": "material_impairment",
    "3.01": "delisting",
    "3.02": "unregistered_sales",
    "4.01": "auditor_change",
    "4.02": "non_reliance_financials",
    "5.01": "change_of_control",
    "5.02": "officer_director_change",
    "5.03": "charter_amendment",
    "5.04": "shareholder_rights",
    "5.05": "compensation_plan",
    "5.06": "shell_company_change",
    "5.07": "shareholder_vote",
    "5.08": "director_compensation",
    "6.01": "ats_notification",
    "7.01": "regulation_fd",
    "8.01": "other_events",
    "9.01": "financial_statements",
}

_CODE_RE = re.compile(r"^(\d+\.\d+)")


def _parse_item(item_name: str) -> tuple[str, str]:
    """Extract (item_code, category) from a raw item_name string."""
    m = _CODE_RE.match(str(item_name).strip())
    if m:
        code = m.group(1)
        cat  = _ITEM_CATEGORIES.get(code, "other")
    else:
        code = ""
        cat  = "other"
    return code, cat


def _slugify(text: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", text.lower().strip())
    return text.strip("_")[:40]


def _accession_clean(acc: str) -> str:
    """Remove dashes from accession number for use in IDs."""
    return re.sub(r"[^0-9a-zA-Z]", "", str(acc))


def _fiscal_year(date_str: str) -> int | None:
    """
    Derive fiscal year from a date string YYYY-MM-DD.
    Q1 filings (month ≤ 3) report on prior year.
    """
    try:
        parts = str(date_str).split("-")
        year  = int(parts[0])
        month = int(parts[1])
        return year - 1 if month <= 3 else year
    except Exception:
        return None


# ── CSV column detection ───────────────────────────────────────────────────────

def _detect_cols(header: list[str]) -> dict[str, str]:
    """
    Map canonical names → actual column names in CSV.
    Handles variations from different edgar package versions.
    """
    h = {c.lower().strip(): c for c in header}
    mapping: dict[str, str] = {}

    for canon, candidates in [
        ("cik",       ["cik_no", "cik.no", "cik", "cik_number"]),
        ("company",   ["company_name", "company.name", "company", "companyname"]),
        ("date",      ["date_filed", "date.filed", "date", "filed_date"]),
        ("accession", ["accession_no", "accession.no", "accession", "accession_number"]),
        ("item_name", ["item_name", "item.name", "items", "item_description", "event_type"]),
    ]:
        for cand in candidates:
            if cand in h:
                mapping[canon] = h[cand]
                break

    return mapping


# ── Neo4j helpers ──────────────────────────────────────────────────────────────

def _apply_schema(driver):
    """Create Event8K uniqueness constraint and indexes."""
    with driver.session(database=config.NEO4J_DATABASE) as s:
        s.run(
            "CREATE CONSTRAINT uq_event8k_node_id IF NOT EXISTS "
            "FOR (n:Event8K) REQUIRE n.node_id IS UNIQUE"
        )
        s.run(
            "CREATE INDEX idx_event8k_cik IF NOT EXISTS "
            "FOR (n:Event8K) ON (n.cik)"
        )
        s.run(
            "CREATE INDEX idx_event8k_item_code IF NOT EXISTS "
            "FOR (n:Event8K) ON (n.item_code)"
        )
        s.run(
            "CREATE INDEX idx_event8k_year IF NOT EXISTS "
            "FOR (n:Event8K) ON (n.year)"
        )
    print("[schema] Event8K constraints and indexes applied.")


def _upsert_event(sess, cik: str, accession: str, item_name: str,
                  item_code: str, category: str, date_str: str,
                  company_name: str, year: int) -> str:
    """MERGE an Event8K node; return its node_id."""
    node_id = f"8k_{cik}_{_accession_clean(accession)}_{_slugify(item_code or item_name)}"
    sess.run(
        "MERGE (e:Event8K {node_id: $node_id}) "
        "SET e.cik          = $cik, "
        "    e.accession_no = $accession, "
        "    e.item_code    = $item_code, "
        "    e.category     = $category, "
        "    e.description  = $description, "
        "    e.date_filed   = $date, "
        "    e.company_name = $company_name, "
        "    e.year         = $year",
        node_id=node_id, cik=cik, accession=accession,
        item_code=item_code, category=category,
        description=str(item_name)[:200],
        date=date_str, company_name=str(company_name)[:200],
        year=year,
    )
    return node_id


def _link_company(sess, cik: str, event_node_id: str) -> bool:
    """Create (Company)-[:HAS_8K_EVENT]->(Event8K) if Company exists."""
    result = sess.run(
        "MATCH (c:Company {cik: $cik}) "
        "MATCH (e:Event8K {node_id: $eid}) "
        "MERGE (c)-[:HAS_8K_EVENT]->(e) "
        "RETURN count(c) AS matched",
        cik=str(cik), eid=event_node_id,
    )
    rec = result.single()
    return bool(rec and rec["matched"] > 0)


def _link_fiscal_year(sess, event_node_id: str, year: int):
    """Create (Event8K)-[:FILED_IN]->(FiscalYear)."""
    sess.run(
        "MATCH (e:Event8K {node_id: $eid}) "
        "MATCH (fy:FiscalYear {node_id: $fyid}) "
        "MERGE (e)-[:FILED_IN]->(fy)",
        eid=event_node_id, fyid=f"fy_{year}",
    )


# ── CSV ingestion ──────────────────────────────────────────────────────────────

def ingest_csv(csv_path: Path, driver, dry_run: bool) -> dict:
    stats = {"rows": 0, "upserted": 0, "linked_company": 0, "skipped": 0, "errors": 0}

    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return stats
        col = _detect_cols(list(reader.fieldnames))

        # Check we have the minimum needed columns
        required = ["cik", "accession", "item_name"]
        missing = [r for r in required if r not in col]
        if missing:
            print(f"  [!] {csv_path.name}: missing columns {missing} — skipping")
            print(f"       Available: {list(reader.fieldnames)}")
            return stats

        rows = list(reader)

    print(f"  {csv_path.name}: {len(rows):,} event rows")
    if dry_run:
        stats["rows"] = len(rows)
        return stats

    with driver.session(database=config.NEO4J_DATABASE) as sess:
        for row in rows:
            stats["rows"] += 1
            try:
                cik       = str(row[col["cik"]]).strip()
                accession = str(row[col["accession"]]).strip()
                item_name = str(row[col["item_name"]]).strip()
                date_str  = str(row.get(col.get("date", ""), "")).strip()
                company   = str(row.get(col.get("company", ""), "")).strip()

                if not cik or not accession or not item_name:
                    stats["skipped"] += 1
                    continue

                item_code, category = _parse_item(item_name)
                year = _fiscal_year(date_str) if date_str else None
                if year is None:
                    stats["skipped"] += 1
                    continue

                eid = _upsert_event(
                    sess, cik, accession, item_name,
                    item_code, category, date_str, company, year,
                )
                stats["upserted"] += 1

                linked = _link_company(sess, cik, eid)
                if linked:
                    stats["linked_company"] += 1

                _link_fiscal_year(sess, eid, year)

            except Exception as e:
                stats["errors"] += 1
                if stats["errors"] <= 5:
                    print(f"  [!] Row error: {e}")

    return stats


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Ingest 8-K event CSVs into Neo4j")
    parser.add_argument("--years",        nargs="+", type=int, help="specific years to ingest")
    parser.add_argument("--dry-run",      action="store_true", help="report only, no writes")
    parser.add_argument("--apply-schema", action="store_true", help="create Event8K constraints first")
    args = parser.parse_args()

    items_root = Path("edgar_8K_items")
    if not items_root.exists():
        print(f"[!] {items_root} does not exist. Run get_8k_items.R first.")
        sys.exit(1)

    # Collect CSVs
    if args.years:
        csv_files = [
            items_root / str(y) / f"events_{y}.csv"
            for y in args.years
        ]
        csv_files = [p for p in csv_files if p.exists()]
    else:
        csv_files = sorted(items_root.glob("*/events_*.csv"))

    if not csv_files:
        print("[!] No events CSVs found.")
        sys.exit(0)

    print(f"Found {len(csv_files)} CSV file(s) to ingest:")
    for p in csv_files:
        print(f"  {p}")

    driver = GraphDatabase.driver(
        config.NEO4J_URI,
        auth=(config.NEO4J_USER, config.NEO4J_PASSWORD),
    )

    if args.apply_schema:
        _apply_schema(driver)

    totals = {"rows": 0, "upserted": 0, "linked_company": 0, "skipped": 0, "errors": 0}

    for csv_path in csv_files:
        print(f"\n--- {csv_path} ---")
        stats = ingest_csv(csv_path, driver, dry_run=args.dry_run)
        for k in totals:
            totals[k] += stats[k]
        if not args.dry_run:
            print(f"  upserted: {stats['upserted']:,}  "
                  f"linked_company: {stats['linked_company']:,}  "
                  f"skipped: {stats['skipped']:,}  "
                  f"errors: {stats['errors']:,}")

    driver.close()

    print(f"\n=== Totals ===")
    for k, v in totals.items():
        print(f"  {k}: {v:,}")
    if args.dry_run:
        print("  [dry-run mode — no writes made]")


if __name__ == "__main__":
    main()
