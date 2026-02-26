"""
Conversation state — tracks turn history and active context across turns.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Turn:
    question: str
    answer: str
    cypher: str | None = None
    graph_rows: list[dict] = field(default_factory=list)
    semantic_hits: list[dict] = field(default_factory=list)


@dataclass
class ConversationState:
    turns: list[Turn] = field(default_factory=list)
    active_company_name: str | None = None
    active_company_cik:  str | None = None
    active_year_from:    int | None = None
    active_year_to:      int | None = None
    active_topic:        str | None = None
    window_size: int = 8

    def add_turn(self, turn: Turn) -> None:
        self.turns.append(turn)
        if len(self.turns) > self.window_size:
            self.turns = self.turns[-self.window_size:]

    def update_context(self, routing: dict) -> None:
        """Merge router output into active context."""
        if routing.get("company"):
            self.active_company_name = routing["company"]
        if routing.get("cik"):
            self.active_company_cik = routing["cik"]
        years = routing.get("years")
        if years and len(years) == 2:
            self.active_year_from, self.active_year_to = years[0], years[1]
        if routing.get("topic"):
            self.active_topic = routing["topic"]

    def history_text(self) -> str:
        """Last N turns as a plain-text block for prompts."""
        if not self.turns:
            return "(no previous turns)"
        lines = []
        for t in self.turns[-4:]:
            lines.append(f"Q: {t.question}")
            lines.append(f"A: {t.answer[:300]}{'...' if len(t.answer) > 300 else ''}")
        return "\n".join(lines)

    def context_summary(self) -> str:
        parts = []
        if self.active_company_name:
            parts.append(f"Company: {self.active_company_name}")
        if self.active_year_from:
            yr = f"{self.active_year_from}"
            if self.active_year_to and self.active_year_to != self.active_year_from:
                yr += f"–{self.active_year_to}"
            parts.append(f"Years: {yr}")
        if self.active_topic:
            parts.append(f"Topic: {self.active_topic}")
        return ", ".join(parts) if parts else "none"
