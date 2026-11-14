"""
Abstention ("I would not know about that"). Three layers, each recorded in the result:

  layer 1  ROUTER      the router says out_of_scope -> skip retrieval entirely.
  layer 2  RETRIEVAL   retrieval-confidence gate (this module): after retrieval, if
                       the evidence is too weak, abstain instead of generating.
  layer 3  GENERATOR   the prompt tells the model to answer ONLY from evidence and
                       to emit INSUFFICIENT_EVIDENCE otherwise (generation.py).

Layer 2 specifics
  * structured evidence is exact: usable iff the parser resolved a table AND at
    least one row/count came back. There is no score to threshold.
  * unstructured evidence: usable iff sigmoid(top CrossEncoder logit) >= threshold.
    The sigmoid is a monotone normalisation of an unbounded logit so a single
    number in [0, 1] can be calibrated; it is NOT a calibrated probability. The
    threshold is chosen on the VALIDATION abstention set (see
    integration/eval/calibrate_abstention.py) and stored, with the method used, in
    data/eval/system_calibration.json.
  * hybrid abstains only if NEITHER half has usable evidence; one usable half
    leads to an honest partial answer instead (see generation.py half-answerable rule).
  * a user-facing abstention carries no citations.
"""

from __future__ import annotations

from integration.qa.config import QAConfig


def structured_usable(evidence: list[dict]) -> bool:
    return len(evidence) > 0


def unstructured_usable(diag: dict | None, cfg: QAConfig) -> bool:
    if not diag or diag.get("top_crossencoder_sigmoid") is None:
        return False
    return diag["top_crossencoder_sigmoid"] >= cfg.retrieval_conf_threshold


def retrieval_gate(route: str, structured_ev: list[dict], unstructured_ev: list[dict],
                   unstructured_diag: dict | None, cfg: QAConfig) -> dict:
    """Decide whether the retrieved evidence is good enough to answer from.

    Returns {abstain, reason, structured_usable, unstructured_usable}.
    """
    s_ok = structured_usable(structured_ev)
    u_ok = bool(unstructured_ev) and unstructured_usable(unstructured_diag, cfg)

    if route == "structured":
        abstain, reason = (not s_ok), ("no structured record or count was found" if not s_ok else "")
    elif route == "unstructured":
        top = (unstructured_diag or {}).get("top_crossencoder_sigmoid")
        abstain = not u_ok
        reason = (f"top document relevance {top} is below the calibrated threshold "
                  f"{cfg.retrieval_conf_threshold}") if abstain else ""
    else:  # hybrid
        abstain = not (s_ok or u_ok)
        reason = "neither the database nor the documents contain usable evidence" if abstain else ""
    return {"abstain": abstain, "reason": reason, "structured_usable": s_ok, "unstructured_usable": u_ok}


def abstention_result_text(cfg: QAConfig) -> str:
    return cfg.abstention_message
