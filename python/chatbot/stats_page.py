"""
Dataset Statistics page for the SEC KG Streamlit app.
Queries Neo4j and ChromaDB to surface corpus coverage metrics.
"""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import streamlit as st
import config
from neo4j import GraphDatabase


# ── Neo4j helper ──────────────────────────────────────────────────────────────

@st.cache_resource
def _get_driver():
    return GraphDatabase.driver(
        config.NEO4J_URI,
        auth=(config.NEO4J_USER, config.NEO4J_PASSWORD),
    )


def _run(cypher: str) -> list[dict]:
    try:
        driver = _get_driver()
        with driver.session(database=config.NEO4J_DATABASE) as s:
            return [dict(r) for r in s.run(cypher)]
    except Exception as e:
        st.error(f"Neo4j error: {e}")
        return []


# ── ChromaDB helper ────────────────────────────────────────────────────────────

@st.cache_resource
def _get_chroma_collection():
    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(config.CHROMA_PERSIST_DIR))
        return client.get_or_create_collection(config.CHROMA_COLLECTION_SENTENCES)
    except Exception:
        return None


# ── Data fetchers (all cached for 5 min) ─────────────────────────────────────

@st.cache_data(ttl=300)
def fetch_top_level():
    rows = _run("""
        MATCH (n)
        RETURN labels(n)[0] AS node_type, count(n) AS cnt
        ORDER BY cnt DESC
    """)
    return {r["node_type"]: r["cnt"] for r in rows if r.get("node_type")}


@st.cache_data(ttl=300)
def fetch_relation_counts():
    return _run("""
        MATCH ()-[r]->()
        RETURN type(r) AS rel_type, count(r) AS cnt
        ORDER BY cnt DESC
    """)


@st.cache_data(ttl=300)
def fetch_filings_by_year():
    return _run("""
        MATCH (f:Filing)-[:FILED_IN]->(fy:FiscalYear)
        RETURN fy.year AS year, count(f) AS filings
        ORDER BY year ASC
    """)


@st.cache_data(ttl=300)
def fetch_sections_by_type():
    return _run("""
        MATCH (s:Section)
        RETURN s.section_type AS section_type, count(s) AS cnt
        ORDER BY cnt DESC
    """)


@st.cache_data(ttl=300)
def fetch_top_companies_by_filings(limit: int = 15):
    return _run(f"""
        MATCH (f:Filing)-[:FILED_BY]->(c:Company)
        RETURN c.name AS company, count(f) AS filings
        ORDER BY filings DESC
        LIMIT {limit}
    """)


@st.cache_data(ttl=300)
def fetch_year_range():
    rows = _run("""
        MATCH (fy:FiscalYear)
        RETURN min(fy.year) AS min_year, max(fy.year) AS max_year
    """)
    if rows:
        return rows[0].get("min_year"), rows[0].get("max_year")
    return None, None


@st.cache_data(ttl=300)
def fetch_chroma_count():
    col = _get_chroma_collection()
    if col is None:
        return None
    try:
        return col.count()
    except Exception:
        return None


@st.cache_data(ttl=300)
def fetch_risk_factor_stats():
    rows = _run("""
        MATCH (rf:RiskFactor)
        RETURN count(rf) AS total_risks
    """)
    total = rows[0]["total_risks"] if rows else 0

    driver_rows = _run("""
        MATCH (rf:RiskFactor)-[:DRIVEN_BY]->(rd:RiskDriver)
        RETURN rd.name AS driver, count(*) AS cnt
        ORDER BY cnt DESC LIMIT 10
    """)
    return total, driver_rows


@st.cache_data(ttl=300)
def fetch_geographic_markets():
    return _run("""
        MATCH (g:GeographicMarket)<-[:OPERATES_IN]-(c:Company)
        RETURN g.name AS market, count(DISTINCT c) AS companies
        ORDER BY companies DESC LIMIT 15
    """)


@st.cache_data(ttl=300)
def fetch_competitor_graph():
    return _run("""
        MATCH (c1:Company)-[:COMPETES_WITH]->(c2:Competitor)
        RETURN c2.name AS competitor, count(DISTINCT c1) AS mentioned_by
        ORDER BY mentioned_by DESC LIMIT 15
    """)


# ── Page renderer ─────────────────────────────────────────────────────────────

def render_stats():
    st.header("Dataset Statistics")
    st.caption("Live counts from Neo4j and ChromaDB — refreshed every 5 minutes.")

    # ── Top-level node counts ──────────────────────────────────────────────────
    node_counts = fetch_top_level()

    n_companies  = node_counts.get("Company", 0)
    n_filings    = node_counts.get("Filing", 0)
    n_sections   = node_counts.get("Section", 0)
    n_fy         = node_counts.get("FiscalYear", 0)
    n_risks      = node_counts.get("RiskFactor", 0)
    n_products   = node_counts.get("Product", 0)
    n_geos       = node_counts.get("GeographicMarket", 0)
    n_competitors= node_counts.get("Competitor", 0)
    n_sentences  = fetch_chroma_count()

    year_min, year_max = fetch_year_range()
    year_span = f"{year_min} – {year_max}" if year_min and year_max else "—"

    # ── KPI row ───────────────────────────────────────────────────────────────
    st.subheader("Corpus Overview")
    cols = st.columns(5)
    cols[0].metric("Companies", f"{n_companies:,}")
    cols[1].metric("Filings", f"{n_filings:,}")
    cols[2].metric("Sections", f"{n_sections:,}")
    cols[3].metric("Fiscal Years", f"{n_fy}  ({year_span})")
    cols[4].metric("Sentences (ChromaDB)", f"{n_sentences:,}" if n_sentences else "—")

    st.divider()

    # ── Filings by year ───────────────────────────────────────────────────────
    col_l, col_r = st.columns(2)

    with col_l:
        st.subheader("Filings per Fiscal Year")
        year_rows = fetch_filings_by_year()
        if year_rows:
            import pandas as pd
            df_year = pd.DataFrame(year_rows).rename(
                columns={"year": "Fiscal Year", "filings": "Filings"}
            )
            st.bar_chart(df_year.set_index("Fiscal Year"))
        else:
            st.info("No fiscal year data found.")

    with col_r:
        st.subheader("Sections by Type")
        sec_rows = fetch_sections_by_type()
        if sec_rows:
            import pandas as pd
            df_sec = pd.DataFrame(sec_rows).rename(
                columns={"section_type": "Section", "cnt": "Count"}
            )
            st.dataframe(df_sec, use_container_width=True, hide_index=True)
        else:
            st.info("No section data found.")

    st.divider()

    # ── Graph node breakdown ───────────────────────────────────────────────────
    st.subheader("Graph Node Breakdown")
    if node_counts:
        import pandas as pd
        df_nodes = pd.DataFrame(
            [{"Node Type": k, "Count": v} for k, v in sorted(node_counts.items(), key=lambda x: -x[1])]
        )
        col_a, col_b = st.columns([1, 2])
        with col_a:
            st.dataframe(df_nodes, use_container_width=True, hide_index=True)
        with col_b:
            st.bar_chart(df_nodes.set_index("Node Type"))
    else:
        st.info("Could not reach Neo4j.")

    st.divider()

    # ── Relationship breakdown ─────────────────────────────────────────────────
    st.subheader("Graph Relationship Breakdown")
    rel_rows = fetch_relation_counts()
    if rel_rows:
        import pandas as pd
        df_rels = pd.DataFrame(rel_rows).rename(
            columns={"rel_type": "Relationship", "cnt": "Count"}
        )
        total_rels = df_rels["Count"].sum()
        st.caption(f"Total relationships in graph: **{total_rels:,}**")
        st.dataframe(df_rels, use_container_width=True, hide_index=True)
    else:
        st.info("No relationship data found.")

    st.divider()

    # ── Top companies ─────────────────────────────────────────────────────────
    col_c, col_d = st.columns(2)

    with col_c:
        st.subheader("Top Companies by Filing Count")
        co_rows = fetch_top_companies_by_filings(15)
        if co_rows:
            import pandas as pd
            df_co = pd.DataFrame(co_rows).rename(
                columns={"company": "Company", "filings": "Filings"}
            )
            st.dataframe(df_co, use_container_width=True, hide_index=True)
        else:
            st.info("No company data found.")

    with col_d:
        st.subheader("Geographic Markets (by companies)")
        geo_rows = fetch_geographic_markets()
        if geo_rows:
            import pandas as pd
            df_geo = pd.DataFrame(geo_rows).rename(
                columns={"market": "Market", "companies": "Companies"}
            )
            st.dataframe(df_geo, use_container_width=True, hide_index=True)
        else:
            st.info("No geographic market data found.")

    st.divider()

    # ── Risk & Competitor insights ─────────────────────────────────────────────
    col_e, col_f = st.columns(2)

    with col_e:
        st.subheader("Top Competitors Mentioned")
        comp_rows = fetch_competitor_graph()
        if comp_rows:
            import pandas as pd
            df_comp = pd.DataFrame(comp_rows).rename(
                columns={"competitor": "Competitor", "mentioned_by": "Mentioned by (companies)"}
            )
            st.dataframe(df_comp, use_container_width=True, hide_index=True)
        else:
            st.info("No competitor data found.")

    with col_f:
        st.subheader("Risk Factor Summary")
        total_risks, driver_rows = fetch_risk_factor_stats()
        st.metric("Total Risk Factors", f"{total_risks:,}")
        if driver_rows:
            import pandas as pd
            df_drivers = pd.DataFrame(driver_rows).rename(
                columns={"driver": "Risk Driver", "cnt": "Count"}
            )
            st.caption("Top risk drivers:")
            st.dataframe(df_drivers, use_container_width=True, hide_index=True)
        else:
            st.info("No risk driver data — run LLM-mode KG population to extract these.")

    st.divider()
    if st.button("Refresh statistics"):
        fetch_top_level.clear()
        fetch_relation_counts.clear()
        fetch_filings_by_year.clear()
        fetch_sections_by_type.clear()
        fetch_top_companies_by_filings.clear()
        fetch_year_range.clear()
        fetch_chroma_count.clear()
        fetch_risk_factor_stats.clear()
        fetch_geographic_markets.clear()
        fetch_competitor_graph.clear()
        st.rerun()
