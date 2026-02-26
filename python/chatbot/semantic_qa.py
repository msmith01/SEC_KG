"""
Semantic search over ChromaDB sentence embeddings.
"""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config


class SemanticQA:
    def __init__(self):
        import chromadb
        self._client = chromadb.PersistentClient(path=config.CHROMA_PERSIST_DIR)
        try:
            self._collection = self._client.get_collection(
                config.CHROMA_COLLECTION_SENTENCES
            )
        except Exception:
            self._collection = None

    def search(
        self,
        question: str,
        company_name: str | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
        n_results: int = 6,
    ) -> list[dict]:
        if self._collection is None:
            return []

        # Build ChromaDB where filter
        where: dict | None = None
        conditions = []
        if company_name:
            conditions.append({"company_name": {"$eq": company_name}})
        if year_from and year_to and year_from != year_to:
            conditions.append({"fiscal_year": {"$gte": year_from}})
            conditions.append({"fiscal_year": {"$lte": year_to}})
        elif year_from:
            conditions.append({"fiscal_year": {"$eq": year_from}})

        if len(conditions) == 1:
            where = conditions[0]
        elif len(conditions) > 1:
            where = {"$and": conditions}

        try:
            results = self._collection.query(
                query_texts=[question],
                n_results=n_results,
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        except Exception:
            # Fall back without filter if company not found in collection
            try:
                results = self._collection.query(
                    query_texts=[question],
                    n_results=n_results,
                    include=["documents", "metadatas", "distances"],
                )
            except Exception:
                return []

        hits = []
        docs      = results.get("documents", [[]])[0]
        metas     = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for doc, meta, dist in zip(docs, metas, distances):
            hits.append({
                "text":     doc,
                "company":  meta.get("company_name", "unknown"),
                "year":     meta.get("fiscal_year", "?"),
                "section":  meta.get("section_type", "?"),
                "score":    round(1 - dist, 3),  # cosine similarity approx
            })

        return hits


def format_semantic_hits(hits: list[dict]) -> str:
    if not hits:
        return "(no relevant filing excerpts found)"
    lines = []
    for h in hits:
        header = f"[{h['company']}, FY{h['year']}, {h['section']}] (relevance: {h['score']})"
        lines.append(f"{header}\n  \"{h['text'][:300]}\"")
    return "\n\n".join(lines)
