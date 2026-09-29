# =============================================================================
# PROTOTYPE v1 - rule-based first draft for Person A's review. Query
# understanding is joint-design territory per E13 roadmap Section 7.
# Replace/extend freely.
# =============================================================================
"""
Query understanding + concept gate (v1 prototype).

Decides how much weight the graph channel should get for a question:

    classify_query(q)  -> needs_personal_data / concept_hint / reasoning
    graph_weight(c)    -> 0.5 | 0.15 | 0.0
    explain_gate(q)    -> both of the above plus the final weight (for review)

Rule-based only, in the spirit of structured/query_parser.py (keyword/pattern
maps, no ML). The concept vocabulary is NOT redefined here: it is read from the
ontology crosswalk via knowledge_graph.concept_bridge, and every keyword below
must point at a concept that exists in that vocabulary (checked at import).
"""

import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from knowledge_graph.concept_bridge import (  # noqa: E402
    SERVICE_CONCEPT_MAPPING,
    concept_vocabulary,
    load_crosswalk,
)

CONCEPT_VOCABULARY = concept_vocabulary(load_crosswalk())

# Keyword -> canonical concept. Keywords are regex fragments matched at a word
# start (so "promo" also catches "promotional"). Values must be vocabulary
# concepts; anything else fails loudly below rather than forming a parallel list.
KEYWORD_CONCEPT_MAP = {
    r"recharge": "Recharge",
    r"top-?up": "Recharge",
    r"plan": "Plan Catalogue",
    r"validity": "Plan Catalogue",
    r"expire": "Plan Catalogue",
    r"subscription": "Subscription",
    r"kyc": "KYC & Identity Verification",
    r"aadhaar": "KYC & Identity Verification",
    r"bill": "Billing & Invoices",
    r"invoice": "Billing & Invoices",
    r"payment": "Payments",
    r"refund": "Payments",
    r"port(?:ing|ability|ed)?\b": "Number Portability",
    r"mnp": "Number Portability",
    r"roaming": "Roaming",
    r"sim\b": "SIM Card Services",
    r"esim": "SIM Card Services",
    r"complaint": "Complaints & Grievances",
    r"ticket": "Complaints & Grievances",
    r"grievance": "Complaints & Grievances",
    r"outage": "Network Outages",
    r"coverage": "Network Coverage",
    r"5g": "Network Coverage",
    r"broadband": "Broadband & FTTH Services",
    r"fib(?:er|re)": "Broadband & FTTH Services",
    r"ftth": "Broadband & FTTH Services",
    r"offer": "Offers & Promotions",
    r"promo": "Offers & Promotions",
    r"fraud": "Security & Fraud",
    r"scam": "Security & Fraud",
    r"device": "Device Compatibility",
    r"store\b": "Retail & Store Network",
    r"outlet": "Retail & Store Network",
    r"data usage": "Usage Records",
    r"call (?:record|detail)": "Usage Records",
    r"vas\b": "Value Added Services",
    r"activation": "New Connection Activation",
}

_unknown = set(KEYWORD_CONCEPT_MAP.values()) - set(CONCEPT_VOCABULARY)
if _unknown:
    raise ValueError(f"query_gate keywords point at concepts not in the vocabulary: {_unknown}")

# Also match the vocabulary's own names / document service names verbatim
# (e.g. "number portability", "roaming activation").
_NAME_CONCEPTS = {name.lower(): name for name in CONCEPT_VOCABULARY}
_NAME_CONCEPTS.update({svc.lower(): c for svc, c in SERVICE_CONCEPT_MAPPING.items()})

# First-person references ("my", "I", "I've", "me")
_FIRST_PERSON = re.compile(r"\b(?:my|mine|i|i've|i'm|i'd|me)\b", re.I)

# Account-level facts a customer could ask about. Personal data needs BOTH a
# first-person reference and one of these; "I" alone (policy questions) is not enough.
_PERSONAL_FACT = re.compile(
    r"\b(?:recharge|top-?up|balance|ticket|complaint|kyc|invoice|bill|payment|"
    r"plan|validity|expir\w*|subscription|status|order|data usage|usage|number)\b",
    re.I,
)

# "How do I ...?" is a procedure question even though it says "I" (no "my").
_HOWTO = re.compile(r"\bhow (?:do|can|should|to) (?:i|we)\b|\bhow to\b", re.I)
_POSSESSIVE = re.compile(r"\b(?:my|mine)\b", re.I)


def classify_query(question: str) -> dict:
    """Classify a question. Never raises; empty/None input yields the null result."""
    text = (question or "").strip()
    if not text:
        return {"needs_personal_data": False, "concept_hint": None,
                "reasoning": "empty question: no signal"}
    lowered = text.lower()

    # --- concept hint: earliest match in the text wins (ties -> longer match) ---
    hits = []  # (position, -length, concept, trigger)
    for pattern, concept in KEYWORD_CONCEPT_MAP.items():
        m = re.search(r"\b" + pattern, lowered)
        if m:
            hits.append((m.start(), -len(m.group(0)), concept, m.group(0)))
    for name, concept in _NAME_CONCEPTS.items():
        pos = lowered.find(name)
        if pos != -1:
            hits.append((pos, -len(name), concept, name))
    hint, trigger = None, None
    if hits:
        _, _, hint, trigger = min(hits)

    # --- personal data ---
    first_person = _FIRST_PERSON.search(text)
    fact = _PERSONAL_FACT.search(text)
    howto = _HOWTO.search(text) and not _POSSESSIVE.search(text)
    needs_personal = bool(first_person and fact and not howto)

    parts = []
    if needs_personal:
        parts.append(f"first-person '{first_person.group(0)}' + account fact '{fact.group(0)}' -> personal data")
    elif howto:
        parts.append("how-to phrasing without 'my' -> treated as a procedure question, not personal data")
    elif first_person:
        parts.append(f"first-person '{first_person.group(0)}' but no account fact -> policy-style, not personal data")
    else:
        parts.append("no first-person reference -> not personal data")
    parts.append(f"concept '{hint}' via '{trigger}'" if hint else "no concept keyword matched")
    return {"needs_personal_data": needs_personal, "concept_hint": hint,
            "reasoning": "; ".join(parts)}


def graph_weight(classification: dict) -> float:
    """Conditional graph-fusion weight from a classify_query() result."""
    if classification.get("concept_hint") is None:
        # No shared concept to bridge on: pure vector, the roadmap default
        # (graph fusion regressed on the main benchmark - roadmap Section 3).
        return 0.0
    if classification.get("needs_personal_data"):
        # Concept + personal data: graph-dependent questions were a real win;
        # 0.5 is the weight validated in graph_augmented_retrieval.py's evaluation.
        return 0.5
    # Concept but no personal data: document-graph expansion only, light touch
    # (roadmap Section 3: graph helps a little on concept-bearing questions, but
    # hurts when over-weighted on the plain benchmark).
    return 0.15


def explain_gate(question: str) -> dict:
    """classify_query + graph_weight in one dict, for manual review/debugging."""
    classification = classify_query(question)
    return {"question": question, "classification": classification,
            "graph_weight": graph_weight(classification)}
