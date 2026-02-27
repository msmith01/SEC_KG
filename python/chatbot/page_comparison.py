"""
Cross-Company Comparison — side-by-side analysis of 2-4 companies.
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
        st.error(f"Neo4j: {e}")
        return []


@st.cache_data(ttl=600)
def get_all_companies() -> list[str]:
    rows = _neo4j("MATCH (c:Company) RETURN c.name AS name ORDER BY name ASC")
    return [r["name"] for r in rows if r.get("name")]


@st.cache_data(ttl=300)
def get_filing_years(name: str) -> set:
    rows = _neo4j("""
        MATCH (f:Filing)-[:FILED_BY]->(c:Company {name: $n})
        OPTIONAL MATCH (f)-[:FILED_IN]->(fy:FiscalYear)
        RETURN DISTINCT fy.year AS year
    """, {"n": name})
    return {r["year"] for r in rows if r.get("year")}


@st.cache_data(ttl=300)
def get_geos_for(name: str) -> set:
    rows = _neo4j("""
        MATCH (c:Company {name: $n})-[:OPERATES_IN]->(g:GeographicMarket)
        RETURN g.name AS market
    """, {"n": name})
    return {r["market"] for r in rows}


@st.cache_data(ttl=300, show_spinner=False)
def get_sentiment_for(name: str) -> pd.DataFrame:
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
        tot: dict = defaultdict(int)
        fwd: dict = defaultdict(int)
        for m in metas:
            yr = m.get("fiscal_year")
            if yr:
                tot[yr] += 1
                if m.get("is_forward_looking"):
                    fwd[yr] += 1
        return pd.DataFrame([
            {"Year": yr, "PctFwd": round(100 * fwd[yr] / tot[yr], 1), "Sentences": tot[yr]}
            for yr in sorted(tot)
        ])
    except Exception:
        return pd.DataFrame()


def render_comparison():
    st.header("Cross-Company Comparison")

    companies = get_all_companies()
    if not companies:
        st.error("No companies found in Neo4j.")
        return

    selected = st.multiselect(
        "Select 2–4 companies to compare",
        companies,
        default=companies[:2] if len(companies) >= 2 else companies,
        max_selections=4,
    )

    if len(selected) < 2:
        st.info("Select at least 2 companies.")
        return

    st.divider()

    # ── Filing coverage ────────────────────────────────────────────────────────
    st.subheader("Filing Coverage")
    coverage_rows = []
    year_sets = {}
    for co in selected:
        years = get_filing_years(co)
        year_sets[co] = years
        coverage_rows.append({
            "Company": co,
            "# Filings": len(years),
            "Earliest": min(years) if years else "—",
            "Latest":   max(years) if years else "—",
            "Years": ", ".join(str(y) for y in sorted(years)) if years else "—",
        })
    st.dataframe(
        pd.DataFrame(coverage_rows),
        use_container_width=True, hide_index=True,
    )

    # ── Year overlap heatmap ───────────────────────────────────────────────────
    all_years = sorted({y for ys in year_sets.values() for y in ys})
    if all_years:
        heat_data = {
            co: ["Y" if y in year_sets[co] else "" for y in all_years]
            for co in selected
        }
        heat_df = pd.DataFrame(heat_data, index=all_years)
        heat_df.index.name = "Year"
        with st.expander("Year-by-year presence"):
            st.dataframe(heat_df, use_container_width=True)

    st.divider()

    # ── Geographic overlap ─────────────────────────────────────────────────────
    st.subheader("Geographic Overlap")
    geo_data = {co: get_geos_for(co) for co in selected}

    if any(geo_data.values()):
        all_markets = sorted({m for geos in geo_data.values() for m in geos})
        overlap_df = pd.DataFrame({
            "Market": all_markets,
            **{
                co: ["Yes" if m in geo_data[co] else "" for m in all_markets]
                for co in selected
            },
        })
        st.dataframe(overlap_df, use_container_width=True, hide_index=True)

        shared = [m for m in all_markets if all(m in geo_data[co] for co in selected)]
        st.caption(
            f"**Shared markets ({len(shared)}):** {', '.join(shared) if shared else 'none'}"
        )
        for co in selected:
            unique = [m for m in geo_data[co] if sum(1 for c in selected if m in geo_data[c]) == 1]
            if unique:
                st.caption(f"**{co} only:** {', '.join(unique[:8])}")
    else:
        st.info("No geographic market data — run KG population.")

    st.divider()

    # ── Forward-looking sentiment ─────────────────────────────────────────────
    st.subheader("Forward-Looking Sentiment Trend")
    st.caption("% forward-looking sentences per year — higher = more bullish management tone")

    dfs: dict[str, pd.DataFrame] = {}
    with st.spinner("Loading from ChromaDB..."):
        for co in selected:
            df = get_sentiment_for(co)
            if not df.empty:
                dfs[co] = df

    if dfs:
        merged = pd.concat(
            [df.assign(Company=co) for co, df in dfs.items()],
            ignore_index=True,
        )
        try:
            import plotly.express as px
            fig = px.line(
                merged, x="Year", y="PctFwd", color="Company",
                markers=True,
                title="Forward-Looking % by Year",
                labels={"PctFwd": "% Forward-Looking"},
            )
            fig.update_layout(yaxis_range=[0, 100])
            st.plotly_chart(fig, use_container_width=True)
        except ImportError:
            pivot = merged.pivot(index="Year", columns="Company", values="PctFwd")
            st.line_chart(pivot)

        # Summary stats
        summary_rows = []
        for co, df in dfs.items():
            summary_rows.append({
                "Company": co,
                "Avg % Fwd-Looking": round(df["PctFwd"].mean(), 1),
                "Peak Year": int(df.loc[df["PctFwd"].idxmax(), "Year"]),
                "Trough Year": int(df.loc[df["PctFwd"].idxmin(), "Year"]),
                "Latest %": df.iloc[-1]["PctFwd"] if len(df) else "—",
                "Trend": "Up" if len(df) >= 2 and df["PctFwd"].iloc[-1] > df["PctFwd"].iloc[0] else "Down",
            })
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)
    else:
        st.info("No ChromaDB data found for these companies.")

    st.divider()

    # ── Semantic search within selected companies ─────────────────────────────
    st.subheader("Search Within These Companies")
    st.caption("Find semantically similar sentences across the selected companies side-by-side.")
    search_q = st.text_input("Search query", placeholder="e.g. tariff exposure supply chain")
    if search_q:
        col = _get_collection()
        if col:
            try:
                results = col.query(
                    query_texts=[search_q],
                    n_results=20,
                    where={"company_name": {"$in": selected}},
                    include=["documents", "metadatas", "distances"],
                )
                docs  = results.get("documents", [[]])[0]
                metas = results.get("metadatas", [[]])[0]
                dists = results.get("distances", [[]])[0]

                if not docs:
                    st.info("No results found.")
                else:
                    for doc, meta, dist in zip(docs[:12], metas[:12], dists[:12]):
                        score = round(1 - dist, 3)
                        co    = meta.get("company_name", "?")
                        yr    = meta.get("fiscal_year", "?")
                        sec   = meta.get("section_type", "?")
                        st.markdown(
                            f"**{co}** &nbsp;·&nbsp; FY{yr} &nbsp;·&nbsp; {sec} &nbsp;·&nbsp; score {score}"
                        )
                        st.markdown(f"> {doc[:400]}")
                        st.divider()
            except Exception as e:
                st.error(f"Search error: {e}")
        else:
            st.error("ChromaDB not available.")
