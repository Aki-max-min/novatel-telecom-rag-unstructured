"""
Clause-level analysis of a question (E13 Phase 8e).

split_clauses(question) -> [(clause_text, kind), ...]

A question can mix a statement about the customer's own account with a rule question
("My bill is unpaid - if I don't pay, will my number be cut?"). Question-level frames cannot tell
those apart, so each clause is classified on its own.

Boundaries: sentence boundaries are . ? ! ; (followed by whitespace or the end). Inside a sentence
the question is further split on spaced dashes (" - ", " - ", " - ") and commas.

Kind of each clause - the FIRST match wins:
  1 HYPOTHETICAL  the clause contains "if", "suppose", "assuming", "in case", "what if" or "what happens if"
                  followed by ANY subject, or "when / whenever / after / before" followed by I or we.
                  ("when/after/before" + an auxiliary is a wh-question word, not a hypothetical:
                  "When does my plan expire?" is not hypothetical.)
                  Conditional inheritance: every clause AFTER a hypothetical clause up to the next sentence
                  boundary is also HYPOTHETICAL (the consequent of the same conditional). Clauses before it are
                  independent.
  1b POLICY (permission / ability cues: can I, could I, may I, am I allowed, are we allowed, is it possible,
     is it allowed, do I need to / have to + verb, must I, should I, will I be able to) - takes precedence over
     STATUS_QUERY and ASSERTION (added after the Phase 8e probes).
  2 STATUS_QUERY  an auxiliary (did|has|have|had|is|are|was|were|does|do|will) within 6 words of my/I, together
                  with a fact term in the clause; or what/which/when/how much/how many + auxiliary ... my/I + fact;
                  or "status of my" + fact.
  3 POLICY        consequence or how-to cues (POLICY_CUES below).
  4 ASSERTION     a possessive (my/mine) + a fact term, in a clause that matched none of the above - a declarative
                  statement about the customer's own account ("my X failed", "my Y is unpaid").
  5 OTHER

personal = any clause is STATUS_QUERY or ASSERTION.
has_policy_component = any clause is HYPOTHETICAL or POLICY.

All term matching goes through hybrid/textmatch.py (word-start boundary + inflection). The regular grammar patterns
(auxiliary windows, policy cues) are not keyword lists.
"""

import re

from textmatch import find_term, has_term

HYPOTHETICAL = "HYPOTHETICAL"
STATUS_QUERY = "STATUS_QUERY"
POLICY = "POLICY"
ASSERTION = "ASSERTION"
OTHER = "OTHER"

# --- cue lists ---------------------------------------------------------------------------------------
# Followed by ANY subject: the word alone is the cue.
HYPOTHETICAL_ANY_SUBJECT_TERMS = ["if", "suppose", "assuming", "in case", "what if", "what happens if"]
# Only hypothetical when followed by I / we (otherwise "when does ..." is a wh-question).
HYPOTHETICAL_PRONOUN_TERMS = [f"{w} {p}" for w in ("when", "whenever", "after", "before") for p in ("i", "we")]

POSSESSIVE_TERMS = ["my", "mine"]
_STATUS_AUX = r"(?:did|has|have|had|is|are|was|were|does|do|will)"
_ANCHOR = r"(?:my|mine|i)"
_WINDOW = r"(?:\W+\w+){0,6}?\W+"   # "within 6 words"
STATUS_QUERY_FRAMES = [
    # aux (+ up to 6 words) + my/I: "Did my recharge ...", "Have I been charged ...", "Are there any open ... on my"
    re.compile(rf"\b{_STATUS_AUX}\b{_WINDOW}{_ANCHOR}\b", re.I),
    # wh-frame, optionally one noun in between, then aux ... my/I: "When does my plan ...", "How many tickets do I have"
    re.compile(rf"\b(?:what|which|when|how much|how many)(?:\s+\w+)?\s+{_STATUS_AUX}\b{_WINDOW}{_ANCHOR}\b", re.I),
    re.compile(r"\bstatus of my\b", re.I),
]

# Consequence / how-to / permission cues. (These are the Phase 7b/8a router cues, moved here so there is one list.)
POLICY_CUES = [
    r"\bwill (?:that|this|it|they|the|i|my|we)\b",              # consequence: "will that ...", "will I be ..."
    r"\bdoes (?:that|this|it) mean\b",                          # consequence
    r"\bwhat happens\b",
    r"\bwhat (?:do|should|can|must) (?:i|we)\b",                # procedure: "what do I do", "what should I do next"
    r"\bwhat (?:documents?|steps?|proof|process|procedure|options?)\b",
    r"\b(?:which|what) \w+ (?:do|should|must) (?:i|we) (?:(?:have|need|got|want) to )?"
    r"(?:submit|provide|bring|carry|need)\b",
    r"\bhow (?:do|can|should|to|long|many|soon)\b",             # how-to / duration ("how long until ...")
    r"\b(?:is|are) (?:it|this|that)? ?(?:allowed|permitted|possible|mandatory|required)\b",
    r"\bcan (?:the company|novatel|they|you)\b",                # permission questions about the operator
    r"\bcan i (?:still|get|claim|dispute|appeal)\b",
    r"\b(?:policy|rules?|regulations?|eligib\w+|entitled)\b",
    r"\bwhat (?:is|are) the (?:process|procedure|policy|rules?|timeline)\b",
]
_POLICY_RE = [re.compile(p, re.I) for p in POLICY_CUES]

# Permission / ability cues (the single Phase 8e probe-driven extension). They are POLICY cues that take
# PRECEDENCE over STATUS_QUERY and ASSERTION (but not over HYPOTHETICAL): "Can I change my plan ...?" asks
# whether something is allowed, not about the account's current state. "do I have to / need to" requires a
# following verb, so "Do I have any open tickets?" stays a STATUS_QUERY.
PERMISSION_CUES = [
    r"\b(?:can|could|may) (?:i|we)\b",
    r"\b(?:am i|are we) allowed\b",
    r"\bis it (?:possible|allowed)\b",
    r"\bdo (?:i|we) (?:need|have) to [a-z]+\b",
    r"\bmust (?:i|we)\b",
    r"\bshould (?:i|we)\b",
    r"\bwill (?:i|we) be able to\b",
]
_PERMISSION_RE = [re.compile(p, re.I) for p in PERMISSION_CUES]

_SENTENCE = re.compile(r"(?<=[.?!;])\s+")
_DASH = re.compile(r"\s[-–—]\s")


def is_hypothetical(clause: str) -> bool:
    return (has_term(clause, HYPOTHETICAL_ANY_SUBJECT_TERMS, inflect=False)
            or has_term(clause, HYPOTHETICAL_PRONOUN_TERMS, inflect=False))


def has_policy_cue(clause: str) -> bool:
    return any(rx.search(clause) for rx in _POLICY_RE)


def _has_fact(clause, fact_terms, number_terms):
    return bool(find_term(clause, fact_terms) or find_term(clause, number_terms))


def _has_status_frame(clause) -> bool:
    return any(rx.search(clause) for rx in STATUS_QUERY_FRAMES)


def _fact_terms(fact_terms, number_terms):
    if fact_terms is None or number_terms is None:  # defaults come from the gate's lists (lazy: no import cycle)
        import query_gate
        fact_terms = query_gate.PERSONAL_FACT_TERMS if fact_terms is None else fact_terms
        number_terms = query_gate.POSSESSIVE_NUMBER_TERMS if number_terms is None else number_terms
    return fact_terms, number_terms


def split_clauses(question: str, fact_terms=None, number_terms=None) -> list:
    """[(clause_text, kind), ...] in textual order. Empty / None input gives []."""
    fact_terms, number_terms = _fact_terms(fact_terms, number_terms)
    out = []
    for sentence in _SENTENCE.split((question or "").strip()):
        hypothetical_seen = False  # conditional inheritance is per sentence
        for part in _DASH.split(sentence):
            for raw in part.split(","):
                clause = raw.strip().rstrip(".?!;").strip()
                if not clause:
                    continue
                if hypothetical_seen or is_hypothetical(clause):
                    hypothetical_seen = True
                    kind = HYPOTHETICAL
                elif any(rx.search(clause) for rx in _PERMISSION_RE):
                    kind = POLICY
                elif _has_status_frame(clause) and _has_fact(clause, fact_terms, number_terms):
                    kind = STATUS_QUERY
                elif has_policy_cue(clause):
                    kind = POLICY
                elif has_term(clause, POSSESSIVE_TERMS, inflect=False) and _has_fact(clause, fact_terms, number_terms):
                    kind = ASSERTION
                else:
                    kind = OTHER
                out.append((clause, kind))
    return out


def summarize(clauses) -> dict:
    kinds = [k for _, k in clauses]
    return {
        "personal": any(k in (STATUS_QUERY, ASSERTION) for k in kinds),
        "has_policy_component": any(k in (HYPOTHETICAL, POLICY) for k in kinds),
        "hypothetical": HYPOTHETICAL in kinds,
    }
