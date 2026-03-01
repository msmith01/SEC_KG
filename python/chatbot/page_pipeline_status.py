"""
Pipeline status page — shows collection, preprocessing, and graph state.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config
import streamlit as st


def _count_files(directory: Path, pattern: str = "*.txt") -> int:
    if not directory.exists():
        return 0
    return sum(1 for _ in directory.rglob(pattern))


def _count_files_by_year(root: Path, pattern: str = "*.txt") -> dict[int, int]:
    if not root.exists():
        return {}
    out = {}
    for d in sorted(root.iterdir()):
        if d.is_dir() and d.name.isdigit():
            out[int(d.name)] = sum(1 for _ in d.glob(pattern))
    return out


def _neo4j_counts() -> dict[str, int]:
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            config.NEO4J_URI,
            auth=(config.NEO4J_USER, config.NEO4J_PASSWORD),
        )
        with driver.session(database=config.NEO4J_DATABASE) as s:
            rows = s.run(
                "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS cnt "
                "ORDER BY cnt DESC"
            )
            result = {row["label"]: row["cnt"] for row in rows}
        driver.close()
        return result
    except Exception:
        return {}


def _preprocessed_counts() -> dict[str, int]:
    root = config.PREPROCESSED_DIR
    out = {}
    if not root.exists():
        return out
    for section_dir in sorted(root.iterdir()):
        if section_dir.is_dir():
            out[section_dir.name] = sum(1 for _ in section_dir.glob("*.json"))
    return out


def _tail_log(log_path: Path, n: int = 6) -> str:
    if not log_path.exists():
        return "(log not found)"
    lines = log_path.read_text(errors="replace").splitlines()
    return "\n".join(lines[-n:]) if lines else "(empty)"


def render_pipeline_status():
    st.header("Pipeline Status")

    # ── Data Collection ────────────────────────────────────────────────────────
    st.subheader("R Data Collection")

    col1, col2, col3 = st.columns(3)
    rf_by_year = _count_files_by_year(config.EDGAR_RISK_FACTORS_DIR)
    bd_by_year = _count_files_by_year(config.EDGAR_BUSINESS_DIR)
    md_by_year = _count_files_by_year(config.EDGAR_MGMT_DISC_DIR)

    col1.metric("Risk Factor files", f"{sum(rf_by_year.values()):,}")
    col2.metric("Business files",    f"{sum(bd_by_year.values()):,}")
    col3.metric("MD&A files",        f"{sum(md_by_year.values()):,}")

    # Year breakdown
    all_years = sorted(set(rf_by_year) | set(bd_by_year) | set(md_by_year), reverse=True)
    if all_years:
        with st.expander("Collection by year (10-K)"):
            rows = []
            for y in all_years:
                rf = rf_by_year.get(y, 0)
                bd = bd_by_year.get(y, 0)
                md = md_by_year.get(y, 0)
                status = "Complete" if rf > 0 and bd > 0 and md > 0 else "Partial" if (rf + bd + md) > 0 else "Missing"
                rows.append({"Year": y, "Risk Factors": rf, "Business": bd, "MD&A": md, "Status": status})
            import pandas as pd
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # 8-K
    st.divider()
    st.subheader("8-K Collection")
    ek_by_year = _count_files_by_year(config.EDGAR_8K_DIR)
    ek_items_dir = config.EDGAR_8K_ITEMS_DIR
    n_8k_total = sum(ek_by_year.values())
    n_8k_items = sum(
        sum(1 for _ in (ek_items_dir / str(y)).glob("events_*.csv"))
        for y in ek_by_year
        if (ek_items_dir / str(y)).exists()
    )

    c1, c2 = st.columns(2)
    c1.metric("8-K raw files",    f"{n_8k_total:,}")
    c2.metric("8-K events CSVs",  f"{n_8k_items}")

    if ek_by_year:
        with st.expander("8-K files by year"):
            rows = [{"Year": y, "Raw files": n} for y, n in sorted(ek_by_year.items(), reverse=True)]
            import pandas as pd
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # ── Preprocessing ──────────────────────────────────────────────────────────
    st.divider()
    st.subheader("Preprocessing")
    pre_counts = _preprocessed_counts()
    if pre_counts:
        cols = st.columns(len(pre_counts))
        for col, (section, count) in zip(cols, pre_counts.items()):
            col.metric(section, f"{count:,}")
    else:
        st.info("No preprocessed documents found.")

    # ── Neo4j Graph ───────────────────────────────────────────────────────────
    st.divider()
    st.subheader("Knowledge Graph (Neo4j)")

    with st.spinner("Querying Neo4j..."):
        neo_counts = _neo4j_counts()

    if neo_counts:
        # Summary metrics
        key_nodes = ["Company", "Filing", "FiscalYear", "Competitor", "GeographicMarket",
                     "Section", "RiskFactor", "FinancialMetric", "ManagementOutlook", "Event8K"]
        cols = st.columns(4)
        for i, label in enumerate(key_nodes):
            if label in neo_counts:
                cols[i % 4].metric(label, f"{neo_counts[label]:,}")

        with st.expander("All node types"):
            import pandas as pd
            rows = [{"Label": k, "Count": v} for k, v in sorted(neo_counts.items(), key=lambda x: -x[1])]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.warning("Neo4j not reachable — is the container running?")
        if st.button("Start Neo4j"):
            subprocess.run(["docker", "start", "neo4j-sec"], capture_output=True)
            st.rerun()

    # ── Log tails ─────────────────────────────────────────────────────────────
    st.divider()
    st.subheader("Recent log activity")

    logs = {
        "8K pipeline (2017-2024)":    config.BASE_DIR / "logs" / "8k_2017_2024.log",
        "8K items 2014":              config.BASE_DIR / "logs" / "8k_items_2014_controller3.log",
        "Historical R collection":    config.BASE_DIR / "logs" / "historical_collection2.log",
        "2023 R collection":          config.BASE_DIR / "logs" / "collection_2023_resume2.log",
        "2024 R collection":          config.BASE_DIR / "logs" / "collection_2024_resume2.log",
        "Chatbot":                    config.BASE_DIR / "logs" / "chatbot.log",
    }

    for name, log_path in logs.items():
        if log_path.exists():
            with st.expander(f"{name} (last 6 lines)"):
                st.code(_tail_log(log_path, 6), language=None)
