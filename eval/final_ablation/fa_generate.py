"""
Generation stage of the final ablation. Same protocol as the v3 and KG-hardening runs: resumable, append-only, order arm -> run -> question,
per-call timeout + bounded retries (TimeoutClient), failures recorded and skipped, heartbeat every 10 records.

    .venv_colpali/Scripts/python.exe eval/final_ablation/fa_generate.py health            # Ollama reachable, model present + loaded after a probe -> health.json
    .venv_colpali/Scripts/python.exe eval/final_ablation/fa_generate.py smoke             # 3 questions x 7 generated arms (run 1) -> smoke_test.json (NOT raw_answers.jsonl)
                                                                                          # + no-LLM retrieval diff of O / G0 / G1 / G1L vs plain B2 search on all 42 questions
    .venv_colpali/Scripts/python.exe eval/final_ablation/fa_generate.py estimate          # runtime estimate from measured v3 / KG-hardening timings -> time_estimate.json
    .venv_colpali/Scripts/python.exe eval/final_ablation/fa_generate.py generate --runs 3  # 7 arms x 42 questions x 3 runs -> raw_answers.jsonl

run_manifest.json is written ONCE by `generate`, before the first raw record exists, on a clean tree (git.dirty = false), after verifying that the
reused arms (results/kg_hardening_eval/) were produced on code identical to HEAD for every retrieval/generation module. A restart re-uses it and
refuses to continue if HEAD moved through anything outside this experiment's own files. `generate` refuses to start on battery power unless
--allow-battery is given (previous runs were hit by laptop sleep).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness_fa as fa  # noqa: E402

h = fa.h
from integration.eval.run_manifest import build_manifest, git_info  # noqa: E402
from integration.qa.config import QAConfig  # noqa: E402
from integration.rag.rag_config import RagConfig  # noqa: E402

SMOKE_IDS = ["S01", "Q04", "MH02"]   # one db, one document (syn), one multi-hop; the graph fires on Q04 (gate 0.5) and MH02 (gate 0.15)
log = fa.log


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _git(*args) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=fa.ROOT).stdout.strip()


# ---------------------------------------------------------------------------------------------------------------------------------
# Ollama health, power
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
    out["ok"] = model in out["loaded_after_probe"] or bool(out["loaded_after_probe"])
    if not out["ok"]:
        out["error"] = "model not reported as loaded by `ollama ps` after the probe"
    return out


def power_status() -> dict:
    """powercfg sleep / hibernate idle timeouts and the battery state (read-only; PowerShell + powercfg)."""
    out = {"timestamp_utc": datetime.now(timezone.utc).isoformat()}
    try:
        ps = subprocess.run(["powershell", "-NoProfile", "-Command",
                             "$b = Get-CimInstance Win32_Battery | Select-Object -First 1; "
                             "Write-Output ('{0}|{1}|{2}' -f $b.BatteryStatus, $b.EstimatedChargeRemaining, $b.EstimatedRunTime)"],
                            capture_output=True, text=True, timeout=60).stdout.strip()
        status, charge, runtime = (ps.split("|") + ["", "", ""])[:3]
        out["battery_status_code"] = int(status) if status.isdigit() else status
        out["battery_status"] = {1: "discharging (on battery)", 2: "on AC power", 3: "fully charged", 4: "low", 5: "critical", 6: "charging",
                                 7: "charging and high", 8: "charging and low", 9: "charging and critical"}.get(out["battery_status_code"], "unknown")
        out["battery_charge_pct"] = int(charge) if charge.isdigit() else None
        out["battery_estimated_runtime_min"] = int(runtime) if runtime.isdigit() else None
    except Exception as exc:  # noqa: BLE001
        out["battery_error"] = f"{type(exc).__name__}: {exc}"
    for name, guid in (("sleep_after", "29f6c1db-86da-48c5-9fdb-f2b67b1f44da"), ("hibernate_after", "9d7815a6-7ee4-497e-8888-515a05f02364")):
        try:
            txt = subprocess.run(["powercfg", "/query", "SCHEME_CURRENT", "238c9fa8-0aad-41ed-83f4-97be242c8f20", guid], capture_output=True, text=True, timeout=60).stdout
            ac = next((l.split(":")[-1].strip() for l in txt.splitlines() if "AC Power Setting Index" in l), None)
            dc = next((l.split(":")[-1].strip() for l in txt.splitlines() if "DC Power Setting Index" in l), None)
            out[name + "_s"] = {"AC": int(ac, 16) if ac else None, "DC": int(dc, 16) if dc else None}
        except Exception as exc:  # noqa: BLE001
            out[name + "_s"] = f"unreadable: {type(exc).__name__}"
    out["on_battery"] = out.get("battery_status_code") == 1
    out["sleep_disabled"] = isinstance(out.get("sleep_after_s"), dict) and out["sleep_after_s"].get("AC") == 0 and out["sleep_after_s"].get("DC") == 0
    return out


def health_stage(write: bool = True, out: dict | None = None) -> dict:
    out = out or ollama_health()
    if not out.get("ok"):
        raise SystemExit(f"Ollama health check failed: {out.get('error')}")
    out.setdefault("power", power_status())
    if write:
        fa.RES.mkdir(parents=True, exist_ok=True)
        (fa.RES / "health.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
        log(f"health: model {out['model']} digest {out['digest'][:12]} probe {out['probe_latency_s']}s loaded={out['loaded_after_probe']}; "
            f"power: {out['power'].get('battery_status')} charge={out['power'].get('battery_charge_pct')}% sleep_after={out['power'].get('sleep_after_s')}")
    return out


# ---------------------------------------------------------------------------------------------------------------------------------
# reused arms: code identity
# ---------------------------------------------------------------------------------------------------------------------------------
def verify_reused_arms() -> dict:
    """The reused arms (results/kg_hardening_eval/) must come from code identical to HEAD for every retrieval/generation module, the same
    graph.json and the same index; counts and arm labels are checked by harness_fa.load_reused."""
    km = json.loads(fa.KG_MANIFEST.read_text(encoding="utf-8"))
    kg_commit = km["git"]["commit"]
    head = git_info()["commit"]
    changed = _git("diff", "--name-only", kg_commit, head, "--", *fa.KG_CODE_DIRS).split()
    not_allowed = [f for f in changed if f not in fa.ALLOWED_CODE_CHANGES]
    graph = fa.ROOT / "knowledge_graph" / "output" / "graph.json"
    graph_sha = sha256_file(graph) if graph.exists() else "missing"
    kg_graph_sha = km.get("extra", {}).get("graph", {}).get("sha256")
    kg_index = {i["path"]: i for i in km.get("indexes", [])}
    fa.load_reused(check_counts=True)
    out = {"source": str(fa.KG_RES.relative_to(fa.ROOT)).replace("\\", "/"), "arms": fa.ARMS_REUSED, "records_per_arm": 126,
           "kg_manifest_commit": kg_commit, "head_commit": head, "code_dirs_compared": fa.KG_CODE_DIRS, "files_changed_in_code_dirs": changed,
           "allowed_code_changes": sorted(fa.ALLOWED_CODE_CHANGES), "files_changed_not_allowed": not_allowed,
           "graph_sha256_now": graph_sha, "graph_sha256_kg_run": kg_graph_sha, "graph_identical": graph_sha == kg_graph_sha,
           "kg_index_sha256": kg_index, "kg_parser_note": km.get("extra", {}).get("parser"), "kg_ollama_digest": km.get("extra", {}).get("ollama_model_digest")}
    if not_allowed:
        raise SystemExit(f"reused arms were generated at {kg_commit[:8]} but HEAD {head[:8]} differs in retrieval/generation code: {not_allowed[:8]}; refusing")
    if not out["graph_identical"]:
        raise SystemExit(f"graph.json differs from the one the reused arms used ({graph_sha[:12]} vs {kg_graph_sha}); refusing")
    return out


# ---------------------------------------------------------------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------------------------------------------------------------
def ensure_manifest(health: dict | None) -> dict:
    path = fa.RES / "run_manifest.json"
    if path.exists():
        m = json.loads(path.read_text(encoding="utf-8"))
        head = git_info()["commit"]
        if m["git"]["commit"] != head:
            changed = _git("diff", "--name-only", m["git"]["commit"], head).split()
            foreign = [f for f in changed if not (f.startswith("eval/final_ablation/") or f.startswith("results/final_ablation/") or f.startswith("docs/"))]
            if foreign:
                raise SystemExit(f"HEAD moved since the manifest was written ({m['git']['commit'][:8]} -> {head[:8]}) and files outside the "
                                 f"experiment changed: {foreign[:5]}; refusing to continue")
        return m
    g = git_info()
    if g["dirty"]:
        raise SystemExit("working tree is not clean: commit or remove changes first so the manifest records dirty=false")
    reused = verify_reused_arms()
    graph = fa.ROOT / "knowledge_graph" / "output" / "graph.json"
    index_dirs = [fa.ROOT / "data" / "experiments" / "combined_retrieval" / "vectorstore"]
    km = json.loads(fa.KG_MANIFEST.read_text(encoding="utf-8"))
    extra = {
        "experiment": {"final_ablation": "final component ablation on one code state: A / B / R / O / G0 / G1 / G1L generated here; B2 / C_V0 / C_V1 / C_V1_links reused from results/kg_hardening_eval/",
                       "graph_merge_fix": "graph merge fix measurement: GF (v3 docgraph definition, legacy graph_expand, router OFF) and GFL (+ use_related_links) on the FIXED "
                                          "_semantic_merge (CrossEncoder order only); B2 reused from results/kg_hardening_eval/ (B2 has no layer and never calls _semantic_merge; "
                                          "verified by the smoke stage's plain-search comparison on all 42 questions)"}[fa.EXPERIMENT],
        "experiment_id": fa.EXPERIMENT,
        "branch": g["branch"],
        "merged_commit_person_b": kg_merged(km), "v3_reference": {"commit": fa.V3_COMMIT, "results": "results/perf_report/ (never modified)"},
        "interpreter": sys.executable,
        "arms_generated": {a: fa.arm_settings(a) for a in fa.ARMS_NEW},
        "arms_reused": {a: fa.arm_settings(a) for a in fa.ARMS_REUSED},
        "reused_arms_verification": reused,
        "runs_per_arm": fa.RUNS,
        "question_file": "eval/perf_report/questions.jsonl (unchanged, 42 questions; sha256 " + sha256_file(h.QUESTIONS)[:16] + ")",
        "retrieval_index_used": "data/experiments/combined_retrieval/vectorstore (SciFact chunks filtered at serving time in every retrieval arm)",
        "answer_cache": "none: every answer generated fresh (cached=false on every record)",
        "judge": "same local model as the generator, temperature 0, E14a prompts; every arm judged at the full level; prompt cache seeded read-only from "
                 "results/perf_report/judge_cache.jsonl and results/kg_hardening_eval/judge_cache.jsonl; new verdicts -> results/final_ablation/judge_cache.jsonl",
        "citation_check": "integration.qa.citations (NLI verifier) on every retrieval arm, flagging only; n/a for A",
        "decoding_note": h.SEED_NOTE,
        "context_budget": {"B": "shared 6 blocks (RagConfig())", "every other retrieval arm": "5 database + 3 document blocks (RagConfig.b2(); never tuned)"},
        "router": "unchanged: auto chain laya_finetuned -> embedding -> rule, router_conf_threshold 0.5 (data/eval/system_calibration.json); arms R and C_* only; "
                  "router OFF = no routing, both sources searched (B2 behaviour)",
        "ontology_setting_in_graph_arms": "as the v3 docgraph_only arm: the FAISS query is NOT expanded with ontology terms (DocGraphOnlyLayer.normalise_query returns the question); "
                                          "the query gate's concept classification still sets the graph weight 0.5 / 0.15 / 0.0",
        "semantic_layer": {"seeds": "GRAPH_SEEDS (5)", "candidates": "GRAPH_CANDIDATES (20)", "max_chunks_per_doc": RagConfig().semantic_max_chunks_per_doc,
                           "gate": "hybrid/query_gate.graph_weight -> 0.5 / 0.15 / 0.0 (0.0 disables the graph for that question)", "V1_options": fa.V1_OPTIONS},
        "graph": {"path": "knowledge_graph/output/graph.json (as rebuilt for the KG-hardening run; unchanged)", "sha256": sha256_file(graph) if graph.exists() else "missing",
                  "related_to": km.get("extra", {}).get("graph", {}).get("related_to")},
        "parser": "structured/query_parser.py blob " + _git("hash-object", "structured/query_parser.py")[:10] + " (merged Person B parser; same blob as the KG-hardening run: "
                  + str(km.get("extra", {}).get("parser")) + ")",
        "ollama_model_digest": (health or {}).get("digest"), "ollama_quantization": (health or {}).get("quantization"),
        "power_at_start": (health or {}).get("power"),
        "smoke_test": f"results/{fa.RES.name}/smoke_test.json (3 questions x {len(fa.ARMS_NEW)} generated arms, run 1; not part of raw_answers.jsonl)",
        "time_estimate": f"results/{fa.RES.name}/time_estimate.json",
        "semantic_merge": "integration/rag/pipeline.py::_semantic_merge as of HEAD: " + ("FIXED 2026-11-11 (CrossEncoder order only)" if fa.EXPERIMENT == "graph_merge_fix"
                                                                                           else "see git history of the file for the state at this commit"),
    }
    m = build_manifest(rag_config=RagConfig.b2(), qa_config=QAConfig(), index_dirs=index_dirs, extra=extra)
    fa.RES.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(m, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    log(f"manifest written (git {m['git']['commit'][:8]}, dirty={m['git']['dirty']}); reused arms verified: code identical, graph identical")
    return m


def kg_merged(km: dict) -> str | None:
    return km.get("extra", {}).get("merged_commit_person_b")


# ---------------------------------------------------------------------------------------------------------------------------------
# smoke test
# ---------------------------------------------------------------------------------------------------------------------------------
def _docs(top10):
    docs = []
    for r in top10:
        d = (r.get("metadata") or {}).get("provenance", {}).get("document_id") or r["record_id"]
        if d not in docs:
            docs.append(d)
    return docs


def retrieval_diff(rig: fa.Rig, qs: dict) -> dict:
    """No-LLM check on all 42 questions: the document search with no layer (B2 behaviour) and with each of the four layers (same call
    Rig.generate makes, no routing), so that we know BEFORE the long run whether every layer changes what it is supposed to change."""
    rig.pipeline.unstructured.exclude_scifact = True
    arms = ["plain"] + fa.LAYER_ARMS
    pairs = [(a, b) for a, b in (("G1", "G0"), ("G1L", "G1"), ("GFL", "GF")) if a in fa.LAYER_ARMS and b in fa.LAYER_ARMS]
    b2 = {k[1]: r for k, r in fa.load_reused(check_counts=False, arms=["B2"])[0].items() if k[2] == 1}     # stored B2 run 1 (reused arm)
    per_q, summary = [], {"questions": 0, "gate_weight_positive": 0, "plain_search_equals_stored_B2_run1_chunks": 0,
                          **{f"{a}_docs_differ_from_plain": 0 for a in fa.LAYER_ARMS}, **{f"{a}_added_chunks": 0 for a in fa.LAYER_ARMS},
                          **{f"{a}_query_differs_from_question": 0 for a in fa.LAYER_ARMS},
                          **{f"{a}_docs_differ_from_{b}": 0 for a, b in pairs}, **{f"{a}_added_differ_from_{b}": 0 for a, b in pairs},
                          "related_neighbours_added_total": 0}
    for qid, q in qs.items():
        row = {"id": qid, "category": q["category"]}
        for arm in arms:
            layer = None if arm == "plain" else rig.layers[arm]
            before = layer.stats["related_neighbours_added"] if layer else 0
            top10 = rig.pipeline.unstructured.search(q["query"], faiss_top_k=10, rerank_top_k=10, semantic=layer)
            added = [r["record_id"] for r in top10 if (r.get("metadata") or {}).get("semantic_added")]
            first = next((r for r in top10 if (r.get("metadata") or {}).get("semantic")), None)
            info = ((first or {}).get("metadata", {}).get("semantic", {}) or {})
            row[arm] = {"doc_top10": _docs(top10), "chunk_top10": [r["record_id"] for r in top10], "added_chunks": added, "neighbour_docs": info.get("neighbour_docs") or [],
                        "graph_weight": info.get("graph_weight"), "concept": info.get("concept"),
                        "related_neighbours_added": (layer.stats["related_neighbours_added"] - before) if layer else 0,
                        "normalised_query": layer.normalise_query(q["query"])[0] if layer is not None else q["query"]}
            if layer is not None:
                summary[f"{arm}_added_chunks"] += len(added)
                summary[f"{arm}_docs_differ_from_plain"] += row[arm]["doc_top10"] != row["plain"]["doc_top10"]
                summary[f"{arm}_query_differs_from_question"] += row[arm]["normalised_query"] != q["query"]
                summary["related_neighbours_added_total"] += row[arm]["related_neighbours_added"] if fa.LAYER_SPECS[arm][2] else 0
        summary["questions"] += 1
        gw_arm = fa.GRAPH_ARMS[0] if fa.GRAPH_ARMS else None
        summary["gate_weight_positive"] += bool(gw_arm) and (row[gw_arm]["graph_weight"] or 0.0) > 0
        row["plain_equals_stored_B2_run1"] = qid in b2 and row["plain"]["chunk_top10"] == b2[qid]["doc_top10_chunks"]
        summary["plain_search_equals_stored_B2_run1_chunks"] += row["plain_equals_stored_B2_run1"]
        for a, b in pairs:
            summary[f"{a}_docs_differ_from_{b}"] += row[a]["doc_top10"] != row[b]["doc_top10"]
            summary[f"{a}_added_differ_from_{b}"] += row[a]["added_chunks"] != row[b]["added_chunks"]
        per_q.append(row)
    return {"summary": summary, "per_question": per_q}


def smoke(rig: fa.Rig) -> dict:
    qs = {q["id"]: q for q in h.load_questions()}
    rows = []
    for arm in fa.ARMS_NEW:
        for qid in SMOKE_IDS:
            rec = rig.generate(arm, qs[qid], 1)
            s = rec.get("semantic") or {}
            rows.append({"arm": arm, "id": qid, "category": rec["category"], "arm_label_in_record": rec["arm"], "arm_config": rec["arm_config"],
                         "route": (rec.get("route") or {}).get("final"), "graph_weight": s.get("graph_weight"), "concept": s.get("concept"),
                         "normalised_query": s.get("normalised_query"), "n_added_chunks": len(s.get("added_chunks") or []), "added_chunks": s.get("added_chunks") or [],
                         "neighbour_docs": s.get("neighbour_docs") or [], "related_neighbours_added": s.get("related_neighbours_added"),
                         "n_structured_ids": len(rec.get("structured_ids") or []), "doc_top10": rec["doc_top10"],
                         "prompt_docs": [b["doc_id"] for b in rec["prompt_blocks"] if b["source"] == "unstructured"],
                         "n_prompt_blocks": len(rec["prompt_blocks"]), "latency_s": rec["latency_s"], "prompt_tokens": rec["prompt_tokens"], "answer_head": rec["answer"][:160]})
            log(f"smoke {arm:4s} {qid:5s} route={rows[-1]['route']} gw={rows[-1]['graph_weight']} added={rows[-1]['n_added_chunks']} links={rows[-1]['related_neighbours_added']} "
                f"blocks={rows[-1]['n_prompt_blocks']} top3={rec['doc_top10'][:3]} {rec['latency_s']}s")
    label_ok = all(r["arm_label_in_record"] == r["arm"] and r["arm_config"]["layer"] == (r["arm"] if r["arm"] in fa.LAYER_ARMS else None) for r in rows)
    by = {(r["arm"], r["id"]): r for r in rows}
    has = set(fa.ARMS_NEW)
    checks = {}
    if "A" in has:
        checks["A_has_no_retrieval"] = all(not by[("A", i)]["doc_top10"] and by[("A", i)]["n_prompt_blocks"] == 0 for i in SMOKE_IDS)
    if "B" in has:
        checks["B_has_no_route_and_no_layer"] = all(by[("B", i)]["route"] is None and by[("B", i)]["graph_weight"] is None for i in SMOKE_IDS)
    if "R" in has:
        checks["R_has_a_route"] = all(by[("R", i)]["route"] is not None for i in SMOKE_IDS)
    checks["non_router_arms_have_no_route"] = all(by[(a, i)]["route"] is None for a in fa.ARMS_NEW if a != "R" for i in SMOKE_IDS)
    if "O" in has:
        checks["O_adds_no_graph_chunks"] = all(by[("O", i)]["n_added_chunks"] == 0 for i in SMOKE_IDS)
        checks["O_rewrites_a_query"] = any(by[("O", i)]["normalised_query"] not in (None, qs[i]["query"]) for i in SMOKE_IDS)
    for a in fa.GRAPH_ARMS:
        checks[f"{a}_adds_chunks_somewhere"] = any(by[(a, i)]["n_added_chunks"] > 0 for i in SMOKE_IDS)
        checks[f"{a}_query_not_rewritten"] = all(by[(a, i)]["normalised_query"] in (None, qs[i]["query"]) for i in SMOKE_IDS)
    diff = retrieval_diff(rig, qs)
    sm = diff["summary"]
    verdict = {"arm_labels_match_configuration": label_ok, **checks}
    if fa.EXPERIMENT == "final_ablation":
        verdict["G1_differs_from_G0_on_42_questions"] = sm["G1_added_differ_from_G0"] > 0 or sm["G1_docs_differ_from_G0"] > 0
        verdict["G1L_link_hop_adds_documents"] = sm["related_neighbours_added_total"] > 0
        verdict["O_changes_the_query_on_42_questions"] = sm["O_query_differs_from_question"] > 0
        gate = verdict["G1_differs_from_G0_on_42_questions"]
    else:   # graph_merge_fix: GF must change retrieval vs the plain search somewhere, GFL must add link documents, and the plain search must equal the stored B2
        verdict["GF_differs_from_plain_on_42_questions"] = sm["GF_docs_differ_from_plain"] > 0
        verdict["GFL_link_hop_adds_documents"] = sm["related_neighbours_added_total"] > 0
        verdict["plain_search_equals_stored_B2_run1_on_all_42"] = sm["plain_search_equals_stored_B2_run1_chunks"] == sm["questions"]
        gate = verdict["GF_differs_from_plain_on_42_questions"] and verdict["plain_search_equals_stored_B2_run1_on_all_42"]
    verdict["proceed"] = label_ok and all(checks.values()) and gate
    out = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "smoke_ids": SMOKE_IDS, "rows": rows, "retrieval_diff": diff, "verdict": verdict}
    (fa.RES / "smoke_test.json").write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    log(f"smoke verdict: {verdict}")
    log(f"retrieval diff summary (42 questions): {sm}")
    if not verdict["proceed"]:
        log("SMOKE TEST FAILED: settings not applied as intended; STOP (no generation)")
    return out


# ---------------------------------------------------------------------------------------------------------------------------------
# runtime estimate (from measured timings; nothing invented)
# ---------------------------------------------------------------------------------------------------------------------------------
def estimate() -> dict:
    v3 = json.loads((fa.V3_RES / "metrics.json").read_text(encoding="utf-8"))["arms"]
    kgm = json.loads((fa.KG_RES / "metrics.json").read_text(encoding="utf-8"))["arms"]
    analog = {"A": ("v3", "A"), "B": ("v3", "B"), "R": ("v3", "router"), "O": ("v3", "ontology"), "G0": ("v3", "docgraph"), "G1": ("kg", "C_V1"), "G1L": ("kg", "C_V1_links"),
              "GF": ("v3", "docgraph"), "GFL": ("kg", "C_V1_links")}
    gen = {}
    for arm, (src, name) in ((a, analog[a]) for a in fa.ARMS_NEW):
        a = (v3 if src == "v3" else kgm)[name]
        med = a["latency_median_s"]
        gen[arm] = {"analog": f"{src}:{name}", "latency_median_s": med, "n": 42 * fa.RUNS, "estimate_s": round(med * 42 * fa.RUNS * 1.15, 0)}   # +15% for p95 tail
    # scoring: the KG-hardening scoring stage measured 504 records in (17:18:01 - 15:44:39) = 5602 s with its judge cache seeded from v3
    kg_rate = 5602 / 504
    n_new = 42 * fa.RUNS * len(fa.ARMS_NEW)
    out = {"generated_utc": datetime.now(timezone.utc).isoformat(), "generation_per_arm": gen,
           "generation_total_s": sum(x["estimate_s"] for x in gen.values()), "n_generations": n_new,
           "scoring": {"basis": "KG-hardening scoring stage: 504 records in 5602 s (11.1 s/record, judge cache seeded; A/B/R/O/G0 prompts may hit the v3 cache more often)",
                       "rate_s_per_record": round(kg_rate, 1), "estimate_s": round(kg_rate * n_new, 0)},
           "model_load_and_warmup_s": 180}
    out["total_estimate_min"] = round((out["generation_total_s"] + out["scoring"]["estimate_s"] + out["model_load_and_warmup_s"]) / 60, 0)
    fa.RES.mkdir(parents=True, exist_ok=True)
    (fa.RES / "time_estimate.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    log(f"runtime estimate: generation {out['generation_total_s'] / 60:.0f} min for {n_new} answers "
        f"({', '.join(f'{a} ~{x['estimate_s'] / 60:.0f} min' for a, x in gen.items())}); scoring ~{out['scoring']['estimate_s'] / 60:.0f} min; total ~{out['total_estimate_min']:.0f} min")
    return out


# ---------------------------------------------------------------------------------------------------------------------------------
# generation
# ---------------------------------------------------------------------------------------------------------------------------------
def generate(rig: fa.Rig, runs: int) -> None:
    questions = h.load_questions()
    done = {(r["arm"], r["id"], r["run"]) for r in h.read_jsonl(fa.RAW)}
    plan = [(arm, q, run) for arm in fa.ARMS_NEW for run in range(1, runs + 1) for q in questions]   # arm -> run -> question (as v3)
    todo = [p for p in plan if (p[0], p[1]["id"], p[2]) not in done]
    log(f"plan: {len(plan)} generations, {len(plan) - len(todo)} already done, {len(todo)} to run")
    started, last_completion, n_ok, n_fail = time.time(), None, 0, 0
    for i, (arm, q, run) in enumerate(todo, 1):
        try:
            rec = rig.generate(arm, q, run)
        except Exception as exc:  # noqa: BLE001  -- after the client's own timeout + retries: record the failure and carry on
            n_fail += 1
            h.append_jsonl(fa.FAILURES, {"stage": "generate", "arm": arm, "id": q["id"], "run": run, "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                                         "timestamp_utc": datetime.now(timezone.utc).isoformat()})
            log(f"FAILED {arm} {q['id']} run{run}: {type(exc).__name__}: {str(exc)[:120]} (recorded in failures.jsonl; continuing)")
            continue
        now = time.time()
        rec["gap_since_previous_s"] = None if last_completion is None else round(now - last_completion, 1)
        rec["suspect_gap"] = bool(last_completion is not None and now - last_completion > h.SUSPECT_GAP_S)
        last_completion = now
        rec["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
        h.append_jsonl(fa.RAW, rec)
        n_ok += 1
        if i % 10 == 0 or i == len(todo):
            elapsed = now - started
            eta = elapsed / i * (len(todo) - i)
            log(f"HEARTBEAT [{i}/{len(todo)}] ok={n_ok} failed={n_fail} last={arm} {q['id']} run{run} {rec['latency_s']}s ETA {eta / 60:.0f} min")
    log(f"generation loop done: ok={n_ok} failed={n_fail}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["health", "smoke", "estimate", "generate"])
    ap.add_argument("--runs", type=int, default=fa.RUNS)
    ap.add_argument("--allow-battery", action="store_true", help="start generation although the machine is on battery power")
    args = ap.parse_args()
    if args.stage == "estimate":
        estimate()
        return
    if args.stage == "generate":
        health = health_stage(write=False)      # probe only: the manifest must be written on a clean tree, before any output file
        ensure_manifest(health)
        health_stage(write=True, out=health)
        pw = health["power"]
        if pw.get("on_battery") and not args.allow_battery:
            raise SystemExit(f"machine is on battery power (charge {pw.get('battery_charge_pct')}%, est. {pw.get('battery_estimated_runtime_min')} min); "
                             "refusing to start the long run (use --allow-battery to override)")
        if not pw.get("sleep_disabled"):
            log(f"WARNING: sleep timeout is not 0 on both AC and DC: {pw.get('sleep_after_s')}")
    else:
        health = health_stage()
    if args.stage == "health":
        return
    t0 = time.time()
    rig = fa.Rig()
    log("models loaded; warming up")
    rig.warm_up()
    if args.stage == "smoke":
        smoke(rig)
    else:
        generate(rig, args.runs)
    log(f"{args.stage} finished in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
