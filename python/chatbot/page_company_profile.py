"""
Company Profile page — full view of one company across Neo4j and ChromaDB.
"""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from collections import defaultdict

import streamlit as st
import pandas as pd
import config
from neo4j import GraphDatabase


@st.cache_resource
def _get_driver():
    return GraphDatabase.driver(
        config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD)
    )


@st.cache_resource
def _get_collection():
    import chromadb
    try:
        client = chromadb.PersistentClient(path=str(config.CHROMA_PERSIST_DIR))
        return client.get_collection(config.CHROMA_COLLECTION_SENTENCES)
    except Exception:
        return None


def _neo4j(cypher: str, params: dict | None = None) -> list[dict]:
    try:
        with _get_driver().session(database=config.NEO4J_DATABASE) as s:
            return [dict(r) for r in s.run(cypher, params or {})]
    except Exception as e:
        st.error(f"Neo4j error: {e}")
        return []


@st.cache_data(ttl=600)
def get_all_companies() -> list[str]:
    rows = _neo4j("MATCH (c:Company) RETURN c.name AS name ORDER BY name ASC")
    return [r["name"] for r in rows if r.get("name")]


@st.cache_data(ttl=300)
def get_filing_history(name: str) -> list[dict]:
    return _neo4j("""
        MATCH (f:Filing)-[:FILED_BY]->(c:Company {name: $name})
        OPTIONAL MATCH (f)-[:FILED_IN]->(fy:FiscalYear)
        RETURN fy.year AS year, f.filing_date AS date
        ORDER BY year ASC
    """, {"name": name})


@st.cache_data(ttl=300)
def get_geos(name: str) -> list[str]:
    rows = _neo4j("""
        MATCH (c:Company {name: $name})-[:OPERATES_IN]->(g:GeographicMarket)
        RETURN g.name AS market ORDER BY market ASC
    """, {"name": name})
    return [r["market"] for r in rows]


@st.cache_data(ttl=300)
def get_competitors(name: str) -> list[str]:
    rows = _neo4j("""
        MATCH (c:Company {name: $name})-[:COMPETES_WITH]->(comp:Competitor)
        RETURN comp.name AS competitor ORDER BY competitor ASC LIMIT 20
    """, {"name": name})
    return [r["competitor"] for r in rows]


@st.cache_data(ttl=300)
def get_risks(name: str) -> list[dict]:
    return _neo4j("""
        MATCH (c:Company {name: $name})<-[:FILED_BY]-(f:Filing)
              -[:HAS_SECTION]->(s:Section)-[:HAS_RISK]->(rf:RiskFactor)
        OPTIONAL MATCH (rf)-[:DRIVEN_BY]->(rd:RiskDriver)
        RETURN rf.text AS risk, rd.name AS driver, rf.severity AS severity
        LIMIT 20
    """, {"name": name})


@st.cache_data(ttl=300, show_spinner=False)
def get_company_sentiment(name: str) -> pd.DataFrame:
    col = _get_collection()
    if col is None:
        return pd.DataFrame()
    try:
        result = col.get(
            where={"company_name": {"$eq": name}},
            include=["metadatas"],
        )
        metas = result.get("metadatas", [])
        if not metas:
            return pd.DataFrame()

        year_total: dict = defaultdict(int)
        year_fwd:   dict = defaultdict(int)
        for m in metas:
            yr = m.get("fiscal_year")
            if yr:
                year_total[yr] += 1
                if m.get("is_forward_looking"):
                    year_fwd[yr] += 1

        return pd.DataFrame([
            {
                "Year": yr,
                "Sentences": year_total[yr],
                "Forward-Looking": year_fwd[yr],
                "% FwdLooking": round(100 * year_fwd[yr] / year_total[yr], 1),
            }
            for yr in sorted(year_total)
        ])
    except Exception:
        return pd.DataFrame()


def get_excerpts(name: str, section: str, n: int = 5) -> list[str]:
    col = _get_collection()
    if col is None:
        return []
    try:
        result = col.get(
            where={"$and": [
                {"company_name": {"$eq": name}},
                {"section_type": {"$eq": section}},
            ]},
            include=["documents"],
            limit=n,
        )
        return result.get("documents", [])
    except Exception:
        return []


def render_company_profile():
    st.header("Company Profile")

    companies = get_all_companies()
    if not companies:
        st.error("No companies found in Neo4j — is the database running?")
        return

    company = st.selectbox("Select company", companies)
    if not company:
        return

    st.divider()

    # ── Filing history ─────────────────────────────────────────────────────────
    st.subheader("Filing History")
    filings = get_filing_history(company)
    if filings:
        df_f = pd.DataFrame(filings)
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Filings", len(df_f))
        c2.metric("Earliest Year", df_f["year"].min())
        c3.metric("Latest Year",   df_f["year"].max())
        counts = df_f.groupby("year").size().reset_index(name="Filings")
        st.bar_chart(counts.set_index("year"))
    else:
        st.info("No filing data found for this company.")

    st.divider()

    # ── Geography + Competitors ────────────────────────────────────────────────
    col_l, col_r = st.columns(2)
    with col_l:
        st.subheader("Geographic Markets")
        geos = get_geos(company)
        if geos:
            st.write(", ".join(geos))
        else:
            st.info("No geographic data — needs KG population to complete.")

    with col_r:
        st.subheader("Known Competitors")
        comps = get_competitors(company)
        if comps:
            st.write(", ".join(comps))
        else:
            st.info("No competitor data — needs KG population to complete.")

    st.divider()

    # ── Forward-looking sentiment trend ───────────────────────────────────────
    st.subheader("Management Confidence Trend")
    st.caption(
        "% of sentences using forward-looking language (will, expect, anticipate…) "
        "— higher = more bullish management tone"
    )
    with st.spinner("Loading from ChromaDB..."):
        df_sent = get_company_sentiment(company)

    if not df_sent.empty:
        try:
            import plotly.express as px
            fig = px.line(
                df_sent, x="Year", y="% FwdLooking",
                markers=True,
                title=f"{company} — Forward-Looking %",
                labels={"% FwdLooking": "% Forward-Looking Sentences"},
            )
            fig.update_layout(yaxis_range=[0, 100])
            st.plotly_chart(fig, use_container_width=True)
        except ImportError:
            st.line_chart(df_sent.set_index("Year")["% FwdLooking"])

        with st.expander("Raw data"):
            st.dataframe(df_sent, use_container_width=True, hide_index=True)
    else:
        st.info("No ChromaDB sentence data found for this company.")

    st.divider()

    # ── Risk factors (LLM mode) ────────────────────────────────────────────────
    st.subheader("Risk Factors")
    risks = get_risks(company)
    if risks:
        st.dataframe(pd.DataFrame(risks), use_container_width=True, hide_index=True)
    else:
        st.info("No risk factors — run LLM-mode KG population to extract these.")

    st.divider()

    # ── Filing excerpts ────────────────────────────────────────────────────────
    st.subheader("Filing Excerpts (ChromaDB)")
    tab_rf, tab_bd, tab_md = st.tabs(
        ["Risk Factors", "Business Description", "MD&A"]
    )
    for tab, section in zip(
        [tab_rf, tab_bd, tab_md],
        ["risk_factors", "business_description", "management_discussion"],
    ):
        with tab:
            excerpts = get_excerpts(company, section)
            if excerpts:
                for i, ex in enumerate(excerpts, 1):
                    st.markdown(f"**{i}.** {ex}")
                    st.divider()
            else:
                st.info(f"No {section} sentences found.")
