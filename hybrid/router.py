"""
Query router (E13 Phase 7b, amended in Phase 8a) - decides which source(s) a question needs
and whether it may be answered for this session.

    route_query(question, customer_id, session_msisdn=None) -> RoutePlan

Builds on hybrid.query_gate.classify_query (imported). The gate supplies needs_personal_data,
concept_hint and the document graph weight; this module adds structured-intent detection, a
policy-cue check, and the identity / privacy guards. All keyword lists go through
hybrid/textmatch.py (word-start boundary + inflection), so "planet" is not "plan" and
"complaints" is "complaint".

Principles
  * personal question  = the gate says it is about the asker's own account AND at least one
    structured intent is detected (or the question names a phone number together with an intent).
    A personal-looking question with no supported intent is NOT sent to the structured source:
    there is nothing deterministic to fetch, and fabricating a lookup would be worse than docs.
  * personal + policy component -> both; personal only -> structured; otherwise -> unstructured.
  * identity: a question that needs the structured source with customer_id None -> needs_identity.
    The structured half never runs and nothing is invented; if the route is "both", the
    unstructured (document) half STILL runs.
  * privacy: a 10-digit phone number, or an explicit "customer <id>", that does not belong to the
    session customer -> refuse_other_customer. Ownership is resolved from customer_master (the
    session customer's own msisdn), never from the question text. A foreign number only triggers
    the refusal when the question has a structured intent or is otherwise personal.
  * third-party possessive (Phase 8a): "my mother's last recharge" is someone else's account:
    refuse_other_customer (reason third_party_reference) unless the question is a how-to
    ("How can I recharge for my mother?"), which goes to the documents only.
  * unrecognised personal request (Phase 8a): possessive phrasing ("my ...") with no supported
    intent and no policy cue keeps route unstructured and outcome answer, but sets a flag so the
    answer layer can say it could not tell which account detail was meant.
"""

import os
import re
import sys
from dataclasses import asdict, dataclass, field

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from query_gate import (  # noqa: E402
    PERSONAL_FACT_TERMS, POSSESSIVE_NUMBER_TERMS, POSSESSIVE_TERMS, classify_query, graph_weight,
)
from structured_adapter import lookup_msisdn  # noqa: E402
from textmatch import find_term, has_term  # noqa: E402

# ---------------------------------------------------------------------------
# Structured intents - textmatch terms (one list per adapter intent)
# ---------------------------------------------------------------------------
INTENT_TERMS = {
    "recharge": ["recharge", "top-up", "balance"],
    "kyc": ["e-kyc", "kyc", "identity verification"],
    # bare "expire" is deliberately NOT a cue: "my KYC has expired" is not a plan question
    "subscription": ["plan", "subscription", "subscribe", "validity", "expiry", "renewal", "pack"],
    "tickets": ["ticket", "complaint", "grievance", "service request", "escalation"],
    "invoice": ["bill", "billing", "invoice", "due", "payment", "paid", "unpaid", "overdue", "outstanding"],
}

# ---------------------------------------------------------------------------
# Policy cues: the question also asks about a rule, consequence or procedure (regular grammar,
# not keyword lists)
# ---------------------------------------------------------------------------
POLICY_CUES = [
    r"\bwill (?:that|this|it|they|the|i|my|we)\b",              # consequence: "will that ...", "will I be ..."
    r"\bdoes (?:that|this|it) mean\b",                          # consequence
    r"\bwhat happens\b",
    r"\bwhat (?:do|should|can|must) (?:i|we)\b",                # procedure: "what do I do"
    r"\bwhat (?:documents?|steps?|proof|process|procedure|options?)\b",
    # Phase 8a: "which documents do I have to submit", "what proof should I bring"
    r"\b(?:which|what) \w+ (?:do|should|must) (?:i|we) (?:(?:have|need|got|want) to )?"
    r"(?:submit|provide|bring|carry|need)\b",
    r"\bhow (?:do|can|should|to|long|many|soon)\b",             # how-to / duration
    r"\b(?:is|are) (?:it|this|that)? ?(?:allowed|permitted|possible|mandatory|required)\b",
    r"\bcan (?:the company|novatel|they|you)\b",                # permission questions about the operator
    r"\bcan i (?:still|get|claim|dispute|appeal)\b",
    r"\b(?:policy|rules?|regulations?|eligib\w+|entitled)\b",
    r"\bwhat (?:is|are) the (?:process|procedure|policy|rules?|timeline)\b",
]
_POLICY_RE = [re.compile(p, re.I) for p in POLICY_CUES]

# A how-to question about someone else's account is a document question, not a data request.
_HOWTO_RE = re.compile(r"\bhow (?:do|can|could|should|would) (?:i|we|you)\b|\bhow to\b", re.I)

# Phase 8a (f): another person's data. "my <relation>" (optionally possessive 's).
THIRD_PARTY_TERMS = [f"my {kin}" for kin in (
    "mother", "father", "mom", "dad", "wife", "husband", "son", "daughter", "brother", "sister",
    "friend", "colleague", "boss", "neighbour", "neighbor", "parent", "parents", "kid", "kids",
    "child", "children", "relative", "cousin", "uncle", "aunt")]

# ---------------------------------------------------------------------------
# Mentions of other people's data
# ---------------------------------------------------------------------------
_MSISDN_RE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?(\d{10})(?!\d)")
_CUSTOMER_ID_RE = re.compile(r"\b(?:customer|cust|account)(?:\s*(?:id|no\.?|number))?\s*#?:?\s*(\d{3,8})\b", re.I)


@dataclass
class RoutePlan:
    route: str                       # structured | unstructured | both
    outcome: str                     # answer | needs_identity | refuse_other_customer
    structured_intents: list = field(default_factory=list)
    has_policy_component: bool = False
    concept_hint: object = None
    graph_weight: float = 0.0
    reasoning: str = ""
    unrecognised_personal_request: bool = False
    refusal_reason: object = None    # e.g. "third_party_reference"

    def as_dict(self):
        return asdict(self)


def detect_intents(question: str) -> list:
    return [name for name, terms in INTENT_TERMS.items() if has_term(question, terms)]


def has_policy_component(question: str) -> bool:
    return any(rx.search(question or "") for rx in _POLICY_RE)


def _foreign_mentions(question, customer_id, own_msisdn):
    """Phone numbers / customer ids in the text that do not belong to the session customer."""
    foreign = []
    for number in _MSISDN_RE.findall(question or ""):
        if own_msisdn is None or number != str(own_msisdn)[-10:]:
            foreign.append(number)
    for cid in _CUSTOMER_ID_RE.findall(question or ""):
        if customer_id is None or str(cid) != str(customer_id):
            foreign.append(f"customer {cid}")
    return foreign


def route_query(question: str, customer_id=None, session_msisdn=None) -> RoutePlan:
    classification = classify_query(question)
    weight = graph_weight(classification)
    intents = detect_intents(question)
    policy = has_policy_component(question)

    own_msisdn = session_msisdn or lookup_msisdn(customer_id)
    mentioned = _MSISDN_RE.findall(question or "") + _CUSTOMER_ID_RE.findall(question or "")
    foreign = _foreign_mentions(question, customer_id, own_msisdn) if customer_id is not None else []

    third_party = find_term(question, THIRD_PARTY_TERMS, inflect=False)
    howto = bool(_HOWTO_RE.search(question or ""))
    has_fact = bool(find_term(question, PERSONAL_FACT_TERMS) or find_term(question, POSSESSIVE_NUMBER_TERMS))

    personal = bool(intents) and (classification["needs_personal_data"] or bool(mentioned))
    why = [classification["reasoning"], f"structured intents: {intents or 'none'}"]

    if third_party and howto:
        personal = False
        why.append(f"how-to about '{third_party.group(0)}' -> documents only, no account data")

    if personal and policy:
        route = "both"
    elif personal:
        route = "structured"
    else:
        route = "unstructured"
        if classification["needs_personal_data"] and not intents:
            why.append("personal-looking but no supported structured intent -> documents only")
    why.append(f"policy component: {policy}")

    outcome, refusal_reason = "answer", None
    if third_party and not howto and (intents or has_fact):
        outcome, refusal_reason = "refuse_other_customer", "third_party_reference"
        why.append(f"third_party_reference: '{third_party.group(0)}' refers to someone else's account")
    elif foreign and (personal or intents):
        outcome, refusal_reason = "refuse_other_customer", "other_customer_identifier"
        why.append(f"question names data not belonging to the session customer: {foreign}")
    elif route in ("structured", "both") and customer_id is None:
        outcome = "needs_identity"
        why.append("personal question without a session customer_id" +
                   ("; the document half still runs" if route == "both" else ""))
    elif customer_id is None and mentioned and (personal or intents):
        outcome = "needs_identity"
        why.append("question names a number/id but there is no session customer to verify ownership")

    unrecognised = bool(
        outcome == "answer" and route == "unstructured" and not intents and not policy
        and has_term(question, POSSESSIVE_TERMS, inflect=False) and not (third_party and howto))
    if unrecognised:
        why.append("unrecognised_personal_request: possessive phrasing but no supported account detail")

    return RoutePlan(route=route, outcome=outcome, structured_intents=intents if personal else [],
                     has_policy_component=policy, concept_hint=classification["concept_hint"],
                     graph_weight=weight, reasoning="; ".join(why),
                     unrecognised_personal_request=unrecognised, refusal_reason=refusal_reason)
