"""
Complete E13 candidate pipeline, one call:
    query gate (Phase 2) -> weighted RRF fusion + dedup (Phase 3) -> controlled rerank (Phase 4)
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from fusion import fuse_and_select  # noqa: E402
from rerank import controlled_rerank  # noqa: E402

# Graph candidates (concept expansion + resolved RELATED_TO links) in the END-TO-END entry point run_hybrid_query.
# OFF by default: the pre-declared KG-hardening evaluation (docs/E13_kg_hardening_rule.md,
# docs/E13_kg_hardening_results.md) did not pass its adoption rule (best pooled net +1, needed >= +2), so the graph list is
# excluded from fusion. Set True (or pass graph_enabled=True) to turn it back on; run_hybrid_retrieval, which takes explicit
# candidate lists, is unchanged.
GRAPH_ENABLED = False
GRAPH_DISABLED_TRACE = "graph disabled by config"

# Resolved RELATED_TO links as their OWN fusion list, independent of the gate graph weight
# (docs/E13_link_decoupling_rule.md). OFF until the pre-declared verdict says otherwise; LINK_WEIGHT is the fusion
# weight of the link list when it is on.
LINKS_ENABLED = False
LINK_WEIGHT = 0.30


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
        facts = fetch_customer_facts(customer_id, plan.structured_intents, as_of=as_of)
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
        vector, graph, _ = build_candidates(question, graph_enabled=use_graph)
        trace["graph"] = "graph enabled" if use_graph else GRAPH_DISABLED_TRACE
        use_links = LINKS_ENABLED if links_enabled is None else links_enabled
        links = []
        if use_links:
            ctx = retrievers.load_context()
            links = retrievers.link_candidates_for(vector, ctx["graph_index"], ctx["corpus"],
                                                   ctx["person_a"].load_chunk_text)
        trace["links"] = "links enabled" if use_links else "links disabled by config"
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
