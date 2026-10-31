"""
Generation stage of the final measurement. Resumable: every (arm, question, run) is appended to results/perf_report/raw_answers.jsonl the
moment it completes, and finished records are skipped on restart (nothing is ever overwritten).

    python eval/perf_report/run_generate.py preflight          # determinism check on 10 questions (arm B2, twice) -> determinism_check.json
    python eval/perf_report/run_generate.py generate --runs 1  # all arms x all 42 questions (+ the SciFact-off reproduction on the core 22)

The run manifest (results/perf_report/run_manifest.json) is written ONCE, before the first output file exists, so it records a clean tree
(git.dirty = false). A restart re-uses it and refuses to continue if HEAD moved.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness as h  # noqa: E402

from integration.eval.run_manifest import build_manifest, git_info  # noqa: E402
from integration.qa.config import QAConfig  # noqa: E402
from integration.rag.rag_config import RagConfig  # noqa: E402

LOG = h.RES / "run_log.txt"
PREFLIGHT_IDS = ["S01", "S03", "S15", "Q01", "Q04", "RW_001", "RW_004", "MH01", "MH_RB_B01", "MH12"]


def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} {msg}"
    print(line, flush=True)
    h.RES.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def ensure_manifest() -> dict:
    path = h.RES / "run_manifest.json"
    if path.exists():
        m = json.loads(path.read_text(encoding="utf-8"))
        head = git_info()["commit"]
        if m["git"]["commit"] != head:
            raise SystemExit(f"HEAD moved since the manifest was written ({m['git']['commit'][:8]} -> {head[:8]}); refusing to continue")
        return m
    g = git_info()
    if g["dirty"]:
        raise SystemExit("working tree is not clean: commit or remove changes first so the manifest records dirty=false")
    index_dirs = [h.ROOT / "data" / "experiments" / "combined_retrieval" / "vectorstore",
                  h.ROOT / "data" / "experiments" / "combined_retrieval_clean" / "vectorstore"]
    m = build_manifest(rag_config=RagConfig.b2(), qa_config=QAConfig(), index_dirs=index_dirs, extra={
        "experiment": "final performance measurement",
        "arms": {a: h.arm_settings(a) for a in h.ARMS + [h.REPRO_ARM]},
        "retrieval_index_used": "data/experiments/combined_retrieval/vectorstore (E14 pipeline index; SciFact chunks filtered at serving time in every arm except B_scifact_off)",
        "answer_cache": "none: this harness generates every answer fresh (cached=false on every record)",
        "parser": "structured/query_parser.py as on this branch (original substring parser; parser-wordboundary NOT merged), "
                  f"blob {__import__('subprocess').run(['git','hash-object','structured/query_parser.py'], capture_output=True, text=True, cwd=h.ROOT).stdout.strip()[:10]}",
        "decoding_note": h.SEED_NOTE, "judge": "same local model as the generator, temperature 0, E14a prompts (integration/eval/base_vs_rag.py)",
        "context_budget": {"B": "shared 6 blocks", "B2_and_others": "5 database + 3 document blocks (from the E14a failure analysis on the same 22 questions; never tuned)"},
        "router_thresholds": "router_conf_threshold 0.5 from data/eval/system_calibration.json (validation-calibrated)"})
    h.RES.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(m, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    log(f"manifest written (git {m['git']['commit'][:8]}, dirty={m['git']['dirty']})")
    return m


def preflight(rig: h.Rig) -> dict:
    qs = {q["id"]: q for q in h.load_questions()}
    picked = [qs[i] for i in PREFLIGHT_IDS if i in qs]
    rows = []
    for q in picked:
        a = rig.generate("B2", q, 1)
        b = rig.generate("B2", q, 2)
        rows.append({"id": q["id"], "identical_answer": a["answer"] == b["answer"],
                     "identical_prompt_context": a["context_text"] == b["context_text"],
                     "prompt_tokens": [a["prompt_tokens"], b["prompt_tokens"]]})
        log(f"preflight {q['id']}: identical={rows[-1]['identical_answer']}")
    out = {"arm": "B2", "n_questions": len(rows), "n_identical_answers": sum(r["identical_answer"] for r in rows),
           "all_deterministic": all(r["identical_answer"] for r in rows), "rows": rows,
           "decision": None}
    out["decision"] = "one run per arm is enough (all answers identical across two generations)" if out["all_deterministic"] \
        else "answers differ between identical runs: 3 runs per arm required"
    (h.RES / "determinism_check.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    log(f"preflight: {out['n_identical_answers']}/{out['n_questions']} identical -> {out['decision']}")
    return out


def generate(rig: h.Rig, runs: int) -> None:
    questions = h.load_questions()
    done = {(r["arm"], r["id"], r["run"]) for r in h.read_jsonl(h.RAW)}
    plan = [(arm, q, run) for arm in h.ARMS for q in questions for run in range(1, runs + 1)]
    plan += [(h.REPRO_ARM, q, run) for q in questions if q["is_core"] for run in range(1, runs + 1)]
    todo = [p for p in plan if (p[0], p[1]["id"], p[2]) not in done]
    log(f"plan: {len(plan)} generations, {len(plan) - len(todo)} already done, {len(todo)} to run")
    for i, (arm, q, run) in enumerate(todo, 1):
        rec = rig.generate(arm, q, run)
        rec["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
        h.append_jsonl(h.RAW, rec)
        if i % 10 == 0 or i == len(todo):
            log(f"[{i}/{len(todo)}] {arm} {q['id']} run{run} {rec['latency_s']}s prompt_tokens={rec['prompt_tokens']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["preflight", "generate"])
    ap.add_argument("--runs", type=int, default=1)
    args = ap.parse_args()
    ensure_manifest()
    t0 = time.time()
    rig = h.Rig()
    log("models loaded; warming up")
    rig.warm_up()
    if args.stage == "preflight":
        preflight(rig)
    else:
        generate(rig, args.runs)
    log(f"{args.stage} finished in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
