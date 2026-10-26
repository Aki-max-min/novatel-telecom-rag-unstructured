"""
Interactive CLI for integration.rag.pipeline. Loads both retrievers and the
Ollama model ONCE, then loops: read a query from stdin, call the existing
RagPipeline.run_query() unchanged, print the answer/citations/evidence/
latency. Type 'exit' or 'quit' to stop.

Does not modify pipeline.py, fuse.py, generate.py, or any retriever --
this file only calls RagPipeline as-is.
"""

import re
import time

from integration.rag.pipeline import RagPipeline

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


def main() -> None:
    print("Loading retrievers and local LLM (this happens once)...")
    pipeline = RagPipeline()
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
