"""
SEC KG Chatbot — Streamlit UI.

Run from repo root:
    streamlit run python/chatbot/app.py --server.port 8501 --server.address 0.0.0.0

Access from Windows: http://192.168.1.39:8501
"""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import streamlit as st

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="SEC KG Chat",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Lazy imports (avoid re-importing on every rerun) ──────────────────────────
@st.cache_resource
def load_pipeline(provider: str):
    from models.llm_client import LLMClient
    from chatbot.router import Router
    from chatbot.graph_qa import GraphQA
    from chatbot.semantic_qa import SemanticQA
    from chatbot.synthesiser import Synthesiser

    llm = LLMClient(provider=provider)
    return {
        "router":      Router(llm),
        "graph_qa":    GraphQA(llm),
        "semantic_qa": SemanticQA(),
        "synthesiser": Synthesiser(llm),
    }


# ── Session state ─────────────────────────────────────────────────────────────
if "state" not in st.session_state:
    from chatbot.memory import ConversationState
    _state = ConversationState()
    _state.load()
    st.session_state.state = _state

if "messages" not in st.session_state:
    # Restore visual history from loaded conversation turns
    msgs = []
    for t in st.session_state.state.turns:
        msgs.append({"role": "user", "content": t.question})
        msgs.append({"role": "assistant", "content": t.answer, "cypher": t.cypher, "sources": ""})
    st.session_state.messages = msgs


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("SEC KG Chat")
    st.caption("Ask questions about 10-K filings")

    page = st.radio(
        "Page",
        [
            "Chat",
            "Pipeline Status",
            "Dataset Statistics",
            "Semantic Search",
            "Company Profile",
            "Geographic Exposure",
            "Sentiment Tracker",
            "Company Comparison",
        ],
        label_visibility="collapsed",
    )

    st.divider()

    provider = st.selectbox(
        "LLM provider",
        ["ollama", "anthropic", "openai"],
        index=0,
        help="Switch LLM backend. Ollama runs locally.",
    )

    st.divider()
    st.subheader("Active context")
    s = st.session_state.state
    st.markdown(f"**Company:** {s.active_company_name or '—'}")
    st.markdown(f"**Years:** {s.active_year_from or '—'} – {s.active_year_to or '—'}")
    st.markdown(f"**Topic:** {s.active_topic or '—'}")

    if st.button("Clear context"):
        from chatbot.memory import ConversationState, SESSION_FILE
        st.session_state.state = ConversationState()
        st.session_state.messages = []
        if os.path.exists(SESSION_FILE):
            os.remove(SESSION_FILE)
        st.rerun()

    # Export conversation to markdown
    if st.session_state.get("messages"):
        from datetime import datetime as _dt
        def _build_markdown():
            lines = [f"# SEC KG Chat export — {_dt.now().strftime('%Y-%m-%d %H:%M')}\n"]
            for msg in st.session_state.messages:
                role = "**You**" if msg["role"] == "user" else "**Assistant**"
                lines.append(f"{role}\n\n{msg['content']}\n")
                if msg.get("cypher"):
                    lines.append(f"```cypher\n{msg['cypher']}\n```\n")
                if msg.get("sources"):
                    lines.append(f"*Sources:* {msg['sources']}\n")
                lines.append("---\n")
            return "\n".join(lines)

        st.download_button(
            label="Export to Markdown",
            data=_build_markdown(),
            file_name=f"sec_chat_{_dt.now().strftime('%Y%m%d_%H%M')}.md",
            mime="text/markdown",
        )

    st.divider()
    st.subheader("Example questions")
    examples = [
        "What companies are in the graph?",
        "What geographic markets does Tyson Foods operate in?",
        "Which companies mention China in their filings?",
        "What are the most common competitors mentioned?",
        "Show me supply chain risk mentions",
    ]
    for ex in examples:
        if st.button(ex, key=f"ex_{ex[:20]}"):
            st.session_state["prefill"] = ex


# ── Non-chat pages ────────────────────────────────────────────────────────────
if page == "Pipeline Status":
    from chatbot.page_pipeline_status import render_pipeline_status
    render_pipeline_status()
    st.stop()

if page == "Dataset Statistics":
    from chatbot.stats_page import render_stats
    render_stats()
    st.stop()

if page == "Semantic Search":
    from chatbot.page_semantic_search import render_semantic_search
    render_semantic_search()
    st.stop()

if page == "Company Profile":
    from chatbot.page_company_profile import render_company_profile
    render_company_profile()
    st.stop()

if page == "Geographic Exposure":
    from chatbot.page_geo_heatmap import render_geo_heatmap
    render_geo_heatmap()
    st.stop()

if page == "Sentiment Tracker":
    from chatbot.page_sentiment_tracker import render_sentiment_tracker
    render_sentiment_tracker()
    st.stop()

if page == "Company Comparison":
    from chatbot.page_comparison import render_comparison
    render_comparison()
    st.stop()


# ── Main chat area ────────────────────────────────────────────────────────────
st.header("SEC Knowledge Graph Chat")

# Render history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("cypher"):
            with st.expander("Cypher query"):
                st.code(msg["cypher"], language="cypher")
        if msg.get("sources"):
            with st.expander("Sources"):
                st.markdown(msg["sources"])
        if msg.get("graph_html"):
            with st.expander("Graph view"):
                import streamlit.components.v1 as components
                components.html(msg["graph_html"], height=480, scrolling=False)


# Input
prefill = st.session_state.pop("prefill", "")
question = st.chat_input("Ask a question about SEC filings...", key="chat_input")
if not question and prefill:
    question = prefill


if question:
    # Show user message immediately
    with st.chat_message("user"):
        st.markdown(question)
    st.session_state.messages.append({"role": "user", "content": question})

    # Run pipeline
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                pipe = load_pipeline(provider)
                state = st.session_state.state

                # 1. Route
                routing = pipe["router"].route(question, state)

                # 2. Graph QA
                cypher, graph_rows = pipe["graph_qa"].run(question, routing)

                # 3. Semantic QA
                sem_hits = pipe["semantic_qa"].search(
                    question,
                    company_name=routing.get("company"),
                    year_from=(routing.get("years") or [None])[0],
                    year_to=(routing.get("years") or [None, None])[1] if routing.get("years") else None,
                )

                # 4. Format context
                from chatbot.graph_qa import format_graph_rows
                from chatbot.semantic_qa import format_semantic_hits
                graph_facts  = format_graph_rows(graph_rows)
                sem_text     = format_semantic_hits(sem_hits)

                # 5. Synthesise
                answer = pipe["synthesiser"].answer(
                    question, graph_facts, sem_text, state,
                    primary_source=routing.get("primary_source", "graph"),
                )

                # 6. Update state
                from chatbot.memory import Turn
                state.update_context(routing)
                state.add_turn(Turn(
                    question=question,
                    answer=answer,
                    cypher=cypher,
                    graph_rows=graph_rows,
                    semantic_hits=sem_hits,
                ))
                state.save()

                # 7. Display
                st.markdown(answer)

                sources_md = ""
                if sem_hits:
                    sources_md = "**Filing excerpts used:**\n"
                    for h in sem_hits[:4]:
                        sources_md += f"- [{h['company']}, FY{h['year']}, {h['section']}] — score {h['score']}\n"

                if cypher:
                    with st.expander("Cypher query"):
                        st.code(cypher, language="cypher")
                if sources_md:
                    with st.expander("Sources"):
                        st.markdown(sources_md)

                # Graph panel — fetch subgraph and render pyvis
                graph_html = None
                try:
                    from chatbot.graph_panel import fetch_subgraph, build_pyvis_html
                    sg_nodes, sg_edges = fetch_subgraph(routing)
                    graph_html = build_pyvis_html(sg_nodes, sg_edges)
                except Exception:
                    pass
                if graph_html:
                    with st.expander("Graph view", expanded=False):
                        import streamlit.components.v1 as components
                        components.html(graph_html, height=480, scrolling=False)

                st.session_state.messages.append({
                    "role": "assistant",
                    "content": answer,
                    "cypher": cypher,
                    "sources": sources_md,
                    "graph_html": graph_html,
                })

            except Exception as e:
                err = f"Pipeline error: {e}"
                st.error(err)
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": err,
                })
