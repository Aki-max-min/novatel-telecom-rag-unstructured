"""
Generation stage of the KG-hardening evaluation. Same protocol as eval/perf_report/run_generate.py (v3): resumable, append-only,
order arm -> run -> question, per-call timeout + bounded retries, failures recorded and skipped, heartbeat every 10 records.

    .venv_colpali/Scripts/python.exe eval/kg_hardening_eval/run_generate.py health            # Ollama reachable, model present, one call answered -> health.json
    .venv_colpali/Scripts/python.exe eval/kg_hardening_eval/run_generate.py smoke             # 3 questions x 4 arms (run 1) -> smoke_test.json (NOT raw_answers.jsonl)
                                                                                              # + no-LLM retrieval diff of the 3 C layers on all 42 questions
    .venv_colpali/Scripts/python.exe eval/kg_hardening_eval/run_generate.py generate --runs 3  # 4 arms x 42 questions x 3 runs -> raw_answers.jsonl

run_manifest.json is written ONCE by `generate`, before the first raw record exists, on a clean tree (git.dirty = false). A restart re-uses it and
refuses to continue if HEAD moved through anything outside this experiment's own files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness_kg as k  # noqa: E402

h = k.h
from integration.eval.run_manifest import build_manifest, git_info  # noqa: E402
from integration.qa.config import QAConfig  # noqa: E402
from integration.rag.rag_config import RagConfig  # noqa: E402

SMOKE_IDS = ["S01", "Q04", "MH02"]   # one db, one document (syn), one multi-hop; v3 recorded graph activity (chunks added) on Q04 and MH02
log = k.log


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---------------------------------------------------------------------------------------------------------------------------------
# Ollama health
# ---------------------------------------------------------------------------------------------------------------------------------
def _field(obj, name):
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def ollama_health(model: str = h.DEFAULT_MODEL) -> dict:
    """Server reachable, model present (digest recorded), one short generation answered, model loaded afterwards."""
    import ollama
    client = ollama.Client(timeout=120)
    out = {"model": model, "timestamp_utc": datetime.now(timezone.utc).isoformat()}
    listed = _field(client.list(), "models") or []
    found = next((m for m in listed if _field(m, "model") == model or _field(m, "name") == model), None)
    if found is None:
        out["error"] = f"model {model} is not in `ollama list`: {[_field(m, 'model') for m in listed]}"
        return out
    out["digest"] = _field(found, "digest")
    details = _field(found, "details")
    out["quantization"] = _field(details, "quantization_level") if details is not None else None
    t0 = time.perf_counter()
    r = client.chat(model=model, messages=[{"role": "system", "content": "Reply with one word."}, {"role": "user", "content": "OK?"}],
                    options={"temperature": 0.0, "seed": 42})
    out["probe_latency_s"] = round(time.perf_counter() - t0, 2)
    out["probe_reply"] = (_field(_field(r, "message"), "content") or "")[:40]
    running = _field(client.ps(), "models") or []
    out["loaded_after_probe"] = [_field(m, "model") or _field(m, "name") for m in running]
    out["ok"] = True
    return out


def health_stage() -> dict:
    out = ollama_health()
    k.RES.mkdir(parents=True, exist_ok=True)
    (k.RES / "health.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    if not out.get("ok"):
        raise SystemExit(f"Ollama health check failed: {out.get('error')}")
    log(f"health: model {out['model']} digest {out['digest'][:12]} probe {out['probe_latency_s']}s loaded={out['loaded_after_probe']}")
    return out


# ---------------------------------------------------------------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------------------------------------------------------------
def _git(*args) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=k.ROOT).stdout.strip()


def ensure_manifest(health: dict | None) -> dict:
    path = k.RES / "run_manifest.json"
    if path.exists():
        m = json.loads(path.read_text(encoding="utf-8"))
        head = git_info()["commit"]
        if m["git"]["commit"] != head:
            changed = _git("diff", "--name-only", m["git"]["commit"], head).split()
            foreign = [f for f in changed if not (f.startswith("eval/kg_hardening_eval/") or f.startswith("results/kg_hardening_eval/"))]
            if foreign:
                raise SystemExit(f"HEAD moved since the manifest was written ({m['git']['commit'][:8]} -> {head[:8]}) and files outside the "
                                 f"experiment changed: {foreign[:5]}; refusing to continue")
        return m
    g = git_info()
    if g["dirty"]:
        raise SystemExit("working tree is not clean: commit or remove changes first so the manifest records dirty=false")
    graph = k.ROOT / "knowledge_graph" / "output" / "graph.json"
    check_path = k.RES / "setup_logs" / "graph_rebuild_check.json"
    check = json.loads(check_path.read_text(encoding="utf-8")) if check_path.exists() else None
    index_dirs = [k.ROOT / "data" / "experiments" / "combined_retrieval" / "vectorstore"]
    extra = {
        "experiment": "KG hardening evaluation (Person B's hardened graph in Person A's pipeline): B2 / C_V0 / C_V1 / C_V1_links, 42 questions, 3 runs",
        "branch": g["branch"],
        "merged_commit_person_b": k.MERGED_COMMIT,
        "handoff_commit_person_b": k.HANDOFF_COMMIT,
        "extra_commits_note": "The 8 commits between the handoff commit (83a8aa7) and the merged tip (700a5dd) touch only Person B's hybrid/ link-decoupling "
                              "code (hybrid/fusion.py, pipeline.py, retrievers.py, two scripts, tests), knowledge_graph/tests/test_graph_expand.py and docs; "
                              "knowledge_graph/graph_augmented_retrieval.py, build_related_aliases.py and graph_builder.py are byte-identical between the two commits.",
        "v3_reference": {"commit": k.V3_COMMIT, "results": "results/perf_report/ (never modified by this evaluation)"},
        "interpreter": sys.executable,
        "arms": {a: k.arm_settings(a) for a in k.ARMS},
        "runs_per_arm": k.RUNS,
        "question_file": "eval/perf_report/questions.jsonl (unchanged, 42 questions; sha256 " + sha256_file(h.QUESTIONS)[:16] + ")",
        "retrieval_index_used": "data/experiments/combined_retrieval/vectorstore (SciFact chunks filtered at serving time in every arm)",
        "answer_cache": "none: every answer generated fresh (cached=false on every record)",
        "judge": "same local model as the generator, temperature 0, E14a prompts (integration/eval/base_vs_rag.py); every arm judged at the full level; "
                 "prompt cache seeded read-only from results/perf_report/judge_cache.jsonl, new verdicts appended to results/kg_hardening_eval/judge_cache.jsonl",
        "citation_check": "integration.qa.citations (NLI verifier) on every arm, flagging only",
        "decoding_note": h.SEED_NOTE,
        "context_budget": "5 database + 3 document blocks in every arm (RagConfig.b2(); never tuned)",
        "router": "unchanged: auto chain laya_finetuned -> embedding -> rule, router_conf_threshold 0.5 (data/eval/system_calibration.json); C arms only",
        "semantic_layer": {"seeds": "GRAPH_SEEDS (5)", "candidates": "GRAPH_CANDIDATES (20)", "max_chunks_per_doc": RagConfig().semantic_max_chunks_per_doc,
                           "gate": "hybrid/query_gate.graph_weight -> 0.5 / 0.15 / 0.0 (0.0 disables the graph for that question)",
                           "V1_options": k.V1_OPTIONS},
        "graph": {"path": "knowledge_graph/output/graph.json (rebuilt by python -m knowledge_graph.graph_builder after build_related_aliases)",
                  "sha256": sha256_file(graph) if graph.exists() else "missing",
                  "related_to": (check or {}).get("related_to_new"), "semantic_layer_reader": (check or {}).get("semantic_layer_reader_new"),
                  "graph_index": (check or {}).get("graph_index"),
                  "alias_files_sha256": {f: sha256_file(k.ROOT / "knowledge_graph" / f) for f in ("related_id_aliases.json", "related_id_alias_audit.csv")}},
        "parser": "structured/query_parser.py as merged from person-b/kg-hardening (includes Person B's parser fixes), blob "
                  + _git("hash-object", "structured/query_parser.py")[:10] + " (v3 ran blob 4ce2f6cc2e)",
        "ollama_model_digest": (health or {}).get("digest"),
        "ollama_quantization": (health or {}).get("quantization"),
        "power": "powercfg: sleep-after 0 (never) and hibernate-after 0 (never) on AC; machine on AC at start; lid-close action not readable without admin rights",
        "smoke_test": "results/kg_hardening_eval/smoke_test.json (3 questions x 4 arms, run 1; not part of raw_answers.jsonl)",
    }
    m = build_manifest(rag_config=RagConfig.b2(), qa_config=QAConfig(), index_dirs=index_dirs, extra=extra)
    k.RES.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(m, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    log(f"manifest written (git {m['git']['commit'][:8]}, dirty={m['git']['dirty']})")
    return m


# ---------------------------------------------------------------------------------------------------------------------------------
# smoke test
# ---------------------------------------------------------------------------------------------------------------------------------
def _sem(rec: dict) -> dict:
    return rec.get("semantic") or {}


def retrieval_diff(rig: k.Rig, qs: dict) -> dict:
    """No-LLM check on all 42 questions: the document search with each of the three C layers (same call Rig.generate makes, no routing),
    so that we know BEFORE the long run whether the V1 options and the link hop change anything at all."""
    rig.pipeline.unstructured.exclude_scifact = True
    per_q, summary = [], {"questions": 0, "gate_weight_positive": 0, "V1_docs_differ_from_V0": 0, "V1_added_differ_from_V0": 0,
                          "V1_links_docs_differ_from_V1": 0, "V1_links_added_differ_from_V1": 0,
                          "added_chunks_total": {a: 0 for a in k.C_ARMS}, "related_neighbours_added_total": 0}
    for qid, q in qs.items():
        row = {"id": qid, "category": q["category"]}
        for arm in k.C_ARMS:
            layer = rig.layers[arm]
            before = layer.stats["related_neighbours_added"]
            top10 = rig.pipeline.unstructured.search(q["query"], faiss_top_k=10, rerank_top_k=10, semantic=layer)
            docs = []
            for r in top10:
                d = (r.get("metadata") or {}).get("provenance", {}).get("document_id") or r["record_id"]
                if d not in docs:
                    docs.append(d)
            added = [r["record_id"] for r in top10 if (r.get("metadata") or {}).get("semantic_added")]
            first = next((r for r in top10 if (r.get("metadata") or {}).get("semantic")), None)
            info = ((first or {}).get("metadata", {}).get("semantic", {}) or {})
            row[arm] = {"doc_top10": docs, "added_chunks": added, "neighbour_docs": info.get("neighbour_docs") or [], "graph_weight": info.get("graph_weight"),
                        "concept": info.get("concept"), "related_neighbours_added": layer.stats["related_neighbours_added"] - before}
            summary["added_chunks_total"][arm] += len(added)
        summary["questions"] += 1
        gw = row["C_V0"]["graph_weight"] or 0.0
        summary["gate_weight_positive"] += gw > 0
        summary["V1_docs_differ_from_V0"] += row["C_V1"]["doc_top10"] != row["C_V0"]["doc_top10"]
        summary["V1_added_differ_from_V0"] += row["C_V1"]["added_chunks"] != row["C_V0"]["added_chunks"]
        summary["V1_links_docs_differ_from_V1"] += row["C_V1_links"]["doc_top10"] != row["C_V1"]["doc_top10"]
        summary["V1_links_added_differ_from_V1"] += row["C_V1_links"]["added_chunks"] != row["C_V1"]["added_chunks"]
        summary["related_neighbours_added_total"] += row["C_V1_links"]["related_neighbours_added"]
        per_q.append(row)
    return {"summary": summary, "per_question": per_q}


def smoke(rig: k.Rig) -> dict:
    qs = {q["id"]: q for q in h.load_questions()}
    rows = []
    for arm in k.ARMS:
        for qid in SMOKE_IDS:
            rec = rig.generate(arm, qs[qid], 1)
            s = _sem(rec)
            rows.append({"arm": arm, "id": qid, "category": rec["category"], "arm_label_in_record": rec["arm"], "arm_config": rec["arm_config"],
                         "route": (rec.get("route") or {}).get("final"), "graph_weight": s.get("graph_weight"), "concept": s.get("concept"),
                         "n_added_chunks": len(s.get("added_chunks") or []), "added_chunks": s.get("added_chunks") or [],
                         "neighbour_docs": s.get("neighbour_docs") or [], "related_neighbours_added": s.get("related_neighbours_added"),
                         "doc_top10": rec["doc_top10"], "prompt_docs": [b["doc_id"] for b in rec["prompt_blocks"] if b["source"] == "unstructured"],
                         "latency_s": rec["latency_s"], "prompt_tokens": rec["prompt_tokens"], "answer_head": rec["answer"][:160]})
            log(f"smoke {arm:10s} {qid:6s} route={rows[-1]['route']} gw={rows[-1]['graph_weight']} added={rows[-1]['n_added_chunks']} "
                f"links_added={rows[-1]['related_neighbours_added']} top3={rec['doc_top10'][:3]} {rec['latency_s']}s")
    label_ok = all(r["arm_label_in_record"] == r["arm"] and r["arm_config"]["layer"] == (None if r["arm"] == "B2" else r["arm"]) for r in rows)
    diff = retrieval_diff(rig, qs)
    sm = diff["summary"]
    v1_applied = sm["V1_added_differ_from_V0"] > 0 or sm["V1_docs_differ_from_V0"] > 0
    links_applied = sm["related_neighbours_added_total"] > 0
    verdict = {"arm_labels_match_configuration": label_ok, "V1_options_change_retrieval": v1_applied, "link_hop_adds_documents": links_applied,
               "proceed": label_ok and v1_applied}
    out = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "smoke_ids": SMOKE_IDS, "rows": rows, "retrieval_diff": diff, "verdict": verdict}
    (k.RES / "smoke_test.json").write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    log(f"smoke verdict: {verdict}; retrieval diff summary: {sm}")
    return out


# ---------------------------------------------------------------------------------------------------------------------------------
# generation
# ---------------------------------------------------------------------------------------------------------------------------------
def generate(rig: k.Rig, runs: int) -> None:
    questions = h.load_questions()
    done = {(r["arm"], r["id"], r["run"]) for r in h.read_jsonl(k.RAW)}
    plan = [(arm, q, run) for arm in k.ARMS for run in range(1, runs + 1) for q in questions]   # arm -> run -> question (as v3)
    todo = [p for p in plan if (p[0], p[1]["id"], p[2]) not in done]
    log(f"plan: {len(plan)} generations, {len(plan) - len(todo)} already done, {len(todo)} to run")
    started, last_completion, n_ok, n_fail = time.time(), None, 0, 0
    for i, (arm, q, run) in enumerate(todo, 1):
        try:
            rec = rig.generate(arm, q, run)
        except Exception as exc:  # noqa: BLE001  -- after the client's own timeout + retries: record the failure and carry on
            n_fail += 1
            h.append_jsonl(k.FAILURES, {"stage": "generate", "arm": arm, "id": q["id"], "run": run, "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                                        "timestamp_utc": datetime.now(timezone.utc).isoformat()})
            log(f"FAILED {arm} {q['id']} run{run}: {type(exc).__name__}: {str(exc)[:120]} (recorded in failures.jsonl; continuing)")
            continue
        now = time.time()
        rec["gap_since_previous_s"] = None if last_completion is None else round(now - last_completion, 1)
        rec["suspect_gap"] = bool(last_completion is not None and now - last_completion > h.SUSPECT_GAP_S)
        last_completion = now
        rec["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
        h.append_jsonl(k.RAW, rec)
        n_ok += 1
        if i % 10 == 0 or i == len(todo):
            elapsed = now - started
            eta = elapsed / i * (len(todo) - i)
            log(f"HEARTBEAT [{i}/{len(todo)}] ok={n_ok} failed={n_fail} last={arm} {q['id']} run{run} {rec['latency_s']}s ETA {eta / 60:.0f} min")
    log(f"generation loop done: ok={n_ok} failed={n_fail}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["health", "smoke", "generate"])
    ap.add_argument("--runs", type=int, default=k.RUNS)
    args = ap.parse_args()
    health = health_stage()
    if args.stage == "health":
        return
    if args.stage == "generate":
        ensure_manifest(health)
    t0 = time.time()
    rig = k.Rig()
    log("models loaded; warming up")
    rig.warm_up()
    if args.stage == "smoke":
        smoke(rig)
    else:
        generate(rig, args.runs)
    log(f"{args.stage} finished in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
