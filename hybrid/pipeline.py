"""
Complete E13 candidate pipeline, one call:
    query gate (Phase 2) -> weighted RRF fusion + dedup (Phase 3) -> controlled rerank (Phase 4)
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import sqlite3  # noqa: E402

from fusion import fuse_and_select  # noqa: E402
from rerank import controlled_rerank  # noqa: E402

# Graph candidates (concept expansion) and resolved RELATED_TO links in the END-TO-END entry point run_hybrid_query.
# ON by default since the graph-fusion fix: fusion is now append-only (the graph is a candidate SOURCE, never a ranker;
# relevance is decided by the CrossEncoder rerank only). Pre-declared dev-set measurement (docs/E13_graph_fusion_fix.md):
# no question lost at R@1 or R@3 versus graph off, +1 question at R@5 on mini 9 -> adopted per the rule. The earlier
# hardening and link-decoupling FAIL verdicts were measured with the old bonus merge and are superseded.
# Turn off with graph_enabled=False / links_enabled=False (or these constants); run_hybrid_retrieval, which takes explicit
# candidate lists, is unchanged.
GRAPH_ENABLED = True
GRAPH_DISABLED_TRACE = "graph disabled by config"

LINKS_ENABLED = True
LINK_WEIGHT = 0.15   # on/off switch only since the fix (> 0 includes the link list); the value no longer ranks anything


def run_hybrid_retrieval(question: str, vector_candidates: list[dict],
                         graph_candidates: list[dict], max_pool: int = 20,
                         top_k: int = 5, model=None, mode: str = None, blend_weight: float = None,
                         link_candidates: list = None, link_weight: float = None) -> list[dict]:
    """Gate -> fuse -> dedupe (keeping up to max_pool) -> capped rerank -> top_k.
    `link_candidates` (optional) is the separate link list; link_weight defaults to LINK_WEIGHT."""
    pool = fuse_and_select(vector_candidates, graph_candidates, question, top_k=max_pool,
                           link_candidates=link_candidates,
                           link_weight=(LINK_WEIGHT if link_weight is None else link_weight))
    return controlled_rerank(question, pool, max_pool=max_pool, top_k=top_k, model=model,
                             mode=mode, blend_weight=blend_weight)


def run_hybrid_query(question: str, customer_id=None, as_of=None, max_pool: int = 20,
                     top_k: int = 5, model=None, mode: str = None, blend_weight: float = None,
                     graph_enabled: bool = None, links_enabled: bool = None) -> dict:
    """Route -> structured facts and/or fused-reranked documents, as TWO separate channels.

    Facts (structured_adapter, customer-scoped) and documents (vector + graph -> fuse -> dedup ->
    controlled rerank) are never fused with each other. `blocked` lists why a channel did not run
    (e.g. "needs_identity"). The existing run_hybrid_retrieval is unchanged.
    """
    from router import route_query
    from structured_adapter import fetch_customer_facts

    plan = route_query(question, customer_id)
    blocked, facts, documents, trace = [], [], [], {"intents_run": [], "documents_ran": False}

    if plan.outcome != "answer":
        blocked.append(plan.outcome)
    if plan.unrecognised_personal_request:
        # outcome stays "answer" (documents still run) but the answer layer must say it could not
        # tell which account detail was meant
        blocked.append("unrecognised_personal_request")

    if plan.outcome == "answer" and plan.route in ("structured", "both"):
        try:
            facts = fetch_customer_facts(customer_id, plan.structured_intents, as_of=as_of)
        except (sqlite3.Error, OSError) as exc:
            # structured DB missing/unreadable: executed=False with a note; documents still run
            facts = []
            trace["structured_executed"] = False
            trace["structured_note"] = f"structured data unavailable: {type(exc).__name__}: {exc}"
            blocked.append("structured_unavailable")
        else:
            trace["structured_executed"] = True
            trace["intents_run"] = list(plan.structured_intents)

    # Documents are never withheld because identity is missing (Phase 8d): they run for unstructured
    # and both routes, AND for any needs_identity outcome whatever the route (then flagged generic -
    # general policy/how-to material, not about this customer). Only a refused (other-customer)
    # request returns neither facts nor documents.
    documents_are_generic = plan.outcome == "needs_identity"
    if plan.outcome != "refuse_other_customer" and (
            plan.route in ("unstructured", "both") or plan.outcome == "needs_identity"):
        import retrievers
        build_candidates = retrievers.build_candidates
        use_graph = GRAPH_ENABLED if graph_enabled is None else graph_enabled
        use_links = LINKS_ENABLED if links_enabled is None else links_enabled
        # the graph index is loaded lazily and ONLY when the graph or the links are on; a missing or corrupt graph.json
        # gives empty graph/link lists and a trace note, never an exception
        graph_index, graph_reason = (retrievers.get_graph_index_safe() if (use_graph or use_links) else (None, None))
        graph_ok = graph_index is not None
        try:
            vector, graph, _ = build_candidates(question, graph_index=graph_index, graph_enabled=(use_graph and graph_ok))
        except (OSError, RuntimeError, ImportError, ValueError, KeyError) as exc:
            # models / FAISS index / chunk files missing or unreadable: the unstructured side returns nothing
            vector, graph = None, []
            trace["vector"] = f"vector retrieval unavailable: {type(exc).__name__}: {exc}"
            blocked.append("document_retrieval_unavailable")
        if vector is not None:
            trace["vector"] = "vector retrieval ok"
            if not use_graph:
                trace["graph"] = GRAPH_DISABLED_TRACE
            elif not graph_ok:
                trace["graph"] = f"graph unavailable: {graph_reason}"
            else:
                trace["graph"] = "graph enabled"
            links = []
            if use_links and graph_ok:
                vctx = retrievers.load_vector_context()
                links = retrievers.link_candidates_for(vector, graph_index, vctx["corpus"], vctx["person_a"].load_chunk_text)
            if not use_links:
                trace["links"] = "links disabled by config"
            elif not graph_ok:
                trace["links"] = "links unavailable: graph unavailable"
            else:
                trace["links"] = "links enabled"
            trace["linked_documents"] = [c["metadata"]["document_id"] for c in links]
            documents = run_hybrid_retrieval(question, vector, graph, max_pool=max_pool, top_k=top_k, model=model,
                                             mode=mode, blend_weight=blend_weight, link_candidates=links)
            trace["documents_ran"] = True
            trace["rerank_status"] = documents[0].get("rerank_status") if documents else None

    trace["customer_identified"] = customer_id is not None
    trace.update({"graph_weight": plan.graph_weight, "concept_hint": plan.concept_hint,
                  "unrecognised_personal_request": plan.unrecognised_personal_request,
                  "refusal_reason": plan.refusal_reason,
                  "fact_count": len(facts), "document_count": len(documents)})
    trace["documents_are_generic"] = bool(documents) and documents_are_generic
    return {"route_plan": plan.as_dict(), "facts": facts, "documents": documents,
            "documents_are_generic": bool(documents) and documents_are_generic,
            "blocked": blocked, "trace": trace}
