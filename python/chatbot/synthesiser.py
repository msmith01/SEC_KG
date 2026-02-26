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
    ) -> str:
        prompt = SYNTHESISER_TEMPLATE.format(
            question=question,
            context_summary=state.context_summary(),
            graph_facts=graph_facts,
            semantic_hits=semantic_hits,
            history=state.history_text(),
        )
        return self.llm.complete(
            prompt,
            system=SYNTHESISER_SYSTEM,
            max_tokens=1024,
            temperature=0.2,
        )
