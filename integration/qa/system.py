"""
answer_query(query, config) -- the one backend entry point (the UI contains no pipeline logic).

    Query -> Router -> ( Structured | Unstructured | Hybrid(decomposed) | Abstain )
          -> Evidence fusion (rank-based RRF) -> Grounded generation
          -> sentence-level citations, each VERIFIED -> result dict

Return value (all keys always present):
    answer_text, sentences:[{text, citations, support_status, support}], evidence:[full provenance],
    route:{...router decision + final route...}, router_name, abstained, abstention:{layer, reason},
    hybrid_diagnostics, fallback, timings, config, error

Design rules enforced here
  * SQL / exact-match evidence and FAISS evidence are never score-combined; they meet only in RRF (rank-based).
  * Low router confidence -> hybrid (safer than a wrong single route); threshold calibrated on VAL.
  * Single-route retrieval that comes back weak triggers ONE retry against the other source (logged as
    `fallback`), never a silent substitution.
  * No unsupported claim is ever shown with a confident citation: every sentence carries support_status and,
    with drop_unsupported=True, unsupported sentences are removed from answer_text.
  * Failures (router, Ollama, graph file) degrade with a visible note; nothing raises to the caller.
"""

from __future__ import annotations

import threading
import time

from integration.qa import citations as cit
from integration.qa.abstain import abstention_result_text, retrieval_gate
from integration.qa.config import QAConfig
from integration.qa.evidence import assign_evidence_ids
from integration.qa.generation import generate
from integration.qa.retrieval import ColPaliAdapter, StructuredBackend, UnstructuredBackend
from integration.rag.fuse import reciprocal_rank_fusion
from query_router.base import RouteDecision
from query_router.decomposer import HybridDecomposer
from query_router.registry import build_router

_LOCK = threading.Lock()
_UNSTRUCTURED: UnstructuredBackend | None = None
_STRUCTURED = StructuredBackend()
_DECOMPOSERS: dict[str, HybridDecomposer] = {}


def get_unstructured() -> UnstructuredBackend:
    global _UNSTRUCTURED
    with _LOCK:
        if _UNSTRUCTURED is None:
            _UNSTRUCTURED = UnstructuredBackend()
        return _UNSTRUCTURED


def get_decomposer(model: str) -> HybridDecomposer:
    if model not in _DECOMPOSERS:
        _DECOMPOSERS[model] = HybridDecomposer(model)
    return _DECOMPOSERS[model]


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)


# ---------------------------------------------------------------------------
# routing
# ---------------------------------------------------------------------------
def _route(query: str, cfg: QAConfig) -> tuple[RouteDecision, dict]:
    info: dict = {"requested_router": cfg.router, "errors": []}
    if cfg.forced_route:
        d = RouteDecision.from_label(cfg.forced_route, router_name=f"forced:{cfg.forced_route}",
                                     model_id="ablation override")
        info["forced"] = True
        return d, info
    try:
        router = build_router(cfg.router, {"chain": cfg.router_chain})
        return router.route(query), info
    except Exception as exc:  # noqa: BLE001
        info["errors"].append(f"{cfg.router}: {str(exc)[:200]}")
        try:
            d = build_router("rule").route(query)
            info["emergency_fallback"] = "rule"
            return d, info
        except Exception as exc2:  # noqa: BLE001
            info["errors"].append(f"rule: {str(exc2)[:200]}")
            d = RouteDecision.from_label("hybrid", router_name="none", model_id="no router available")
            info["emergency_fallback"] = "hybrid (no router available)"
            return d, info


# ---------------------------------------------------------------------------
# retrieval helpers
# ---------------------------------------------------------------------------
def _retrieve_structured(query: str, cfg: QAConfig, origin: str, hybrid_sub: str | None = None) -> tuple[list, dict]:
    """Structured retrieval for a query (or a hybrid structured sub-query).

    The existing parser is a first-substring-match rule set with known quirks, so for a direct structured
    question the LLM rewriter proposes a parser-friendly form that is VALIDATED against the parser; if its
    table disagrees with the parser's reading of the original, the validated rewrite wins and the disagreement
    is recorded. If no rewrite is executable the original query is run as-is.
    """
    if hybrid_sub is not None:  # decomposer already produced + validated this sub-query
        return _STRUCTURED.search(hybrid_sub, cfg, origin=origin)

    notes = []
    ok_orig, parsed_orig = _STRUCTURED.can_execute(query)
    decomposer = get_decomposer(cfg.decomposer_model)
    rewrite = decomposer.rewrite_for_parser(query)
    chosen = query
    if rewrite["structured"]:
        orig_table = parsed_orig.get("table") if ok_orig else None
        new_table = (rewrite["parsed"] or {}).get("table")
        if (not ok_orig) or orig_table != new_table:
            chosen = rewrite["structured"]
            notes.append(f"used rewritten sub-query {chosen!r} (original parsed to table={orig_table!r}, rewrite -> {new_table!r})")
    evidence, diag = _STRUCTURED.search(chosen, cfg, origin="original" if chosen == query else "rewrite")
    diag["rewrite_notes"] = notes + rewrite.get("notes", [])
    diag["original_query"] = query
    return evidence, diag


def _fuse(structured_ev: list, unstructured_ev: list, cfg: QAConfig) -> list:
    lists = [l for l in (structured_ev, unstructured_ev) if l]
    if not lists:
        return []
    fused = reciprocal_rank_fusion(*lists, k=cfg.rrf_k)
    out = []
    for item in fused:
        item = dict(item)
        item["metadata"] = dict(item["metadata"])
        item["metadata"]["fusion"] = item.pop("fusion")
        out.append(item)
    return assign_evidence_ids(out)[: cfg.top_n_context]


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def answer_query(query: str, config: QAConfig | None = None) -> dict:
    cfg = config or QAConfig()
    t_start = time.perf_counter()
    timings: dict = {}
    result: dict = {
        "query": query, "answer_text": "", "sentences": [], "evidence": [], "route": {}, "router_name": None,
        "abstained": False, "abstention": {"layer": None, "reason": None}, "hybrid_diagnostics": None,
        "fallback": {"occurred": False}, "timings": timings, "config": cfg.as_dict(), "error": None,
        "answer_raw": None, "components": [],
    }

    # ---- 1. route --------------------------------------------------------
    t = time.perf_counter()
    decision, route_info = _route(query, cfg)
    timings["router_ms"] = _ms(t)
    final_route = decision.label
    if not route_info.get("forced") and decision.label != "out_of_scope" \
            and decision.confidence < cfg.router_conf_threshold:
        final_route = "hybrid"
        route_info["low_confidence_to_hybrid"] = {"confidence": decision.confidence,
                                                   "threshold": cfg.router_conf_threshold,
                                                   "original_label": decision.label}
    result["route"] = {**decision.as_dict(), "final_route": final_route, **route_info}
    result["router_name"] = decision.router_name

    # ---- 2. layer-1 abstention: out of scope ------------------------------
    if final_route == "out_of_scope":
        result.update(abstained=True, answer_text=abstention_result_text(cfg),
                      abstention={"layer": 1, "reason": "the router judged this question out of scope"})
        timings["total_ms"] = _ms(t_start)
        return result

    # ---- 3. retrieval ------------------------------------------------------
    t = time.perf_counter()
    structured_ev: list = []
    unstructured_ev: list = []
    u_diag: dict | None = None
    s_diag: dict | None = None
    sub_queries = {"structured": None, "unstructured": None}
    decomposition = None
    try:
        unstructured = get_unstructured() if final_route in ("unstructured", "hybrid") or cfg.retry_other_source_on_weak else None

        if final_route == "structured":
            structured_ev, s_diag = _retrieve_structured(query, cfg, origin="original")
            sub_queries["structured"] = query

        elif final_route == "unstructured":
            unstructured_ev, u_diag = unstructured.search(query, cfg, origin="original")
            sub_queries["unstructured"] = query

        else:  # hybrid: decompose, then run BOTH retrievers independently
            td = time.perf_counter()
            decomposition = get_decomposer(cfg.decomposer_model).decompose(query)
            timings["decompose_ms"] = _ms(td)
            sub_queries = {"structured": decomposition["structured"], "unstructured": decomposition["unstructured"]}
            if decomposition["structured"]:
                structured_ev, s_diag = _retrieve_structured(query, cfg, origin="structured_subquery",
                                                             hybrid_sub=decomposition["structured"])
            unstructured_ev, u_diag = unstructured.search(decomposition["unstructured"], cfg,
                                                          origin="unstructured_subquery")
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"retrieval failed: {exc}"
        result.update(abstained=True, answer_text=cfg.abstention_message,
                      abstention={"layer": 2, "reason": f"retrieval error: {str(exc)[:160]}"})
        timings["total_ms"] = _ms(t_start)
        return result
    timings["retrieval_ms"] = _ms(t)

    # ---- 4. layer-2 gate + one-shot fallback to the other source ----------
    gate = retrieval_gate(final_route, structured_ev, unstructured_ev, u_diag, cfg)
    if gate["abstain"] and cfg.retry_other_source_on_weak and final_route in ("structured", "unstructured"):
        t = time.perf_counter()
        try:
            if final_route == "structured":
                alt_ev, alt_diag = get_unstructured().search(query, cfg, origin="original")
                unstructured_ev, u_diag = alt_ev, alt_diag
                other = "unstructured"
            else:
                alt_ev, alt_diag = _retrieve_structured(query, cfg, origin="original")
                structured_ev, s_diag = alt_ev, alt_diag
                other = "structured"
            regate = retrieval_gate("hybrid", structured_ev, unstructured_ev, u_diag, cfg)
            result["fallback"] = {"occurred": True, "from_route": final_route, "to_source": other,
                                  "reason": gate["reason"], "recovered": not regate["abstain"]}
            if not regate["abstain"]:
                gate = {**regate, "abstain": False}
                final_route = other
        except Exception as exc:  # noqa: BLE001
            result["fallback"] = {"occurred": True, "from_route": final_route, "error": str(exc)[:160],
                                  "recovered": False}
        timings["fallback_ms"] = _ms(t)

    result["route"]["final_route"] = final_route

    # keep only usable sources in the context (weak document chunks are noise, not evidence)
    ctx_structured = structured_ev if gate["structured_usable"] else []
    ctx_unstructured = unstructured_ev if gate["unstructured_usable"] else []
    result["components"] = [(s_diag or {}).get("components"), (u_diag or {}).get("components")]
    result["retrieval"] = {"structured": s_diag, "unstructured": u_diag, "gate": gate}

    if gate["abstain"] or not (ctx_structured or ctx_unstructured):
        result.update(abstained=True, answer_text=abstention_result_text(cfg),
                      abstention={"layer": 2, "reason": gate["reason"] or "no usable evidence"})
        if final_route == "hybrid" or decomposition:
            result["hybrid_diagnostics"] = _hybrid_diag(decomposition, sub_queries, gate, [], None)
        timings["total_ms"] = _ms(t_start)
        return result

    # ---- 5. fusion ---------------------------------------------------------
    t = time.perf_counter()
    evidence = _fuse(ctx_structured, ctx_unstructured, cfg)
    timings["fusion_ms"] = _ms(t)
    by_id = {e["metadata"]["evidence_id"]: e for e in evidence}

    # ---- 6. grounded generation -------------------------------------------
    t = time.perf_counter()
    try:
        raw = generate(query, evidence, cfg, sub_queries if final_route == "hybrid" else None)
    except Exception as exc:  # noqa: BLE001
        result.update(error=f"generation unavailable: {str(exc)[:200]}", evidence=[cit.resolve_provenance(e) for e in evidence],
                      answer_text="The answer generator is unavailable, so only the retrieved evidence is shown.",
                      abstained=False)
        timings["total_ms"] = _ms(t_start)
        return result
    timings["generation_ms"] = _ms(t)
    result["answer_raw"] = raw

    # ---- 7. parse + verify citations ----------------------------------------
    t = time.perf_counter()
    parsed = cit.parse_answer(raw, set(by_id))
    sentences = cit.verify_answer(parsed, by_id, cfg)
    timings["verification_ms"] = _ms(t)

    if parsed["insufficient"] or (not sentences and not parsed["unanswered"]):
        result.update(abstained=True, answer_text=abstention_result_text(cfg),
                      abstention={"layer": 3, "reason": "the generator reported insufficient evidence"},
                      evidence=[])
        if final_route == "hybrid":
            result["hybrid_diagnostics"] = _hybrid_diag(decomposition, sub_queries, gate, [], parsed)
        timings["total_ms"] = _ms(t_start)
        return result

    if cfg.drop_unsupported:
        sentences = [s for s in sentences if s["support_status"] != cit.UNSUPPORTED]
        if not sentences and not parsed["unanswered"]:
            result.update(abstained=True, answer_text=abstention_result_text(cfg),
                          abstention={"layer": 3, "reason": "every generated sentence failed citation verification"},
                          evidence=[])
            timings["total_ms"] = _ms(t_start)
            return result

    cited_ids = {c for s in sentences for c in s["citations"]}
    # evidence panel: everything the answer cited FIRST, then the rest of the retrieved context
    ordered = [e for e in evidence if e["metadata"]["evidence_id"] in cited_ids] + \
              [e for e in evidence if e["metadata"]["evidence_id"] not in cited_ids]
    provenance = []
    for e in ordered:
        p = cit.resolve_provenance(e)
        eid = p["evidence_id"]
        p["cited"] = eid in cited_ids
        p["cited_by_sentence"] = [i for i, s in enumerate(sentences) if eid in s["citations"]]
        p["supporting_spans"] = [s["support"]["supporting_span"] for s in sentences
                                 if s["support"].get("best_evidence_id") == eid and s["support"].get("supporting_span")]
        provenance.append(p)

    answer_lines = [s["text"] + "".join(f" [{c}]" for c in s["citations"]) for s in sentences]
    result.update(
        answer_text="\n".join(answer_lines),
        sentences=sentences,
        evidence=provenance,
        abstained=False,
    )
    if parsed["unanswered"]:
        result["answer_text"] += "\n" + "\n".join("NOT ANSWERED: " + u for u in parsed["unanswered"])
        result["unanswered"] = parsed["unanswered"]

    if final_route == "hybrid" or decomposition:
        cited_sources = [by_id[c]["source"] for s in sentences for c in s["citations"] if c in by_id]
        result["hybrid_diagnostics"] = _hybrid_diag(decomposition, sub_queries, gate, cited_sources, parsed)

    timings["total_ms"] = _ms(t_start)
    return result


def _hybrid_diag(decomposition: dict | None, sub_queries: dict, gate: dict, cited_sources: list,
                 parsed: dict | None) -> dict:
    unanswered = (parsed or {}).get("unanswered") or []
    return {
        "structured_sub_query": sub_queries.get("structured"),
        "unstructured_sub_query": sub_queries.get("unstructured"),
        "structured_half_found": gate["structured_usable"],
        "unstructured_half_found": gate["unstructured_usable"],
        "structured_parse_ok": (decomposition or {}).get("structured_parse_ok"),
        "decomposer_method": (decomposition or {}).get("structured_method"),
        "decomposer_notes": (decomposition or {}).get("notes"),
        "sources_cited_in_answer": sorted(set(cited_sources)),
        "unanswered_part": unanswered or None,
        "half_answered": bool(unanswered) or (gate["structured_usable"] != gate["unstructured_usable"]),
    }
