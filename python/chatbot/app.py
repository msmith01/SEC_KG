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
    st.session_state.state = ConversationState()

if "messages" not in st.session_state:
    st.session_state.messages = []   # [{role, content, cypher, sources}]


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("SEC KG Chat")
    st.caption("Ask questions about 10-K filings")

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
        from chatbot.memory import ConversationState
        st.session_state.state = ConversationState()
        st.session_state.messages = []
        st.rerun()

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
                    question, graph_facts, sem_text, state
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

                st.session_state.messages.append({
                    "role": "assistant",
                    "content": answer,
                    "cypher": cypher,
                    "sources": sources_md,
                })

            except Exception as e:
                err = f"Pipeline error: {e}"
                st.error(err)
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": err,
                })
