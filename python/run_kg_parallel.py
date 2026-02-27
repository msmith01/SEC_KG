#!/usr/bin/env python3
"""
Parallel KG population — N extractor workers + 1 writer process.

Architecture (producer-consumer):
    Worker-0 ──┐
    Worker-1 ──┤
    Worker-2 ──┼──► Queue ──► Writer ──► Neo4j
    ...        │
    Worker-N ──┘

Workers run spaCy NER in parallel (CPU-bound).
A single Writer serialises all Neo4j writes — zero deadlock risk.

Usage:
    # Dry run — no Neo4j writes
    python python/run_kg_parallel.py --dry-run --workers 4 --limit 40

    # Full fast run (spaCy NER), 8 extraction workers
    python python/run_kg_parallel.py --workers 8

    # One section only
    python python/run_kg_parallel.py --workers 8 --section risk_factors

    # Check progress
    python python/run_kg_parallel.py --status
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(_REPO_ROOT))

import config
from models.schemas import SectionType

_CHECKPOINT_DIR   = config.KG_EXPORT_DIR
_MAIN_CHECKPOINT  = _CHECKPOINT_DIR / ".checkpoint_fast.json"
_SECTION_ID_RE    = re.compile(rb'"section_id"\s*:\s*"([^"]+)"')

_SENTINEL = None   # signals worker is done


# ── File enumeration ──────────────────────────────────────────────────────────

def _iter_doc_files(section_type: Optional[SectionType]):
    """Yield (section_id, path_str) for all preprocessed docs."""
    sections = [section_type] if section_type else list(SectionType)
    for sec in sections:
        sec_dir = config.PREPROCESSED_DIR / sec.value
        if not sec_dir.exists():
            continue
        for jf in sorted(sec_dir.glob("*.json")):
            try:
                with jf.open("rb") as fh:
                    m = _SECTION_ID_RE.search(fh.read(100))
                if m:
                    yield m.group(1).decode(), str(jf)
            except Exception:
                pass


# ── Extractor worker ──────────────────────────────────────────────────────────

def _extractor_worker(
    worker_id: int,
    file_pairs: list[tuple[str, str]],
    out_queue: mp.Queue,
):
    """
    Load spaCy, run NER + normalise over the given file list, push results
    to out_queue.  Pushes _SENTINEL when finished.
    """
    sys.path.insert(0, str(_REPO_ROOT))

    from kg_population.ner_extractor import NERExtractor
    from kg_population.normaliser import Normaliser
    from models.schemas import SectionDocument

    from collections import defaultdict
    from kg_population.writer import _LABEL_MAP
    from ontology.neo4j_schema import node_to_props

    prefix = f"[extractor-{worker_id}]"
    extractor = NERExtractor()

    for section_id, json_path in file_pairs:
        try:
            doc = SectionDocument.model_validate_json(Path(json_path).read_text())
            raw = extractor.extract(doc)
            normaliser = Normaliser(doc, extraction_method="spacy")
            nodes, edges = normaliser.normalise(raw)

            # Serialise to plain dicts here (in the extractor, parallelised)
            # so the queue carries lightweight data, not heavy Pydantic objects.
            nodes_by_label: dict = defaultdict(list)
            for node in nodes:
                label = _LABEL_MAP.get(type(node))
                if label:
                    props = node_to_props(node)
                    nodes_by_label[label].append(
                        {k: v for k, v in props.items() if v is not None}
                    )

            edges_by_type: dict = defaultdict(list)
            for edge in edges:
                edges_by_type[edge.relation_type.value].append({
                    "subject_id":  edge.subject_id,
                    "object_id":   edge.object_id,
                    "filing_ref":  edge.filing_ref,
                    "as_of_year":  edge.as_of_year,
                    "confidence":  edge.provenance.confidence,
                    "sentence_id": edge.provenance.sentence_id,
                    "weight":      edge.weight,
                })

            out_queue.put({
                "section_id":        section_id,
                "nodes_by_label":    dict(nodes_by_label),
                "edges_by_type":     dict(edges_by_type),
                "accession_number":  doc.metadata.accession_number,
                "fiscal_year":       doc.metadata.fiscal_year,
                "company_name":      doc.metadata.company_name,
            })

        except Exception as e:
            print(f"{prefix} ERROR {section_id}: {e}", file=sys.stderr, flush=True)
            # Push a failed marker so writer knows to skip checkpointing this one
            out_queue.put({
                "section_id": section_id,
                "error": str(e),
            })

    out_queue.put(_SENTINEL)
    print(f"{prefix} Done.", flush=True)


# ── Writer process ────────────────────────────────────────────────────────────

def _writer_process(
    n_workers: int,
    out_queue: mp.Queue,
    checkpoint_path_str: str,
    dry_run: bool,
    total_pending: int,
):
    """
    Single process that drains out_queue and writes to Neo4j.
    Exits when it has received n_workers sentinels (one per extractor).
    """
    sys.path.insert(0, str(_REPO_ROOT))

    from ontology.neo4j_schema import Neo4jGraph

    checkpoint_path = Path(checkpoint_path_str)
    done: set[str] = set()
    if checkpoint_path.exists():
        try:
            done = set(json.loads(checkpoint_path.read_text()))
        except Exception:
            pass

    graph = None
    if not dry_run:
        graph = Neo4jGraph()

    sentinels_received = 0
    processed = 0
    t_start = time.time()

    try:
        while sentinels_received < n_workers:
            item = out_queue.get()

            if item is _SENTINEL:
                sentinels_received += 1
                continue

            if "error" in item:
                continue

            section_id = item["section_id"]
            if section_id in done:
                continue

            try:
                if graph:
                    graph.write_document(
                        item["nodes_by_label"],
                        item["edges_by_type"],
                        item["accession_number"],
                        item["fiscal_year"],
                    )
                done.add(section_id)
                processed += 1

                if processed % 50 == 0:
                    checkpoint_path.write_text(json.dumps(sorted(done), indent=2))
                    elapsed = time.time() - t_start
                    rate = processed / elapsed
                    remaining = total_pending - processed
                    eta_min = remaining / rate / 60 if rate > 0 else 0
                    print(
                        f"[writer] {processed}/{total_pending} | "
                        f"{rate:.1f} doc/s | ETA {eta_min:.0f}m | "
                        f"{item['company_name']}",
                        flush=True,
                    )

            except Exception as e:
                print(f"[writer] ERROR {section_id}: {e}", file=sys.stderr, flush=True)

    finally:
        checkpoint_path.write_text(json.dumps(sorted(done), indent=2))
        if graph:
            graph.close()


    elapsed = time.time() - t_start
    print(f"[writer] Done. {processed} docs in {elapsed/60:.1f}m.", flush=True)


# ── Status helper ─────────────────────────────────────────────────────────────

def _show_status():
    total = sum(1 for _ in _iter_doc_files(None))
    main_done = set()
    if _MAIN_CHECKPOINT.exists():
        try:
            main_done = set(json.loads(_MAIN_CHECKPOINT.read_text()))
        except Exception:
            pass
    pct = 100 * len(main_done) / total if total else 0
    print(f"Total docs:   {total}")
    print(f"Completed:    {len(main_done)} ({pct:.1f}%)")
    print(f"Remaining:    {total - len(main_done)}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Parallel KG population — N extractors + 1 writer"
    )
    parser.add_argument("--workers", type=int, default=8,
                        help="Number of NER extraction workers (default: 8)")
    parser.add_argument("--section", choices=["business", "risk_factors", "mda"],
                        default=None)
    parser.add_argument("--dry-run", action="store_true",
                        help="Extract but skip Neo4j writes")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max total pending docs to process")
    parser.add_argument("--status", action="store_true",
                        help="Print progress summary and exit")
    args = parser.parse_args()

    if args.status:
        _show_status()
        return

    # Neo4j connectivity + FiscalYear pre-creation
    if not args.dry_run:
        try:
            from ontology.neo4j_schema import Neo4jGraph
            g = Neo4jGraph()
            g.setup_fiscal_years()
            g.close()
            print("Neo4j OK. FiscalYear nodes ready.")
        except Exception as e:
            print(f"ERROR: Cannot connect to Neo4j: {e}", file=sys.stderr)
            sys.exit(1)

    section_type = SectionType(args.section) if args.section else None
    all_files = list(_iter_doc_files(section_type))

    # Load main checkpoint
    main_done: set[str] = set()
    if _MAIN_CHECKPOINT.exists():
        try:
            main_done = set(json.loads(_MAIN_CHECKPOINT.read_text()))
        except Exception:
            pass

    pending = [(sid, p) for sid, p in all_files if sid not in main_done]
    if args.limit:
        pending = pending[:args.limit]

    print(f"Total: {len(all_files)} | Done: {len(main_done)} | Pending: {len(pending)}")

    if not pending:
        print("Nothing to do.")
        return

    n_workers = min(args.workers, len(pending))

    # Shuffle so same-company docs are spread across workers' queues
    import random
    rng = random.Random(42)
    rng.shuffle(pending)

    # Distribute round-robin
    shards: list[list[tuple[str, str]]] = [[] for _ in range(n_workers)]
    for i, pair in enumerate(pending):
        shards[i % n_workers].append(pair)

    sizes = [len(s) for s in shards]
    print(f"Workers: {n_workers} | Shards: {min(sizes)}–{max(sizes)} docs each")

    # Inter-process queue — bounded to avoid unbounded RAM use
    # (spaCy output for a 600-sentence doc is ~a few KB of dicts)
    queue_size = n_workers * 4
    ctx = mp.get_context("fork")
    out_queue = ctx.Queue(maxsize=queue_size)

    # Start writer process
    writer_proc = ctx.Process(
        target=_writer_process,
        args=(n_workers, out_queue, str(_MAIN_CHECKPOINT), args.dry_run, len(pending)),
        daemon=False,
    )
    writer_proc.start()

    # Start extractor workers
    worker_procs = []
    for i in range(n_workers):
        p = ctx.Process(
            target=_extractor_worker,
            args=(i, shards[i], out_queue),
            daemon=False,
        )
        p.start()
        worker_procs.append(p)

    print(f"Writer PID: {writer_proc.pid} | "
          f"Worker PIDs: {[p.pid for p in worker_procs]}")
    print("Monitor: python python/run_kg_parallel.py --status")

    t0 = time.time()
    for p in worker_procs:
        p.join()
    writer_proc.join()

    elapsed = time.time() - t0
    print(f"\nAll done in {elapsed/60:.1f}m.")

    # Report final state
    _show_status()


if __name__ == "__main__":
    main()
