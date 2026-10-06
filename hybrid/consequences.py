"""
Consequence terms shared by the answerer (silence rule, Phase 9b/9d) and the groundedness verifier (check R6).

CONSEQUENCE_TERMS maps a canonical name to hybrid/textmatch.py terms; a trailing "*" is an explicit open
stem, so "suspend" finds "suspension". SERVICE_LOSS_FAMILY groups the terms that all mean "the service is
taken away" - a passage that says "suspension" is relevant to a question that says "disconnected" even though
it does not use that word.
"""

from textmatch import has_term

CONSEQUENCE_TERMS = {
    "disconnect": ["disconnect*"],
    "suspend": ["suspen*"],
    "deactivate": ["deactivat*"],
    "terminate": ["terminat*"],
    "bar": ["bar", "barred", "barring"],
    "block": ["block*"],
    "penalty": ["penalt*"],
    "fee": ["fee"],
    "refund": ["refund*"],
    "charge": ["charg*"],
    "deadline": ["deadline"],
    "days": ["day"],
}

SERVICE_LOSS_FAMILY = ["suspend", "disconnect", "deactivate", "terminate", "bar", "block"]


def name_for_word(word: str):
    """Canonical consequence name whose terms match `word` ("suspension" -> "suspend"), or None."""
    for name, terms in CONSEQUENCE_TERMS.items():
        if has_term(word, terms):
            return name
    return None


def terms_for_word(word: str) -> list:
    """textmatch terms to look for when checking whether `word` appears in a text."""
    name = name_for_word(word)
    if name:
        return CONSEQUENCE_TERMS[name]
    word = (word or "").lower()
    return [word[:5] + "*"] if len(word) >= 6 else [word]
