"""
Forward-Looking Sentiment Tracker — management confidence across companies and years.

Loads all ChromaDB sentence metadata (metadata-only, no text) and aggregates
% forward-looking sentences as a proxy for management confidence.
"""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from collections import defaultdict

import streamlit as st
import pandas as pd
import config


@st.cache_resource
def _get_collection():
    import chromadb
    try:
        client = chromadb.PersistentClient(path=str(config.CHROMA_PERSIST_DIR))
        return client.get_collection(config.CHROMA_COLLECTION_SENTENCES)
    except Exception:
        return None


@st.cache_data(ttl=3600)
def load_aggregated_sentiment() -> pd.DataFrame:
    """
    Paginate through all ChromaDB metadata (no document text) and return a
    DataFrame with one row per company×year: Sentences, FwdLooking, PctFwd.
    Cached for 1 hour — first load takes ~30-60s for 397k records.
    """
    col = _get_collection()
    if col is None:
        return pd.DataFrame()

    year_company_total: dict = defaultdict(lambda: defaultdict(int))
    year_company_fwd:   dict = defaultdict(lambda: defaultdict(int))

    batch_size = 10_000
    offset = 0
    total = col.count()
    progress = st.progress(0, text=f"Loading sentence metadata (0/{total:,})...")

    while offset < total:
        try:
            result = col.get(include=["metadatas"], limit=batch_size, offset=offset)
        except Exception:
            break

        metas = result.get("metadatas", [])
        if not metas:
            break

        for m in metas:
            company = m.get("company_name")
            yr = m.get("fiscal_year")
            if company and yr:
                year_company_total[yr][company] += 1
                if m.get("is_forward_looking"):
                    year_company_fwd[yr][company] += 1

        offset += len(metas)
        pct = min(offset / max(total, 1), 1.0)
        progress.progress(pct, text=f"Loading... {offset:,}/{total:,}")
        if len(metas) < batch_size:
            break

    progress.empty()

    rows = []
    for yr in sorted(year_company_total.keys()):
        for company in year_company_total[yr]:
            tot = year_company_total[yr][company]
            fwd = year_company_fwd[yr].get(company, 0)
            rows.append({
                "Year": yr,
                "Company": company,
                "Sentences": tot,
                "FwdLooking": fwd,
                "PctFwd": round(100 * fwd / tot, 1) if tot else 0.0,
            })

    return pd.DataFrame(rows)


def render_sentiment_tracker():
    st.header("Forward-Looking Sentiment Tracker")
    st.caption(
        "% of sentences using forward-looking language (will, expect, anticipate, plan, etc.) "
        "as a proxy for management confidence. Higher = more bullish outlook."
    )

    # ── Load aggregated data (cached 1 hr) ────────────────────────────────────
    df = load_aggregated_sentiment()
    if df.empty:
        st.error("Could not load sentiment data from ChromaDB.")
        return

    n_companies = df["Company"].nunique()
    n_years     = df["Year"].nunique()
    n_sentences = int(df["Sentences"].sum())

    c1, c2, c3 = st.columns(3)
    c1.metric("Companies", f"{n_companies:,}")
    c2.metric("Fiscal Years", n_years)
    c3.metric("Total Sentences", f"{n_sentences:,}")

    st.divider()

    # ── Tabs ──────────────────────────────────────────────────────────────────
    tab1, tab2, tab3 = st.tabs([
        "Corpus Trend",
        "Rankings by Year",
        "Track Companies",
    ])

    # ── Tab 1: Corpus-level trend ─────────────────────────────────────────────
    with tab1:
        st.subheader("Overall Forward-Looking % by Year")
        st.caption("Aggregated across all companies — higher bars = more bullish corpus-wide.")

        year_agg = (
            df.groupby("Year")
            .agg(Sentences=("Sentences", "sum"), FwdLooking=("FwdLooking", "sum"))
            .reset_index()
        )
        year_agg["PctFwd"] = (
            100 * year_agg["FwdLooking"] / year_agg["Sentences"].clip(lower=1)
        ).round(1)

        try:
            import plotly.express as px
            fig = px.bar(
                year_agg, x="Year", y="PctFwd",
                title="S&P 500 corpus — % forward-looking sentences per year",
                labels={"PctFwd": "% Forward-Looking"},
                color="PctFwd",
                color_continuous_scale="RdYlGn",
            )
            fig.update_layout(coloraxis_showscale=False)
            st.plotly_chart(fig, use_container_width=True)
        except ImportError:
            st.bar_chart(year_agg.set_index("Year")["PctFwd"])

        st.dataframe(year_agg, use_container_width=True, hide_index=True)

    # ── Tab 2: Rankings ────────────────────────────────────────────────────────
    with tab2:
        st.subheader("Most / Least Bullish Companies in a Given Year")
        years = sorted(df["Year"].unique(), reverse=True)
        sel_year = st.selectbox("Year", years, key="rank_year")

        df_yr = df[df["Year"] == sel_year].copy()
        # Filter to companies with enough sentences to be meaningful
        min_sentences = st.slider("Min sentences (noise filter)", 5, 100, 20, key="min_sent")
        df_yr = df_yr[df_yr["Sentences"] >= min_sentences].sort_values(
            "PctFwd", ascending=False
        )

        st.caption(f"{len(df_yr)} companies with >= {min_sentences} sentences in {sel_year}")

        col_hi, col_lo = st.columns(2)
        with col_hi:
            st.subheader(f"Top 20 most bullish")
            st.dataframe(
                df_yr.head(20)[["Company", "PctFwd", "Sentences"]].rename(
                    columns={"PctFwd": "% Fwd-Looking"}
                ),
                use_container_width=True, hide_index=True,
            )
        with col_lo:
            st.subheader(f"Top 20 least bullish")
            st.dataframe(
                df_yr.tail(20)[["Company", "PctFwd", "Sentences"]].rename(
                    columns={"PctFwd": "% Fwd-Looking"}
                ),
                use_container_width=True, hide_index=True,
            )

        # Distribution chart
        try:
            import plotly.express as px
            fig2 = px.histogram(
                df_yr, x="PctFwd", nbins=30,
                title=f"Distribution of Forward-Looking % — {sel_year}",
                labels={"PctFwd": "% Forward-Looking"},
            )
            st.plotly_chart(fig2, use_container_width=True)
        except ImportError:
            pass

    # ── Tab 3: Track specific companies ───────────────────────────────────────
    with tab3:
        st.subheader("Track Companies Over Time")
        all_companies = sorted(df["Company"].unique())
        default_cos = all_companies[:4] if len(all_companies) >= 4 else all_companies
        sel_companies = st.multiselect(
            "Select 1–8 companies",
            all_companies,
            default=default_cos,
            max_selections=8,
        )

        if sel_companies:
            df_sel = df[df["Company"].isin(sel_companies)]
            try:
                import plotly.express as px
                fig = px.line(
                    df_sel, x="Year", y="PctFwd", color="Company",
                    markers=True,
                    title="Forward-Looking % over time",
                    labels={"PctFwd": "% Forward-Looking"},
                )
                fig.update_layout(yaxis_range=[0, 100])
                st.plotly_chart(fig, use_container_width=True)
            except ImportError:
                pivot = df_sel.pivot(index="Year", columns="Company", values="PctFwd")
                st.line_chart(pivot)

            with st.expander("Raw data"):
                st.dataframe(
                    df_sel[["Company", "Year", "PctFwd", "Sentences"]].rename(
                        columns={"PctFwd": "% Fwd-Looking"}
                    ).sort_values(["Company", "Year"]),
                    use_container_width=True, hide_index=True,
                )
        else:
            st.info("Select at least one company above.")

    st.divider()
    if st.button("Reload sentiment data (clears 1-hr cache)"):
        load_aggregated_sentiment.clear()
        st.rerun()
