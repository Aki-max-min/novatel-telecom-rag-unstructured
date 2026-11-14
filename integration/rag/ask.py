"""
Interactive CLI for integration.rag.pipeline. Loads both retrievers and the
Ollama model ONCE, then loops: read a query from stdin, call the existing
RagPipeline.run_query() unchanged, print the answer/citations/evidence/
latency. Type 'exit' or 'quit' to stop.

Does not modify fuse.py, generate.py, or any retriever -- this file only calls
RagPipeline. With no flags it behaves exactly as before. Optional flags (all off
by default):

    --semantic-layer on|off      ontology term normalisation + one-hop graph expansion
    --budget-db N --budget-doc N per-source context budget (both required together)
    --include-scifact            keep SciFact chunks (they are excluded by default)
"""

import argparse
import re
import time

from integration.rag.pipeline import RagPipeline
from integration.rag.rag_config import RagConfig

CITATION_RE = re.compile(r"\[(E\d+)\]")


def _print_evidence(evidence: list[dict]) -> None:
    if not evidence:
        print("  (no evidence retrieved)")
        return
    for item in evidence:
        metadata = item.get("metadata", {}) or {}
        provenance = metadata.get("provenance", {}) or {}
        page = provenance.get("page_number")
        page_part = f", page={page}" if page is not None else ""
        print(f"  [{item['id']}] source={item['source']} dataset={item['dataset']} "
              f"record_id={item['record_id']}{page_part}")
        print(f"        provenance: {item['provenance_label']}")


def _print_citations(answer: str) -> None:
    cited = sorted(set(CITATION_RE.findall(answer)))
    if cited:
        print(f"  Cited evidence ids: {', '.join(cited)}")
    else:
        print("  No [Ek] citations found in the answer.")


def _looks_like_abstention(answer: str) -> bool:
    lowered = answer.lower()
    return "abstain" in lowered or "don't have enough evidence" in lowered or "not enough information" in lowered


def parse_args(argv=None) -> RagConfig:
    ap = argparse.ArgumentParser(description="Interactive NovaTel RAG CLI")
    ap.add_argument("--semantic-layer", choices=["on", "off"], default="off")
    ap.add_argument("--budget-db", type=int, default=None, help="database blocks in the prompt (use with --budget-doc)")
    ap.add_argument("--budget-doc", type=int, default=None, help="document blocks in the prompt (use with --budget-db)")
    ap.add_argument("--include-scifact", action="store_true", help="do not filter SciFact chunks out")
    args = ap.parse_args(argv)
    kwargs = {"semantic_layer": args.semantic_layer == "on", "budget_db_blocks": args.budget_db,
              "budget_doc_blocks": args.budget_doc}
    if args.include_scifact:
        kwargs["exclude_scifact"] = False
    return RagConfig(**kwargs)


def main() -> None:
    config = parse_args()
    print("Loading retrievers and local LLM (this happens once)...")
    pipeline = RagPipeline(config=config)
    print(f"Ready. Model: {pipeline.llm_client.model}. Type a query, or 'exit'/'quit' to stop.\n")

    try:
        while True:
            try:
                question = input("Query> ").strip()
            except EOFError:
                break

            if not question:
                continue
            if question.lower() in ("exit", "quit"):
                break

            start = time.perf_counter()
            result = pipeline.run_query(question)
            elapsed = time.perf_counter() - start

            print("\n--- ANSWER ---")
            print(result["answer"])

            if _looks_like_abstention(result["answer"]):
                print("\n[Pipeline abstained -- insufficient evidence for this query.]")

            print("\n--- CITATIONS ---")
            _print_citations(result["answer"])

            print("\n--- EVIDENCE USED ---")
            _print_evidence(result["evidence"])

            print(f"\n--- LATENCY ---\n  retrieval + fusion + generation (combined, one call): {elapsed:.2f}s")
            print("\n" + "=" * 70 + "\n")
    finally:
        pipeline.close()


if __name__ == "__main__":
    main()
