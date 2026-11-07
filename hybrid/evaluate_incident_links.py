"""
Mechanism check for resolved RELATED_TO links (KG hardening Part 3): five differently-worded incident questions,
one per INC/RCA pair. Reports whether BOTH documents of the pair are in the final top 5 with links ON vs OFF.

MECHANISM ONLY: only five such pairs exist, so this is not evidence of generalisation.
Run in the rag-api environment:  python hybrid/evaluate_incident_links.py
"""

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.chdir(REPO_ROOT)

from pipeline import run_hybrid_retrieval  # noqa: E402
from retrievers import build_candidates, load_context  # noqa: E402

CHECK = Path(__file__).resolve().parent / "benchmark" / "incident_link_check.json"


def final_docs(question, use_links):
    ctx = load_context()
    vector, graph, _ = build_candidates(question, ctx["retriever"], ctx["graph_index"], ctx["corpus"],
                                        ctx["person_a"], use_related_links=use_links)
    out = run_hybrid_retrieval(question, vector, graph, top_k=5)  # explicit candidate lists: graph participates
    return [c["metadata"]["document_id"] for c in out], [c["metadata"]["document_id"] for c in vector[:5]]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    items = json.loads(CHECK.read_text(encoding="utf-8"))["questions"]
    on_both = off_both = 0
    print("===== INCIDENT LINK MECHANISM CHECK (mechanism-only; 5 pairs) =====")
    for item in items:
        pair = set(item["pair"])
        off, vec = final_docs(item["question"], False)
        on, _ = final_docs(item["question"], True)
        off_hits, on_hits = pair & set(off), pair & set(on)
        off_both += len(off_hits) == 2
        on_both += len(on_hits) == 2
        print(f"{item['question_id']}: pair in vector top5: {len(pair & set(vec))}/2 | links OFF final top5: "
              f"{len(off_hits)}/2 | links ON final top5: {len(on_hits)}/2")
        print(f"     OFF {off}\n     ON  {on}")
    print(f"both documents of the pair in the final top 5: links OFF {off_both}/5, links ON {on_both}/5")


if __name__ == "__main__":
    main()
