"""
Run glossary extraction over preprocessed SectionDocuments.

Usage:
    python python/run_glossary.py                   # LLM + rules
    python python/run_glossary.py --rules-only      # skip LLM (fast)
    python python/run_glossary.py --section risk_factors
    python python/run_glossary.py --index-chroma    # also push to ChromaDB
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import config
from models.schemas import SectionDocument, SectionType
from glossary.extractor import GlossaryBuilder
from glossary.vector_store import VectorStore


def load_preprocessed_docs(section: str | None) -> list[SectionDocument]:
    docs = []
    sections = (
        [SectionType(section)] if section
        else list(SectionType)
    )
    for sec_type in sections:
        sec_dir = config.PREPROCESSED_DIR / sec_type.value
        if not sec_dir.exists():
            continue
        for json_file in sorted(sec_dir.glob("*.json")):
            try:
                doc = SectionDocument.model_validate_json(json_file.read_text())
                docs.append(doc)
            except Exception as e:
                print(f"[run_glossary] Skipping {json_file.name}: {e}", file=sys.stderr)
    return docs


def main():
    parser = argparse.ArgumentParser(description="Glossary extraction pipeline")
    parser.add_argument("--rules-only", action="store_true",
                        help="Skip LLM extraction (fast mode)")
    parser.add_argument("--section", choices=["business", "risk_factors", "mda"],
                        default=None)
    parser.add_argument("--index-chroma", action="store_true",
                        help="Also index sentences and glossary into ChromaDB")
    args = parser.parse_args()

    docs = load_preprocessed_docs(args.section)
    if not docs:
        print("No preprocessed documents found. Run run_preprocessing.py first.")
        sys.exit(1)

    print(f"Loaded {len(docs)} preprocessed documents.")

    builder = GlossaryBuilder(use_llm=not args.rules_only)
    store = builder.process_documents(docs)
    out_path = builder.save()

    print(f"\nGlossary complete: {len(store)} terms → {out_path}")

    if args.index_chroma:
        vs = VectorStore()
        print("\nIndexing sentences into ChromaDB...")
        total_sents = 0
        for doc in docs:
            total_sents += vs.index_document(doc)
        print(f"  Sentences indexed: {total_sents}")

        print("Indexing glossary into ChromaDB...")
        n_terms = vs.index_glossary(store)
        print(f"  Glossary terms indexed: {n_terms}")
        print(f"  ChromaDB sentence count: {vs.sentence_count()}")
        print(f"  ChromaDB glossary count: {vs.glossary_count()}")


if __name__ == "__main__":
    main()
