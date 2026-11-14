"""
Leakage / near-duplicate check between evaluation sets and the data used to build or tune the router.

Pairs checked (held-out set  vs  data it must not resemble):
    router_test   vs router_train, router_val
    router_val    vs router_train
    abstention_*  vs router_train, router_val, router_test (+ each other)
    demo questions vs router_train, router_val   (if demo/demo_questions.json exists)

Three similarity signals per held-out query against its nearest neighbour in the reference data:
    exact       identical after lowercasing / stripping punctuation
    jaccard     word-set Jaccard  >= JACCARD_FLAG
    cosine      MiniLM sentence-embedding cosine >= COSINE_FLAG
Customer-id and number tokens are masked before comparison: two templated questions that differ only by a
customer id ARE near-duplicates for routing purposes, and the check must say so.

Output: data/eval/router_leakage_report.json  (+ a printed summary). Flagged test items are listed by id so
evaluate_router.py can report accuracy with and without them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVAL = ROOT / "data" / "eval"
JACCARD_FLAG = 0.80
COSINE_FLAG = 0.92
EMB_MODEL = "all-MiniLM-L6-v2"


def norm(text: str) -> str:
    t = re.sub(r"\d+", "#", text.lower())
    t = re.sub(r"[^a-z# ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def demo_rows() -> list[dict]:
    p = ROOT / "demo" / "demo_questions.json"
    if not p.exists():
        return []
    return [{"id": f"DEMO_{i + 1:02d}", "query": q["question"]} for i, q in enumerate(json.loads(p.read_text(encoding="utf-8"))["questions"])]


def compare(held: list[dict], ref: list[dict], encoder) -> list[dict]:
    if not held or not ref:
        return []
    h_n, r_n = [norm(r["query"]) for r in held], [norm(r["query"]) for r in ref]
    h_vec = encoder.encode([r["query"] for r in held], normalize_embeddings=True, convert_to_numpy=True)
    r_vec = encoder.encode([r["query"] for r in ref], normalize_embeddings=True, convert_to_numpy=True)
    sims = h_vec @ r_vec.T
    flagged = []
    for i, row in enumerate(held):
        j = int(sims[i].argmax())
        cos = float(sims[i, j])
        a, b = set(h_n[i].split()), set(r_n[j].split())
        jac = len(a & b) / max(1, len(a | b))
        exact = any(h_n[i] == rn for rn in r_n)
        reasons = []
        if exact:
            reasons.append("exact(normalised)")
        if jac >= JACCARD_FLAG:
            reasons.append(f"jaccard={jac:.2f}")
        if cos >= COSINE_FLAG:
            reasons.append(f"cosine={cos:.2f}")
        if reasons:
            flagged.append({"id": row.get("id"), "query": row["query"], "nearest": ref[j]["query"],
                            "nearest_id": ref[j].get("id"), "reasons": reasons,
                            "nearest_is_synthetic": ref[j].get("synthetic")})
    return flagged


def main() -> None:
    from sentence_transformers import SentenceTransformer
    encoder = SentenceTransformer(EMB_MODEL, local_files_only=True)

    tr, va, te = (read(EVAL / f"router_{s}.jsonl") for s in ("train", "val", "test"))
    abs_val, abs_test = read(EVAL / "abstention_val.jsonl"), read(EVAL / "abstention_test.jsonl")
    demo = demo_rows()

    pairs = {
        "router_test_vs_train+val": (te, tr + va),
        "router_val_vs_train": (va, tr),
        "abstention_val_vs_router_all": (abs_val, tr + va + te),
        "abstention_test_vs_router_all": (abs_test, tr + va + te),
        "abstention_test_vs_abstention_val": (abs_test, abs_val),
        "demo_vs_router_train+val": (demo, tr + va),
        "demo_vs_router_test": (demo, te),
    }
    report = {"thresholds": {"jaccard": JACCARD_FLAG, "cosine": COSINE_FLAG, "embedding_model": EMB_MODEL,
                             "masking": "digits replaced by '#'"}, "pairs": {}}
    for name, (held, ref) in pairs.items():
        flagged = compare(held, ref, encoder)
        report["pairs"][name] = {"held_out_n": len(held), "reference_n": len(ref), "flagged_n": len(flagged),
                                 "flagged": flagged}
        print(f"{name:42s} held-out={len(held):3d} reference={len(ref):4d} flagged={len(flagged)}")

    test_flag_ids = sorted(f["id"] for f in report["pairs"]["router_test_vs_train+val"]["flagged"])
    report["router_test_flagged_ids"] = test_flag_ids
    (EVAL / "router_leakage_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("wrote data/eval/router_leakage_report.json")


if __name__ == "__main__":
    main()
