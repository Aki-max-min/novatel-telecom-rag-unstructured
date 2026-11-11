"""
Part 5a: abstention composition for the router arms (read-only analysis of raw records).

    .venv_colpali/Scripts/python.exe eval/final_ablation/fa_open_items.py

For every arm with a router (C_V0 / C_V1 / C_V1_links from results/kg_hardening_eval/, and R from results/final_ablation/ when it exists) lists
every record with abstained=True (the harness flag: route out_of_scope -> the fixed abstention message; or an empty prompt context) and says
which layer abstained:
  router         route final == out_of_scope (the router's own decision; the harness answers with QAConfig.abstention_message)
  retrieval      the route was followed but the searched source(s) returned nothing, so the prompt was empty (no retrieval-confidence gate
                 exists in this harness: this is "nothing retrieved", keyed by the structured status)
  generator      answer text carries an E14a abstention marker although evidence was in the prompt (NOT counted in the harness's abstained
                 flag; listed separately as "generator abstention-like answers")
and whether abstaining was correct: the only should-abstain question in the 42 is S15 (gibberish query; v3 STATUS.md). Everything else is
answerable, so an abstention there is unnecessary.

Writes results/final_ablation/abstention_composition.md (+ .json).
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness_fa as fa  # noqa: E402

h = fa.h
from integration.eval.base_vs_rag import ABSTENTION_MARKERS  # noqa: E402

SHOULD_ABSTAIN = {"S15"}


def layer_of(rec: dict) -> tuple[str, str]:
    route = (rec.get("route") or {}).get("final")
    if route == "out_of_scope":
        return "router", "route out_of_scope -> fixed abstention message"
    st = rec.get("structured_status") or {}
    if not rec["context_text"].strip():
        parts = []
        if route in ("structured", "hybrid"):
            parts.append(f"structured: executed={st.get('executed')} route={st.get('route')} table={st.get('table')} rows={len(rec.get('structured_ids') or [])}"
                         + (f" note={str(st.get('note'))[:80]}" if st.get("note") else "") + (f" reason={st.get('reason')}" if st.get("reason") else ""))
        if route in ("unstructured", "hybrid"):
            parts.append(f"documents: top10={len(rec.get('doc_top10') or [])}")
        return "retrieval", "empty prompt; " + "; ".join(parts)
    return "generator", "evidence in prompt, abstention-like answer"


def main() -> None:
    qs = {q["id"]: q for q in h.load_questions()}
    raw, scored = fa.load_reused(check_counts=False)
    if fa.RAW.exists():
        for r in h.read_jsonl(fa.RAW):
            raw[(r["arm"], r["id"], r["run"])] = r
        for s in h.read_jsonl(fa.SCORED) if fa.SCORED.exists() else []:
            scored[(s["arm"], s["id"], s["run"])] = s
    arms = [a for a in ("R", "C_V0", "C_V1", "C_V1_links") if any(k[0] == a for k in raw)]
    out = {"should_abstain_questions": sorted(SHOULD_ABSTAIN), "arms": {}}
    for arm in arms:
        rows, gen_rows = [], []
        for key in sorted((k for k in raw if k[0] == arm), key=lambda k: (k[2], list(qs).index(k[1]))):
            r = raw[key]
            route = (r.get("route") or {}).get("final")
            conf = (r.get("route") or {}).get("confidence")
            corr = (scored.get(key) or {}).get("correctness")
            if r.get("abstained"):
                layer, why = layer_of(r)
                rows.append({"id": key[1], "run": key[2], "category": r["category"], "route": route, "router_confidence": conf, "layer": layer, "why": why,
                             "correct_to_abstain": key[1] in SHOULD_ABSTAIN, "scored_correctness": corr, "answer": r["answer"][:100]})
            elif any(m in r["answer"].lower() for m in ABSTENTION_MARKERS):
                gen_rows.append({"id": key[1], "run": key[2], "category": r["category"], "route": route, "scored_correctness": corr,
                                 "prompt_docs": [b["doc_id"] for b in r["prompt_blocks"] if b["source"] == "unstructured"][:4],
                                 "n_sql_blocks": sum(1 for b in r["prompt_blocks"] if b["source"] == "structured"), "answer": r["answer"][:140]})
        out["arms"][arm] = {"n_abstained": len(rows), "by_layer": dict(Counter(x["layer"] for x in rows)), "correct": sum(x["correct_to_abstain"] for x in rows),
                            "unnecessary": sum(not x["correct_to_abstain"] for x in rows), "questions": sorted({x["id"] for x in rows}, key=list(qs).index),
                            "rows": rows, "generator_abstention_like_not_flagged": gen_rows}
    (fa.RES / "abstention_composition.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    md = ["# Abstention composition (router arms)", "",
          "`abstained` is the harness flag: the router said out_of_scope (fixed message) or the prompt context was empty. The only should-abstain question "
          "among the 42 is S15 (gibberish). 'generator' rows are answers that carry an E14a abstention marker although evidence was in the prompt; they are "
          "not counted in the flag and are listed separately. Scoring note (v3 STATUS.md): the router's abstention message is not in E14a's marker list, so S15 scores 0 "
          "even when abstaining was right.", ""]
    for arm, a in out["arms"].items():
        md += [f"## {arm}: {a['n_abstained']} abstained records ({a['by_layer']}); correct {a['correct']}, unnecessary {a['unnecessary']}; questions {a['questions']}", "",
               "| id | run | cat | route | router conf. | layer | correct? | scored | why |", "|---|---|---|---|---|---|---|---|---|"]
        for x in a["rows"]:
            md.append(f"| {x['id']} | {x['run']} | {x['category']} | {x['route']} | {x['router_confidence']} | {x['layer']} | {'yes' if x['correct_to_abstain'] else 'no (answerable)'} | {x['scored_correctness']} | {x['why']} |")
        md += ["", f"Generator abstention-like answers not flagged ({len(a['generator_abstention_like_not_flagged'])}):", "",
               "| id | run | cat | route | scored | prompt docs | SQL blocks | answer |", "|---|---|---|---|---|---|---|---|"]
        for x in a["generator_abstention_like_not_flagged"]:
            md.append(f"| {x['id']} | {x['run']} | {x['category']} | {x['route']} | {x['scored_correctness']} | {x['prompt_docs']} | {x['n_sql_blocks']} | {x['answer']!r} |")
        md.append("")
    (fa.RES / "abstention_composition.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md[:60]))
    print("written: abstention_composition.md / .json")


if __name__ == "__main__":
    main()
