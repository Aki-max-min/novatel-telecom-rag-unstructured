"""
Builds a compact, provenance-labelled evidence context from a fused,
ranked Common-Result-Schema list. Never dumps every candidate -- selects
the top-N, drops empty/degenerate content, and dedups by identity.
"""

DEFAULT_TOP_N = 6
MIN_CONTENT_CHARS = 5


def _evidence_id(result: dict, index: int) -> str:
    return f"E{index + 1}"


def _provenance_label(result: dict) -> str:
    metadata = result.get("metadata", {}) or {}
    provenance = metadata.get("provenance")

    if result["source"] == "structured":
        return f"structured:{result['dataset']}#{result['record_id']}"

    if provenance:
        doc_id = provenance.get("document_id")
        chunk_id = provenance.get("chunk_id")
        page = provenance.get("page_number")
        label = f"unstructured:{result['dataset']}#{doc_id or result['record_id']}"
        if chunk_id and chunk_id != doc_id:
            label += f"/{chunk_id}"
        if page is not None:
            label += f"/page_{page}"
        return label

    return f"{result['source']}:{result['dataset']}#{result['record_id']}"


def _is_usable(result: dict) -> bool:
    content = (result.get("content") or "").strip()
    return len(content) >= MIN_CONTENT_CHARS


def build_context(fused_results: list[dict], top_n: int = DEFAULT_TOP_N,
                  per_source_budget: dict | None = None) -> dict:
    """
    fused_results: RRF-ranked Common-Schema list (fuse.reciprocal_rank_fusion
        output), best first.
    top_n: how many evidence blocks to keep (one budget shared by both sources).
    per_source_budget: optional {"structured": n_s, "unstructured": n_u}. When given it REPLACES the shared
        top_n: each source keeps its own best n blocks in fused order. This is the E14b fix for the
        context-budget truncation diagnosed in data/experiments/benchmark_base_vs_rag/failure_diagnostic.md
        (RRF interleaving split the shared 6-block budget about 3/3, so multi-row SQL answers lost rows).
        Default None keeps the original shared-budget behaviour exactly.

    Returns {"evidence": [...], "context_text": str} where each evidence
    entry is {"id", "source", "dataset", "record_id", "provenance_label",
    "content"} and context_text is the compact prompt-ready string.
    """
    usable = [r for r in fused_results if _is_usable(r)]

    seen = set()
    deduped = []
    for result in usable:
        key = (result["source"], result["dataset"], result["record_id"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(result)

    if per_source_budget is None:
        selected = deduped[:top_n]
    else:
        taken: dict[str, int] = {}
        selected = []
        for result in deduped:
            source = result["source"]
            if taken.get(source, 0) < per_source_budget.get(source, 0):
                selected.append(result)
                taken[source] = taken.get(source, 0) + 1

    evidence = []
    lines = []
    for index, result in enumerate(selected):
        evidence_id = _evidence_id(result, index)
        label = _provenance_label(result)
        content = result["content"].strip()

        evidence.append({
            "id": evidence_id,
            "source": result["source"],
            "dataset": result["dataset"],
            "record_id": result["record_id"],
            "provenance_label": label,
            "content": content,
            "metadata": result.get("metadata", {}),
        })
        lines.append(f"[{evidence_id}] ({result['source']} | {label})\n{content}")

    context_text = "\n\n".join(lines) if lines else ""

    return {"evidence": evidence, "context_text": context_text}
