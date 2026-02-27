"""
Geographic Exposure Heatmap — world map of company geographic market presence.
"""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import streamlit as st
import pandas as pd
import config
from neo4j import GraphDatabase

# Country name → ISO alpha-3 mapping for Plotly choropleth
COUNTRY_ISO: dict[str, str] = {
    "UNITED STATES": "USA", "U.S.": "USA", "US": "USA", "USA": "USA",
    "UNITED STATES OF AMERICA": "USA",
    "CHINA": "CHN", "PEOPLE'S REPUBLIC OF CHINA": "CHN", "PRC": "CHN",
    "MAINLAND CHINA": "CHN",
    "JAPAN": "JPN", "GERMANY": "DEU", "UNITED KINGDOM": "GBR", "UK": "GBR",
    "GREAT BRITAIN": "GBR", "ENGLAND": "GBR",
    "FRANCE": "FRA", "CANADA": "CAN", "AUSTRALIA": "AUS", "INDIA": "IND",
    "BRAZIL": "BRA", "MEXICO": "MEX", "SOUTH KOREA": "KOR", "KOREA": "KOR",
    "REPUBLIC OF KOREA": "KOR",
    "ITALY": "ITA", "SPAIN": "ESP", "NETHERLANDS": "NLD", "SWITZERLAND": "CHE",
    "SWEDEN": "SWE", "RUSSIA": "RUS", "RUSSIAN FEDERATION": "RUS",
    "TAIWAN": "TWN", "SINGAPORE": "SGP",
    "HONG KONG": "HKG", "MALAYSIA": "MYS", "INDONESIA": "IDN",
    "THAILAND": "THA", "VIETNAM": "VNM", "VIET NAM": "VNM",
    "ISRAEL": "ISR", "SAUDI ARABIA": "SAU", "UAE": "ARE",
    "UNITED ARAB EMIRATES": "ARE",
    "SOUTH AFRICA": "ZAF", "NIGERIA": "NGA", "EGYPT": "EGY", "TURKEY": "TUR",
    "POLAND": "POL", "CZECH REPUBLIC": "CZE", "CZECHIA": "CZE",
    "HUNGARY": "HUN", "ROMANIA": "ROU", "AUSTRIA": "AUT", "BELGIUM": "BEL",
    "DENMARK": "DNK", "FINLAND": "FIN", "NORWAY": "NOR", "PORTUGAL": "PRT",
    "GREECE": "GRC", "IRELAND": "IRL", "NEW ZEALAND": "NZL",
    "PHILIPPINES": "PHL", "ARGENTINA": "ARG", "CHILE": "CHL",
    "COLOMBIA": "COL", "PERU": "PER", "PAKISTAN": "PAK",
    "BANGLADESH": "BGD", "SRI LANKA": "LKA", "MYANMAR": "MMR",
    "CAMBODIA": "KHM", "LUXEMBOURG": "LUX", "CROATIA": "HRV",
    "SLOVAKIA": "SVK", "SLOVENIA": "SVN", "BULGARIA": "BGR",
    "SERBIA": "SRB", "UKRAINE": "UKR", "KENYA": "KEN", "GHANA": "GHA",
    "ETHIOPIA": "ETH", "MOROCCO": "MAR", "ALGERIA": "DZA", "TUNISIA": "TUN",
    "QATAR": "QAT", "KUWAIT": "KWT", "BAHRAIN": "BHR", "OMAN": "OMN",
    "JORDAN": "JOR", "IRAN": "IRN", "IRAQ": "IRQ",
    "CZECH": "CZE", "KOREA SOUTH": "KOR",
}

# Multi-country regions — shown in a separate table
REGIONS = {
    "EUROPE", "ASIA", "ASIA PACIFIC", "ASIA-PACIFIC", "APAC",
    "LATIN AMERICA", "SOUTH AMERICA", "NORTH AMERICA", "CENTRAL AMERICA",
    "MIDDLE EAST", "AFRICA", "EMEA", "NORTH AFRICA", "SOUTHEAST ASIA",
    "CARIBBEAN", "WESTERN EUROPE", "EASTERN EUROPE", "PACIFIC RIM",
    "GREATER CHINA",
}


@st.cache_resource
def _get_driver():
    return GraphDatabase.driver(
        config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD)
    )


def _neo4j(cypher: str, params: dict | None = None) -> list[dict]:
    try:
        with _get_driver().session(database=config.NEO4J_DATABASE) as s:
            return [dict(r) for r in s.run(cypher, params or {})]
    except Exception as e:
        st.error(f"Neo4j error: {e}")
        return []


@st.cache_data(ttl=300)
def get_all_geo_data() -> list[dict]:
    return _neo4j("""
        MATCH (g:GeographicMarket)<-[:OPERATES_IN]-(c:Company)
        RETURN g.name AS market, count(DISTINCT c) AS companies
        ORDER BY companies DESC
    """)


@st.cache_data(ttl=300)
def get_geo_by_year(year: int) -> list[dict]:
    return _neo4j("""
        MATCH (c:Company)<-[:FILED_BY]-(f:Filing)-[:FILED_IN]->(fy:FiscalYear {year: $year})
        MATCH (c)-[:OPERATES_IN]->(g:GeographicMarket)
        RETURN g.name AS market, count(DISTINCT c) AS companies
        ORDER BY companies DESC
    """, {"year": year})


@st.cache_data(ttl=300)
def get_companies_in_market(market: str) -> list[dict]:
    return _neo4j("""
        MATCH (c:Company)-[:OPERATES_IN]->(g:GeographicMarket {name: $market})
        RETURN c.name AS company
        ORDER BY company ASC LIMIT 50
    """, {"market": market})


def render_geo_heatmap():
    st.header("Geographic Exposure")
    st.caption(
        "Countries and regions extracted from company filings via KG population "
        "(OPERATES_IN relationships from spaCy NER or LLM extraction)."
    )

    # ── Controls ───────────────────────────────────────────────────────────────
    col_mode, col_year = st.columns(2)
    with col_mode:
        view_all = st.checkbox("All years combined", value=True)
    with col_year:
        year = st.number_input(
            "Filter to specific year", 2010, 2025, 2023, step=1,
            disabled=view_all,
        )

    # ── Fetch data ─────────────────────────────────────────────────────────────
    with st.spinner("Loading geographic data..."):
        rows = get_all_geo_data() if view_all else get_geo_by_year(int(year))

    if not rows:
        st.info(
            "No geographic market data found. "
            "Run KG population (`python run_kg_population.py --fast`) to extract geographic links."
        )
        return

    df = pd.DataFrame(rows)
    df["norm"] = df["market"].str.upper().str.strip()
    df["iso"]  = df["norm"].map(COUNTRY_ISO)
    df["is_region"] = df["norm"].isin(REGIONS) | df["iso"].isna()

    df_countries = df[~df["is_region"]].copy()
    df_regions   = df[df["is_region"]].copy()

    # ── World choropleth ───────────────────────────────────────────────────────
    st.subheader("World Heatmap — Companies per Country")
    if not df_countries.empty:
        try:
            import plotly.express as px
            fig = px.choropleth(
                df_countries,
                locations="iso",
                color="companies",
                hover_name="market",
                color_continuous_scale="YlOrRd",
                labels={"companies": "Companies"},
                title="Number of companies with operations in each country",
            )
            fig.update_layout(height=500, geo=dict(showframe=False))
            st.plotly_chart(fig, use_container_width=True)
        except ImportError:
            st.warning("plotly not installed — showing table only.")
    else:
        st.info("No country-level geographic data to display.")

    st.divider()

    # ── Tables ─────────────────────────────────────────────────────────────────
    col_ct, col_rg = st.columns(2)
    with col_ct:
        st.subheader("Countries")
        if not df_countries.empty:
            st.dataframe(
                df_countries[["market", "companies"]].rename(
                    columns={"market": "Country", "companies": "Companies"}
                ).head(30),
                use_container_width=True, hide_index=True,
            )

    with col_rg:
        st.subheader("Regions")
        if not df_regions.empty:
            st.dataframe(
                df_regions[["market", "companies"]].rename(
                    columns={"market": "Region", "companies": "Companies"}
                ),
                use_container_width=True, hide_index=True,
            )

    st.divider()

    # ── China exposure ─────────────────────────────────────────────────────────
    st.subheader("China Exposure — Companies with China Operations")
    china_companies = set()
    for term in ["CHINA", "PRC", "PEOPLE'S REPUBLIC OF CHINA", "MAINLAND CHINA"]:
        rows_c = _neo4j("""
            MATCH (c:Company)-[:OPERATES_IN]->(g:GeographicMarket)
            WHERE toUpper(g.name) = $name
            RETURN c.name AS company
        """, {"name": term})
        china_companies.update(r["company"] for r in rows_c)

    if china_companies:
        sorted_cos = sorted(china_companies)
        st.caption(f"{len(sorted_cos)} companies with China operations in the graph")
        n_cols = 3
        cols = st.columns(n_cols)
        for i, co in enumerate(sorted_cos):
            cols[i % n_cols].markdown(f"- {co}")
    else:
        st.info("No China exposure data found.")

    st.divider()

    # ── Drill-down: companies in a market ─────────────────────────────────────
    st.subheader("Drill Down — Companies in a Specific Market")
    all_markets = sorted(df["market"].tolist())
    selected_market = st.selectbox("Select market", [""] + all_markets)
    if selected_market:
        cos = get_companies_in_market(selected_market)
        if cos:
            st.write(f"**{len(cos)} companies** with `{selected_market}` operations:")
            st.dataframe(
                pd.DataFrame(cos).rename(columns={"company": "Company"}),
                use_container_width=True, hide_index=True,
            )
        else:
            st.info("No companies found for this market.")
