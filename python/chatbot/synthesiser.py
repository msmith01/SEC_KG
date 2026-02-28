"""
Answer synthesiser — merges graph facts and semantic passages into a
grounded natural-language answer.
"""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from models.llm_client import LLMClient
from chatbot.memory import ConversationState
from chatbot.prompts import SYNTHESISER_SYSTEM, SYNTHESISER_TEMPLATE


class Synthesiser:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def answer(
        self,
        question: str,
        graph_facts: str,
        semantic_hits: str,
        state: ConversationState,
        primary_source: str = "graph",
    ) -> str:
        # For narrative/MD&A questions, lead with filing excerpts
        if primary_source == "semantic":
            primary_block   = f"--- FILING EXCERPTS (primary source) ---\n{semantic_hits}"
            secondary_block = f"--- GRAPH FACTS (supplementary) ---\n{graph_facts}"
            source_note     = "Prioritise the filing excerpts for this answer. Graph data is supplementary."
        else:
            primary_block   = f"--- GRAPH FACTS ---\n{graph_facts}"
            secondary_block = f"--- FILING EXCERPTS ---\n{semantic_hits}"
            source_note     = "Prioritise graph facts. Use filing excerpts to add detail."

        prompt = SYNTHESISER_TEMPLATE.format(
            question=question,
            context_summary=state.context_summary(),
            primary_block=primary_block,
            secondary_block=secondary_block,
            source_note=source_note,
            history=state.history_text(),
        )
        return self.llm.complete(
            prompt,
            system=SYNTHESISER_SYSTEM,
            max_tokens=1024,
            temperature=0.2,
        )
