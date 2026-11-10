"""
Read-only check of the rebuilt graph (after `build_related_aliases` + `graph_builder` on the kg-hardening branch) against the graph the
v3 report used (a copy taken before the rebuild). No LLM, no retrieval.

    .venv_colpali/Scripts/python.exe eval/kg_hardening_eval/verify_graph_rebuild.py <old_graph.json>  -> results/kg_hardening_eval/setup_logs/graph_rebuild_check.json

Checks: (1) node/edge differences between old and new graph; (2) RELATED_TO resolution in the new graph; (3) how many RELATED_TO links our
semantic layer's reader (integration/rag/semantic_layer._read_related_edges) can resolve against the indexed documents; (4) for every seed list
the v3 C arm recorded (run 1), legacy graph_expand() on old vs new graph (V0 reproduction) and the V1 profile on the new graph (must differ
somewhere, otherwise the knobs do nothing on this data).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(ROOT / "hybrid")):
    if p not in sys.path:
        sys.path.insert(0, p)
from knowledge_graph.graph_augmented_retrieval import DEFAULT_BRIDGES, GRAPH_CANDIDATES, graph_expand, load_graph_index  # noqa: E402
from integration.rag.semantic_layer import GRAPH_JSON, _read_related_edges  # noqa: E402

V1 = {"hub_fraction": 0.05, "specificity": True, "max_documents": 3}
INDEX_META = ROOT / "data" / "experiments" / "combined_retrieval" / "vectorstore" / "chunk_metadata.json"
V3_RAW = ROOT / "results" / "perf_report" / "raw_answers.jsonl"
OUT = ROOT / "results" / "kg_hardening_eval" / "setup_logs" / "graph_rebuild_check.json"


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def node_set(g, drop_stub_documents):
    out = set()
    for n in g["nodes"]:
        if drop_stub_documents and n["label"] == "Document" and not n["properties"].get("resolved", True):
            continue
        out.add((n["label"], n["key"]))
    return out


def edge_set(g, types=None, exclude=()):
    key = {n["id"]: n["key"] for n in g["nodes"]}
    return {(key[e["source"]], e["type"], key[e["target"]]) for e in g["edges"]
            if (types is None or e["type"] in types) and e["type"] not in exclude}


def main(old_path: str) -> None:
    old, new = load(old_path), load(GRAPH_JSON)
    out = {"old_graph": old_path, "new_graph": str(GRAPH_JSON)}
    # (1) structure
    out["nodes"] = {"old": len(old["nodes"]), "new": len(new["nodes"]),
                    "old_stub_documents": sum(1 for n in old["nodes"] if n["label"] == "Document" and not n["properties"].get("resolved", True)),
                    "new_stub_documents": sum(1 for n in new["nodes"] if n["label"] == "Document" and not n["properties"].get("resolved", True)),
                    "non_stub_nodes_identical": node_set(old, True) == node_set(new, True)}
    out["edges"] = {"old": len(old["edges"]), "new": len(new["edges"]),
                    "non_RELATED_TO_edges_identical": edge_set(old, exclude=("RELATED_TO",)) == edge_set(new, exclude=("RELATED_TO",)),
                    "RELATED_TO_old": len(edge_set(old, {"RELATED_TO"})), "RELATED_TO_new": len(edge_set(new, {"RELATED_TO"}))}
    # (2) resolution in the new graph
    rel_new = [e for e in new["edges"] if e["type"] == "RELATED_TO"]
    out["related_to_new"] = {"total": len(rel_new), "resolved_true": sum(1 for e in rel_new if e["properties"].get("resolved")),
                             "via_alias": sum(1 for e in rel_new if e["properties"].get("via_alias")),
                             "unresolved": sum(1 for e in rel_new if not e["properties"].get("resolved"))}
    # (3) our reader against the indexed documents
    idx_docs = {m["document_id"] for m in load(INDEX_META)}
    for name, path in (("old", old_path), ("new", GRAPH_JSON)):
        pairs = _read_related_edges(Path(path))
        out[f"semantic_layer_reader_{name}"] = {"links": len(pairs), "resolvable_both_endpoints_indexed": sum(1 for a, b in pairs if a in idx_docs and b in idx_docs)}
    # (4) V0 reproduction + V1 difference on the seeds the v3 C arm recorded
    gi_old, gi_new = load_graph_index(Path(old_path)), load_graph_index(GRAPH_JSON)
    out["graph_index"] = {"document_count_old": gi_old.document_count, "document_count_new": gi_new.document_count,
                          "hub_threshold_V1_new": V1["hub_fraction"] * gi_new.document_count,
                          "related_pairs_in_index_new": sum(len(v) for v in gi_new.related.values()) // 2}
    rows, same_v0, same_as_v3, v1_differs = [], 0, 0, 0
    for line in V3_RAW.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["arm"] != "C" or r["run"] != 1 or not (r.get("semantic") or {}).get("seeds"):
            continue
        seeds = r["semantic"]["seeds"]
        v0_old = [x["document_id"] for x in graph_expand(seeds, gi_old, bridges=DEFAULT_BRIDGES, limit=GRAPH_CANDIDATES)]
        v0_new = [x["document_id"] for x in graph_expand(seeds, gi_new, bridges=DEFAULT_BRIDGES, limit=GRAPH_CANDIDATES)]
        v1_new = [x["document_id"] for x in graph_expand(seeds, gi_new, bridges=DEFAULT_BRIDGES, limit=GRAPH_CANDIDATES, **V1)]
        v3_neigh = r["semantic"].get("neighbour_docs") or []
        same_v0 += v0_old == v0_new
        same_as_v3 += v0_new == v3_neigh
        v1_differs += v1_new != v0_new
        rows.append({"id": r["id"], "seeds": seeds, "graph_weight": r["semantic"].get("graph_weight"), "v0_old_eq_v0_new": v0_old == v0_new,
                     "v0_new_eq_v3_recorded_neighbours": v0_new == v3_neigh, "v1_differs_from_v0": v1_new != v0_new,
                     "n_v0": len(v0_new), "n_v1": len(v1_new), "v1_new": v1_new, "v0_new_top5": v0_new[:5]})
    out["v0_reproduction"] = {"seed_lists_checked": len(rows), "v0_identical_old_vs_new_graph": same_v0, "v0_new_identical_to_v3_recorded_neighbours": same_as_v3,
                             "v1_differs_from_v0": v1_differs, "rows": rows}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    for k in ("nodes", "edges", "related_to_new", "semantic_layer_reader_old", "semantic_layer_reader_new", "graph_index"):
        print(k, json.dumps(out[k]))
    v = out["v0_reproduction"]
    print("v0_reproduction", {k: v[k] for k in v if k != "rows"})
    print("written", OUT)


if __name__ == "__main__":
    main(sys.argv[1])
