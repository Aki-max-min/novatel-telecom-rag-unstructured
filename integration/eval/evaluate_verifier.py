"""
Mutation test for the citation verifier (integration/qa/citations.verify_sentence).

A verifier that never flags anything looks perfect on faithful text, so it is measured on text that is KNOWN to be
unsupported. Method (no LLM involved, so the labels are certain):

  faithful   an actual sentence copied from a chunk, cited against that same chunk -> should NOT be UNSUPPORTED
             (extractive sentences are the easy case; paraphrase robustness is NOT measured here and is a limit)
  mutations  applied to the faithful sentences:
    number_change    one number replaced by a different number           -> must be flagged (UNSUPPORTED)
    negation         a negation inserted after an auxiliary verb          -> should be flagged (not SUPPORTED)
    wrong_source     the sentence cited against a chunk of a DIFFERENT
                     document                                             -> should be flagged (not SUPPORTED)
    fabricated_tail  a plausible but invented clause appended             -> should be flagged (not SUPPORTED)

Reports, per mutation: detection rate under two definitions
    strict  = status == UNSUPPORTED
    lenient = status != SUPPORTED   (UNSUPPORTED or WEAK; what the UI shows in non-green)
and, for faithful sentences, the false-flag rates under the same two definitions. Both verifiers (lexical, nli).

    python -m integration.eval.evaluate_verifier --n 40
"""

from __future__ import annotations

import argparse
import json
import random
import re
from datetime import datetime, timezone
from pathlib import Path

from integration.qa import citations as cit
from integration.qa.config import QAConfig
from integration.qa.evidence import assign_evidence_ids, unstructured_evidence

ROOT = Path(__file__).resolve().parents[2]
META = ROOT / "data" / "experiments" / "combined_retrieval" / "vectorstore" / "chunk_metadata.json"
SYNTH = ROOT / "data" / "processed" / "chunks"
AUX = re.compile(r"\b(is|are|was|were|can|must|will|may|should|does|do|has|have)\b", re.I)
FABRICATIONS = [" Customers also receive a complimentary 5G upgrade for life.",
                " This is handled exclusively by the Mumbai regional office.",
                " The same rule applies to all prepaid and postpaid plans without exception."]


def chunk_text(rec: dict) -> str:
    if rec.get("text"):
        return rec["text"]
    p = SYNTH / f"{rec['chunk_id']}.json"
    return json.loads(p.read_text(encoding="utf-8")).get("text", "") if p.exists() else ""


def sentences_of(text: str) -> list[str]:
    out = []
    for s in re.split(r"(?<=[.!?])\s+|\n+", text):
        s = s.strip(" -*#>\t")
        if 8 <= len(s.split()) <= 35 and re.search(r"[a-z]{4}", s):
            out.append(s)
    return out


def ev(rec: dict, text: str, n: int) -> dict:
    item = unstructured_evidence(
        document_id=rec["document_id"], chunk_id=rec["chunk_id"], dataset="novatel_synthetic", category=rec.get("category", ""),
        content=text, title=rec.get("title", ""), retrieval_method="test", raw_scores={}, score=0.0, sub_query="", origin="test")
    item["metadata"]["evidence_id"] = f"E{n}"
    return item


def mutate_number(sentence: str, rng: random.Random):
    nums = list(re.finditer(r"\d[\d,]*(?:\.\d+)?", sentence))
    if not nums:
        return None
    m = rng.choice(nums)
    val = float(m.group().replace(",", ""))
    new = str(int(val) + rng.choice([3, 7, 11])) if val == int(val) else f"{val + 3.5:.1f}"
    return sentence[:m.start()] + new + sentence[m.end():]


def mutate_negate(sentence: str):
    m = AUX.search(sentence)
    return None if not m else sentence[:m.end()] + " not" + sentence[m.end():]


def rates(statuses: list[str]) -> dict:
    n = len(statuses)
    return {"n": n,
            "strict_flag_rate": round(sum(s == cit.UNSUPPORTED for s in statuses) / n, 3) if n else None,
            "lenient_flag_rate": round(sum(s != cit.SUPPORTED for s in statuses) / n, 3) if n else None}


def run(verifier: str, cases: dict, base_cfg: dict) -> dict:
    cfg = QAConfig(verifier=verifier, **base_cfg)
    out = {}
    for name, items in cases.items():
        statuses = [cit.verify_sentence(sent, [e], cfg).status for sent, e in items]
        out[name] = rates(statuses)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    meta = json.loads(META.read_text(encoding="utf-8"))
    pool = []
    for rec in rng.sample(meta, len(meta)):
        text = chunk_text(rec)
        sents = sentences_of(text)
        if sents:
            pool.append((rec, text, rng.choice(sents)))
        if len(pool) >= args.n * 2:
            break
    rng.shuffle(pool)
    pool = pool[:args.n]

    cases = {"faithful": [], "number_change": [], "negation": [], "wrong_source": [], "fabricated_tail": []}
    for i, (rec, text, sent) in enumerate(pool):
        own = ev(rec, text, 1)
        cases["faithful"].append((sent, own))
        m = mutate_number(sent, rng)
        if m:
            cases["number_change"].append((m, own))
        g = mutate_negate(sent)
        if g:
            cases["negation"].append((g, own))
        other_rec, other_text, _ = next(p for p in pool[i + 1:] + pool[:i] if p[0]["document_id"] != rec["document_id"])
        cases["wrong_source"].append((sent, ev(other_rec, other_text, 1)))
        cases["fabricated_tail"].append((sent + rng.choice(FABRICATIONS), own))

    base_cfg = {}
    result = {"experiment": "verifier-mutation-test", "timestamp_utc": datetime.now(timezone.utc).isoformat(), "seed": args.seed,
              "n_sentences": len(pool), "thresholds": {k: getattr(QAConfig(), k) for k in
                                                       ("nli_supported_threshold", "nli_weak_threshold",
                                                        "lexical_supported_threshold", "lexical_weak_threshold")},
              "limits": ["faithful sentences are extractive copies (easy case)", "mutations are synthetic, not model errors",
                         "negation detection relies on NLI contradiction; the lexical verifier cannot see it"],
              "results": {v: run(v, cases, base_cfg) for v in ("lexical", "nli")}}
    out = ROOT / "data" / "experiments" / "system_eval" / "verifier_mutation_test.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    for v, res in result["results"].items():
        print(f"\n[{v}]")
        for k, r in res.items():
            print(f"  {k:16s} n={r['n']:3d} strict={r['strict_flag_rate']} lenient={r['lenient_flag_rate']}")
    print(f"saved: {out}")


if __name__ == "__main__":
    main()
