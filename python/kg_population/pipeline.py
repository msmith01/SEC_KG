"""
End-to-end KG population pipeline for one section document.

Stages:
  1. KGExtractor  — LLM extracts raw entity/relation dicts
  2. Normaliser   — maps raw dicts to typed ontology nodes/edges
  3. GraphWriter  — upserts nodes and edges into Neo4j

Usage:
    from kg_population.pipeline import KGPopulationPipeline

    pipe = KGPopulationPipeline()
    pipe.run_document(doc)
    pipe.run_all(section_type=SectionType.RISK_FACTORS)
"""

from __future__ import annotations

import json
import sys
import os
from pathlib import Path
from typing import Optional

_CHECKPOINT_FILE = Path(__file__).parent.parent / "data" / "kg_export" / ".checkpoint.json"

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config
from models.schemas import SectionDocument, SectionType
from models.llm_client import LLMClient
from ontology.neo4j_schema import Neo4jGraph
from kg_population.extractor import KGExtractor
from kg_population.ner_extractor import NERExtractor
from kg_population.normaliser import Normaliser
from kg_population.writer import GraphWriter

try:
    from tqdm import tqdm
    _TQDM = True
except ImportError:
    _TQDM = False


class KGPopulationPipeline:
    """
    Orchestrates extraction → normalisation → Neo4j write for a section.
    """

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        graph: Optional[Neo4jGraph] = None,
        dry_run: bool = False,
        fast_mode: bool = False,
    ):
        """
        Args:
            llm_client: LLM client to use for extraction.
            graph:      Neo4j graph connection. If None and not dry_run,
                        opens a connection using config settings.
            dry_run:    If True, runs extraction and normalisation but skips
                        Neo4j writes. Useful for debugging.
            fast_mode:  Use spaCy NER instead of the LLM extractor. Much
                        faster — no GPU/API required. Good for demos and
                        initial graph population.
        """
        self._extractor = NERExtractor() if fast_mode else KGExtractor(llm_client)
        self._dry_run   = dry_run
        self._graph     = None
        self._writer    = None

        if not dry_run:
            self._graph  = graph or Neo4jGraph()
            self._writer = GraphWriter(self._graph)

    # ── Single document ───────────────────────────────────────────────────────

    def run_document(self, doc: SectionDocument) -> dict:
        """
        Run the full pipeline on one SectionDocument.

        Returns:
            {"nodes": int, "edges": int, "section_id": str}
        """
        # 1. Extract
        raw = self._extractor.extract(doc)

        # 2. Normalise
        normaliser = Normaliser(doc)
        nodes, edges = normaliser.normalise(raw)

        # 3. Write
        if not self._dry_run and self._writer:
            n_nodes, n_edges = self._writer.write(nodes, edges)
            # Ensure FiscalYear node exists and Filing is linked to it
            fiscal_year = doc.metadata.fiscal_year
            self._writer.ensure_fiscal_year_chain(fiscal_year)
            self._writer.link_filing_to_fiscal_year(
                doc.metadata.accession_number, fiscal_year
            )
        else:
            n_nodes = len(nodes)
            n_edges = len(edges)
            if self._dry_run:
                self._dump_dry_run(doc.section_id, nodes, edges)

        return {
            "section_id": doc.section_id,
            "nodes":      n_nodes,
            "edges":      n_edges,
        }

    # ── Batch run ─────────────────────────────────────────────────────────────

    def run_all(
        self,
        section_type: Optional[SectionType] = None,
        limit: Optional[int] = None,
    ) -> list[dict]:
        """
        Process all preprocessed documents (optionally filtered by section type).
        Automatically resumes from the last checkpoint if a previous run was
        interrupted — already-completed section_ids are skipped.

        Args:
            section_type: Process only this section (None = all three).
            limit:        Max number of documents to process (useful for testing).
        """
        docs = self._load_preprocessed_docs(section_type)
        if limit:
            docs = docs[:limit]

        done = self._load_checkpoint()
        pending = [d for d in docs if d.section_id not in done]
        skipped = len(docs) - len(pending)
        if skipped:
            print(f"[kg] Resuming — skipping {skipped} already-completed document(s).")

        results = []
        iterable = tqdm(pending, desc="KG population") if _TQDM else pending

        for doc in iterable:
            try:
                result = self.run_document(doc)
                results.append(result)
                done.add(doc.section_id)
                self._save_checkpoint(done)
                print(
                    f"[kg] {doc.metadata.company_name} "
                    f"({doc.section_type.value}): "
                    f"{result['nodes']} nodes, {result['edges']} edges"
                )
            except Exception as e:
                print(f"[kg] ERROR on {doc.section_id}: {e}", file=sys.stderr)

        return results

    def apply_schema(self) -> None:
        """Apply Neo4j constraints and indexes (call once before first run)."""
        if self._graph:
            self._graph.apply_schema()
        else:
            print("[kg] Dry-run mode: schema not applied.", file=sys.stderr)

    def close(self) -> None:
        if self._graph:
            self._graph.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _load_preprocessed_docs(
        section_type: Optional[SectionType],
    ) -> list[SectionDocument]:
        docs = []
        sections = (
            [section_type] if section_type
            else list(SectionType)
        )
        for sec in sections:
            sec_dir = config.PREPROCESSED_DIR / sec.value
            if not sec_dir.exists():
                continue
            for json_file in sorted(sec_dir.glob("*.json")):
                try:
                    doc = SectionDocument.model_validate_json(json_file.read_text())
                    docs.append(doc)
                except Exception as e:
                    print(f"[kg] Skipping {json_file.name}: {e}", file=sys.stderr)
        return docs

    # ── Checkpoint helpers ────────────────────────────────────────────────────

    @staticmethod
    def _load_checkpoint() -> set[str]:
        """Return the set of section_ids that have already been processed."""
        if _CHECKPOINT_FILE.exists():
            try:
                return set(json.loads(_CHECKPOINT_FILE.read_text()))
            except Exception:
                pass
        return set()

    @staticmethod
    def _save_checkpoint(done: set[str]) -> None:
        """Persist the set of completed section_ids to disk."""
        _CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CHECKPOINT_FILE.write_text(json.dumps(sorted(done), indent=2))

    def _dump_dry_run(self, section_id: str, nodes: list, edges: list) -> None:
        """Write dry-run output to data/kg_export/ for inspection."""
        out = {
            "section_id": section_id,
            "nodes": [
                {"type": type(n).__name__, "node_id": n.node_id}
                for n in nodes
            ],
            "edges": [
                {
                    "subject": e.subject_id,
                    "relation": e.relation_type.value,
                    "object": e.object_id,
                }
                for e in edges
            ],
        }
        out_path = config.KG_EXPORT_DIR / f"{section_id}_dryrun.json"
        out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"[kg] Dry-run output → {out_path}")
