# =============================================================================
# PROTOTYPE v1 - rule-based first draft for Person A's review. Query
# understanding is joint-design territory per E13 roadmap Section 7
# (docs/E13_Hybrid_Fusion_Roadmap.md, Section 7).
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

POST-HOC FIXES (Phase 8a, made AFTER seeing the frozen-benchmark first run; see
docs/E13_phase8_posthoc_log.md): every keyword list now goes through hybrid/textmatch.py
(word-start boundary + inflection), which fixes plurals ("complaints", "tickets") that the old
mixed word-start / whole-word matching missed; "promo" no longer matches "promotional";
bare "number" no longer makes a question personal; unsolicited-communication questions
(promotional/marketing/spam + sms/message/call/text) get no concept hint, because that topic
(e.g. DND) has no concept in the shared vocabulary (concept_bridge.py: no DND table exists);
handset+5G/VoLTE and enterprise+plan questions get Device Compatibility / Enterprise & Business
Services hints when those concepts exist in the vocabulary.
"""

import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from knowledge_graph.concept_bridge import (  # noqa: E402
    SERVICE_CONCEPT_MAPPING,
    concept_vocabulary,
    load_crosswalk,
)
from textmatch import find_term, has_term  # noqa: E402

CONCEPT_VOCABULARY = concept_vocabulary(load_crosswalk())

# Keyword -> canonical concept (terms use hybrid/textmatch.py syntax: word-start boundary +
# inflection). Values must be vocabulary concepts; anything else fails loudly below rather than
# forming a parallel list.
KEYWORD_CONCEPT_MAP = {
    "recharge": "Recharge",
    "top-up": "Recharge",
    "plan": "Plan Catalogue",
    "validity": "Plan Catalogue",
    "expire": "Plan Catalogue",
    "expiry": "Plan Catalogue",
    "subscription": "Subscription",
    "kyc": "KYC & Identity Verification",
    "aadhaar": "KYC & Identity Verification",
    "bill": "Billing & Invoices",
    "invoice": "Billing & Invoices",
    "payment": "Payments",
    "refund": "Payments",
    "port": "Number Portability",
    "porting": "Number Portability",
    "portability": "Number Portability",
    "mnp": "Number Portability",
    "roaming": "Roaming",
    "sim": "SIM Card Services",
    "esim": "SIM Card Services",
    "complaint": "Complaints & Grievances",
    "ticket": "Complaints & Grievances",
    "grievance": "Complaints & Grievances",
    "outage": "Network Outages",
    "coverage": "Network Coverage",
    "5g": "Network Coverage",
    "broadband": "Broadband & FTTH Services",
    "fiber": "Broadband & FTTH Services",
    "fibre": "Broadband & FTTH Services",
    "ftth": "Broadband & FTTH Services",
    "offer": "Offers & Promotions",
    "promo": "Offers & Promotions",
    "promotion": "Offers & Promotions",
    "fraud": "Security & Fraud",
    "scam": "Security & Fraud",
    "device": "Device Compatibility",
    "store": "Retail & Store Network",
    "outlet": "Retail & Store Network",
    "data usage": "Usage Records",
    "call record": "Usage Records",
    "call detail": "Usage Records",
    "vas": "Value Added Services",
    "activation": "New Connection Activation",
}

_unknown = set(KEYWORD_CONCEPT_MAP.values()) - set(CONCEPT_VOCABULARY)
if _unknown:
    raise ValueError(f"query_gate keywords point at concepts not in the vocabulary: {_unknown}")

# Also match the vocabulary's own names / document service names (e.g. "number portability").
_NAME_CONCEPTS = {name.lower(): name for name in CONCEPT_VOCABULARY}
_NAME_CONCEPTS.update({svc.lower(): c for svc, c in SERVICE_CONCEPT_MAPPING.items()})

# (d) Combination rules that beat the single-keyword hint: both term groups must be present.
# A target concept that is NOT in the shared vocabulary is never forced (the hint stays whatever
# the keywords gave) and is listed in MISSING_CONCEPT_TARGETS.
COMBO_RULES = [
    {"any_of": ["handset", "phone", "device"], "and_any_of": ["5g", "volte"],
     "concept": "Device Compatibility"},
    {"any_of": ["enterprise", "business", "corporate"], "and_any_of": ["plan", "connectivity", "sim"],
     "concept": "Enterprise & Business Services"},
]
MISSING_CONCEPT_TARGETS = sorted({r["concept"] for r in COMBO_RULES} - set(CONCEPT_VOCABULARY))

# (a) Unsolicited communication (spam / telemarketing, e.g. the DND topic) has NO concept in the
# vocabulary, so it must not borrow "Offers & Promotions": hint None, graph weight 0.0.
UNSOLICITED_QUALIFIERS = ["promotional", "marketing", "spam", "unsolicited", "telemarketing"]
COMMUNICATION_CHANNELS = ["sms", "message", "call", "text"]

# First-person references: exact whole words, no inflection ("i" + "s" would be "is")
FIRST_PERSON_TERMS = ["my", "mine", "i", "i've", "i'm", "i'd", "me"]
POSSESSIVE_TERMS = ["my", "mine"]

# Account-level facts a customer could ask about. Personal data needs BOTH a first-person
# reference and one of these; "I" alone (policy questions) is not enough. (b) bare "number" is
# not a fact; it only counts inside a possessive phrase ("my number", "my mobile number").
PERSONAL_FACT_TERMS = [
    "recharge", "top-up", "balance", "ticket", "complaint", "kyc", "invoice", "bill", "payment",
    "plan", "validity", "expir*", "subscription", "status", "order", "data usage", "usage",
]
POSSESSIVE_NUMBER_TERMS = ["my number", "my mobile number", "my phone number", "my sim number"]

# "How do I ...?" is a procedure question even though it says "I" (no "my").
_HOWTO = re.compile(r"\bhow (?:do|can|should|to) (?:i|we)\b|\bhow to\b", re.I)


def _concept_hint(lowered: str):
    """(concept, trigger) for the question, or (None, explanation)."""
    if has_term(lowered, UNSOLICITED_QUALIFIERS, inflect=False) and has_term(lowered, COMMUNICATION_CHANNELS):
        return None, "unsolicited-communication question (no concept in the vocabulary)"

    for rule in COMBO_RULES:
        a = find_term(lowered, rule["any_of"])
        b = find_term(lowered, rule["and_any_of"])
        if a and b and rule["concept"] in CONCEPT_VOCABULARY:
            return rule["concept"], f"{a.group(0)}+{b.group(0)}"

    hits = []  # (position, -length, concept, trigger)
    for term, concept in KEYWORD_CONCEPT_MAP.items():
        m = find_term(lowered, [term])
        if m:
            hits.append((m.start(), -len(m.group(0)), concept, m.group(0)))
    for name, concept in _NAME_CONCEPTS.items():
        m = find_term(lowered, [name])
        if m:
            hits.append((m.start(), -len(m.group(0)), concept, m.group(0)))
    if hits:
        _, _, hint, trigger = min(hits)
        return hint, trigger
    return None, None


def classify_query(question: str) -> dict:
    """Classify a question. Never raises; empty/None input yields the null result."""
    text = (question or "").strip()
    if not text:
        return {"needs_personal_data": False, "concept_hint": None,
                "reasoning": "empty question: no signal"}
    lowered = text.lower()

    hint, trigger = _concept_hint(lowered)

    # --- personal data ---
    first_person = find_term(text, FIRST_PERSON_TERMS, inflect=False)
    fact = find_term(text, PERSONAL_FACT_TERMS) or find_term(text, POSSESSIVE_NUMBER_TERMS)
    howto = _HOWTO.search(text) and not has_term(text, POSSESSIVE_TERMS, inflect=False)
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
    if hint:
        parts.append(f"concept '{hint}' via '{trigger}'")
    else:
        parts.append(trigger or "no concept keyword matched")
    return {"needs_personal_data": needs_personal, "concept_hint": hint,
            "reasoning": "; ".join(parts)}


def graph_weight(classification: dict) -> float:
    """Conditional graph-fusion weight from a classify_query() result."""
    if classification.get("concept_hint") is None:
        # No shared concept to bridge on: pure vector, the roadmap default
        # (graph fusion regressed on the main benchmark - docs/E13_Hybrid_Fusion_Roadmap.md, Section 3).
        return 0.0
    if classification.get("needs_personal_data"):
        # Concept + personal data: graph-dependent questions were a real win;
        # 0.5 is the weight validated in graph_augmented_retrieval.py's evaluation.
        return 0.5
    # Concept but no personal data: document-graph expansion only, light touch
    # (docs/E13_Hybrid_Fusion_Roadmap.md, Section 3: graph helps a little on concept-bearing questions, but
    # hurts when over-weighted on the plain benchmark).
    return 0.15


def explain_gate(question: str) -> dict:
    """classify_query + graph_weight in one dict, for manual review/debugging."""
    classification = classify_query(question)
    return {"question": question, "classification": classification,
            "graph_weight": graph_weight(classification)}
