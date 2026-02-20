"""
ChromaDB integration for the glossary and sentence corpus.

Two collections:
  sec_sentences  — every preprocessed sentence (for semantic retrieval)
  sec_glossary   — every glossary term + definition (for term lookup / similarity)

Usage:
    from glossary.vector_store import VectorStore

    vs = VectorStore()
    vs.index_document(section_doc)
    vs.index_glossary(glossary_store)

    results = vs.search_sentences("cybersecurity risk supply chain", n=10)
    results = vs.search_glossary("annual recurring revenue", n=5)
"""

from __future__ import annotations

import sys
import os
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config
from models.schemas import GlossaryStore, GlossaryTerm, SectionDocument, TaggedSentence


class VectorStore:
    """
    Wraps ChromaDB with two purpose-built collections.
    Uses ChromaDB's built-in embedding model (all-MiniLM-L6-v2) by default —
    no external embedding API needed.
    """

    def __init__(self, persist_dir: Optional[str] = None):
        import chromadb
        persist_dir = persist_dir or config.CHROMA_PERSIST_DIR
        self._client = chromadb.PersistentClient(path=persist_dir)

        self._sentences = self._client.get_or_create_collection(
            name=config.CHROMA_COLLECTION_SENTENCES,
            metadata={"hnsw:space": "cosine"},
        )
        self._glossary = self._client.get_or_create_collection(
            name=config.CHROMA_COLLECTION_GLOSSARY,
            metadata={"hnsw:space": "cosine"},
        )

    # ── Sentence indexing ─────────────────────────────────────────────────────

    def index_document(self, doc: SectionDocument, batch_size: int = 100) -> int:
        """
        Add all sentences from a SectionDocument to the sentence collection.
        Skips sentences already indexed (idempotent via sentence_id).
        Returns count of newly added sentences.
        """
        sentences = doc.sentences
        added = 0

        for i in range(0, len(sentences), batch_size):
            batch = sentences[i : i + batch_size]

            # Check which IDs are already present
            existing_ids = set(
                self._sentences.get(
                    ids=[s.sentence_id for s in batch],
                    include=[],
                ).get("ids", [])
            )

            new_batch = [s for s in batch if s.sentence_id not in existing_ids]
            if not new_batch:
                continue

            self._sentences.add(
                ids=[s.sentence_id for s in new_batch],
                documents=[s.text for s in new_batch],
                metadatas=[
                    {
                        "cik":              s.cik,
                        "ticker":           s.ticker or "",
                        "company_name":     s.company_name,
                        "accession_number": s.accession_number,
                        "filing_date":      str(s.filing_date),
                        "fiscal_year":      str(s.fiscal_year),
                        "section_type":     s.section_type.value,
                        "is_forward_looking": str(s.is_forward_looking),
                        "has_company_coref":  str(s.has_company_coref),
                        "word_count":       str(s.word_count),
                    }
                    for s in new_batch
                ],
            )
            added += len(new_batch)

        return added

    def search_sentences(
        self,
        query: str,
        n: int = 10,
        where: Optional[dict] = None,
    ) -> list[dict]:
        """
        Semantic search over indexed sentences.

        Args:
            query:  Natural language query.
            n:      Number of results to return.
            where:  ChromaDB metadata filter (e.g. {"section_type": "risk_factors"}).

        Returns:
            List of dicts with keys: id, text, metadata, distance.
        """
        kwargs = {"query_texts": [query], "n_results": min(n, self._sentences.count())}
        if where:
            kwargs["where"] = where

        results = self._sentences.query(
            include=["documents", "metadatas", "distances"],
            **kwargs,
        )
        return self._format_results(results)

    # ── Glossary indexing ─────────────────────────────────────────────────────

    def index_glossary(self, store: GlossaryStore) -> int:
        """
        Index all glossary terms. Idempotent — skips existing IDs.
        Returns count of newly added terms.
        """
        added = 0
        items = list(store.terms.items())

        for term_key, term in items:
            term_id = f"glossary_{term_key}"
            existing = self._glossary.get(ids=[term_id], include=[])
            if existing.get("ids"):
                continue

            text = term.term
            if term.definition:
                text = f"{term.term}: {term.definition}"
            elif term.expansion:
                text = f"{term.term} ({term.expansion})"

            self._glossary.add(
                ids=[term_id],
                documents=[text],
                metadatas=[
                    {
                        "term":          term.term,
                        "aliases":       ", ".join(term.aliases),
                        "is_acronym":    str(term.is_acronym),
                        "expansion":     term.expansion or "",
                        "frequency":     str(term.frequency),
                        "section_scope": ", ".join(s.value for s in term.section_scope),
                        "domain_tags":   ", ".join(t.value for t in term.domain_tags),
                        "definition":    term.definition or "",
                    }
                ],
            )
            added += 1

        return added

    def search_glossary(
        self,
        query: str,
        n: int = 5,
    ) -> list[dict]:
        """Semantic lookup over the glossary collection."""
        count = self._glossary.count()
        if count == 0:
            return []
        results = self._glossary.query(
            query_texts=[query],
            n_results=min(n, count),
            include=["documents", "metadatas", "distances"],
        )
        return self._format_results(results)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _format_results(raw: dict) -> list[dict]:
        out = []
        ids       = raw.get("ids",       [[]])[0]
        docs      = raw.get("documents", [[]])[0]
        metas     = raw.get("metadatas", [[]])[0]
        distances = raw.get("distances", [[]])[0]
        for id_, doc, meta, dist in zip(ids, docs, metas, distances):
            out.append({
                "id":       id_,
                "text":     doc,
                "metadata": meta,
                "distance": dist,
            })
        return out

    def sentence_count(self) -> int:
        return self._sentences.count()

    def glossary_count(self) -> int:
        return self._glossary.count()
