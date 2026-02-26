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
import re
import sys
import os
import time
from pathlib import Path
from typing import Iterator, Optional

_SECTION_ID_RE = re.compile(rb'"section_id"\s*:\s*"([^"]+)"')

_CHECKPOINT_FAST = Path(__file__).parent.parent / "data" / "kg_export" / ".checkpoint_fast.json"
_CHECKPOINT_LLM  = Path(__file__).parent.parent / "data" / "kg_export" / ".checkpoint_llm.json"

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
        self._extractor         = NERExtractor() if fast_mode else KGExtractor(llm_client)
        self._dry_run           = dry_run
        self._extraction_method = "spacy" if fast_mode else "llm"
        self._checkpoint_file   = _CHECKPOINT_FAST if fast_mode else _CHECKPOINT_LLM
        self._graph          = None
        self._writer         = None

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
        normaliser = Normaliser(doc, extraction_method=self._extraction_method)
        nodes, edges = normaliser.normalise(raw)

        # 3. Write
        if not self._dry_run and self._writer:
            n_nodes, n_edges = self._writer.write_document(
                nodes, edges,
                doc.metadata.accession_number,
                doc.metadata.fiscal_year,
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
        delay: float = 0.0,
    ) -> list[dict]:
        """
        Process all preprocessed documents (optionally filtered by section type).
        Automatically resumes from the last checkpoint if a previous run was
        interrupted — already-completed section_ids are skipped.

        Loads one document at a time — never holds more than one SectionDocument
        in memory, keeping RAM usage flat regardless of corpus size.

        Args:
            section_type: Process only this section (None = all three).
            limit:        Max number of documents to process (useful for testing).
        """
        done = self._load_checkpoint(self._checkpoint_file)

        # Build pending list from filenames only — no JSON parsing yet
        all_files = list(self._iter_doc_files(section_type))
        if limit:
            all_files = all_files[:limit]
        pending = [(sid, p) for sid, p in all_files if sid not in done]

        skipped = len(all_files) - len(pending)
        if skipped:
            print(f"[kg] Resuming — skipping {skipped} already-completed document(s).")

        results = []
        iterable = tqdm(pending, desc="KG population") if _TQDM else pending

        for i, (section_id, json_file) in enumerate(iterable):
            try:
                # Load one doc at a time — previous doc is GC'd after each iteration
                doc = SectionDocument.model_validate_json(json_file.read_text())
                result = self.run_document(doc)
                results.append(result)
                done.add(section_id)
                if i % 50 == 0 or i == len(pending) - 1:
                    self._save_checkpoint(done, self._checkpoint_file)
                print(
                    f"[kg] {doc.metadata.company_name} "
                    f"({doc.section_type.value}): "
                    f"{result['nodes']} nodes, {result['edges']} edges"
                )
            except Exception as e:
                print(f"[kg] ERROR on {section_id}: {e}", file=sys.stderr)

            if delay > 0:
                time.sleep(delay)

        self._save_checkpoint(done, self._checkpoint_file)
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
    def _iter_doc_files(
        section_type: Optional[SectionType],
    ) -> Iterator[tuple[str, Path]]:
        """
        Yield (section_id, json_file) pairs for all preprocessed documents.
        Reads only the first 100 bytes of each file to extract section_id —
        8x faster than full JSON parsing, uses negligible memory.
        """
        sections = [section_type] if section_type else list(SectionType)
        for sec in sections:
            sec_dir = config.PREPROCESSED_DIR / sec.value
            if not sec_dir.exists():
                continue
            for json_file in sorted(sec_dir.glob("*.json")):
                try:
                    with json_file.open("rb") as fh:
                        match = _SECTION_ID_RE.search(fh.read(100))
                    if match:
                        yield match.group(1).decode(), json_file
                    else:
                        print(f"[kg] Skipping {json_file.name}: section_id not found", file=sys.stderr)
                except Exception as e:
                    print(f"[kg] Skipping {json_file.name}: {e}", file=sys.stderr)

    # ── Checkpoint helpers ────────────────────────────────────────────────────

    @staticmethod
    def _load_checkpoint(path: Path) -> set[str]:
        """Return the set of section_ids that have already been processed."""
        if path.exists():
            try:
                return set(json.loads(path.read_text()))
            except Exception:
                pass
        return set()

    @staticmethod
    def _save_checkpoint(done: set[str], path: Path) -> None:
        """Persist the set of completed section_ids to disk."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(sorted(done), indent=2))

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
