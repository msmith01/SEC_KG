"""
Semantic Search page — full-text search over 397k ChromaDB sentences.
"""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

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


def render_semantic_search():
    st.header("Semantic Search")
    st.caption("Search across 397k+ filing sentences using semantic similarity.")

    # ── Query + result count ──────────────────────────────────────────────────
    col_q, col_n = st.columns([4, 1])
    with col_q:
        query = st.text_input(
            "Search query",
            placeholder="e.g. supply chain disruption China tariffs",
        )
    with col_n:
        n_results = st.slider("Results", 5, 50, 20)

    # ── Filters ───────────────────────────────────────────────────────────────
    with st.expander("Filters", expanded=False):
        fc1, fc2, fc3, fc4 = st.columns(4)
        with fc1:
            company_filter = st.text_input(
                "Company (exact, UPPERCASE)",
                placeholder="APPLE INC",
            )
        with fc2:
            year_from = st.number_input("Year from", 2010, 2025, 2018, step=1)
            year_to   = st.number_input("Year to",   2010, 2025, 2024, step=1)
        with fc3:
            section_filter = st.selectbox(
                "Section",
                ["All", "risk_factors", "business_description", "management_discussion"],
            )
        with fc4:
            fwd_only = st.checkbox("Forward-looking only")

    if not query:
        st.info("Enter a search query above to get started.")
        return

    collection = _get_collection()
    if collection is None:
        st.error("ChromaDB collection not available.")
        return

    # ── Build where filter ────────────────────────────────────────────────────
    conditions = []
    if company_filter.strip():
        conditions.append({"company_name": {"$eq": company_filter.strip().upper()}})
    if year_from == year_to:
        conditions.append({"fiscal_year": {"$eq": int(year_from)}})
    else:
        conditions.append({"fiscal_year": {"$gte": int(year_from)}})
        conditions.append({"fiscal_year": {"$lte": int(year_to)}})
    if section_filter != "All":
        conditions.append({"section_type": {"$eq": section_filter}})
    if fwd_only:
        conditions.append({"is_forward_looking": {"$eq": True}})

    where = None
    if len(conditions) == 1:
        where = conditions[0]
    elif len(conditions) > 1:
        where = {"$and": conditions}

    # ── Query ChromaDB ────────────────────────────────────────────────────────
    with st.spinner("Searching..."):
        try:
            kwargs = dict(
                query_texts=[query],
                n_results=min(int(n_results), 100),
                include=["documents", "metadatas", "distances"],
            )
            if where:
                kwargs["where"] = where
            results = collection.query(**kwargs)
        except Exception as e:
            st.error(f"Search error: {e}")
            return

    docs  = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    dists = results.get("distances", [[]])[0]

    if not docs:
        st.info("No results. Try relaxing filters or changing your query.")
        return

    st.caption(f"{len(docs)} results")
    st.divider()

    for doc, meta, dist in zip(docs, metas, dists):
        score   = round(1 - dist, 3)
        company = meta.get("company_name", "?")
        year    = meta.get("fiscal_year", "?")
        section = meta.get("section_type", "?")
        fwd     = meta.get("is_forward_looking", False)

        col_l, col_r = st.columns([1, 5])
        with col_l:
            st.metric("Score", score)
            st.caption(f"**{company}**  \nFY{year}  \n{section}")
            if fwd:
                st.caption("forward-looking")
        with col_r:
            st.markdown(f'"{doc}"')
        st.divider()
